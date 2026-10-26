#!/usr/bin/env bash
# Mirror the WebSphere Application Server for Developers offering from IBM into
# the lab VM's local Installation Manager repository.
#
#   bash ci/k3s/lab-mirror-was.sh --check    preconditions only, changes nothing
#   bash ci/k3s/lab-mirror-was.sh            the whole thing
#
# Run it from the k3s node, like make-lab-vm.sh: it resolves the VM address
# from the cluster and drives the VM over SSH.
#
# WHY A SCRIPT AND NOT A PLAYBOOK. One step is irreducibly interactive. The IBM
# download site wants an IBMid, and Installation Manager's own advice when it
# refuses is "use the -prompt option to receive a credential prompt; the
# credentials are saved to the secure storage file". That prompt needs a TTY,
# which an AWX job pod does not have. So the credential is captured here, once,
# by a human, and every later run - including the Ansible install job - reads
# the secure storage file and carries no secret of its own.
#
# WHAT THIS DOES NOT DO. It does not install WAS. It fills the media directory
# on the VM with a real Installation Manager repository, which is what
# roles/traditional/was_install looks for. The install stays in the playbook,
# where the discovery, the asserts and the logging already live.

set -euo pipefail

# Paths mirror inventories/lab/group_vars/all/25_install_dirs.yml. Overridable
# so this script does not become a second place where the layout is decided.
NS="${WAS_LAB_NS:-was-lab}"
VM="${WAS_LAB_VM:-was-lab-01}"
KEY="${WAS_LAB_KEY:-$HOME/.ssh/was_lab}"
VM_USER="${WAS_LAB_USER:-ansible}"

IMTOOLS="${IM_TOOLS_DIR:-/app/binaries/InstallationManager/eclipse/tools}"
IMSHARED="${IM_SHARED_DIR:-/app/binaries/IMShared}"
IMDATA="${IM_AGENT_DATA_DIR:-/app/data/IM/agentdata}"
IMLOGS="${IM_LOG_DIR:-/app/logs/IM}"
PU_DIR="${PU_DIR:-/app/binaries/PackagingUtility}"
TARGET="${WAS_MEDIA_DIR:-/mnt/binaries/IBM/install_was90}"

SECSTORE="${IM_SECURE_STORAGE:-/app/data/IM/im.creds}"
MASTERPW="${IM_MASTER_PASSWORD_FILE:-/app/data/IM/im.master}"

# The ILAN composite repository. ILAN - International License Agreement for
# Non-Warranted Programs - is the licence the "for Developers" edition ships
# under. IBM's repository table has no entry called "Developers"; this is it.
REPO="${WAS_ILAN_REPO:-https://www.ibm.com/software/repositorymanager/V9WASILAN}"
# The composite carries 658 packages - BASE, ILAN, Liberty, z/OS, every level of
# each - so a loose com.ibm.websphere. prefix is not a filter, it is a lottery
# whose most recent entry happens to be a Liberty z/OS build. Name the offering.
# ILAN.v90 is the "for Developers" edition.
WAS_OFFERING_ID="${WAS_OFFERING_ID:-com.ibm.websphere.ILAN.v90}"
SDK_OFFERING_ID="${SDK_OFFERING_ID:-com.ibm.java.jdk.v8}"
PUREPO="${PU_REPO:-https://www.ibm.com/software/repositorymanager/com.ibm.cic.packagingUtility}"

# WAS 9.0 fix packs require this floor, and so does the install.
IM_MIN_VERSION="1.8.5"
# The offering is around 2.5 GB and the copy needs room to verify.
MIN_FREE_MB="${MIN_FREE_MB:-6000}"

CHECK_ONLY=false
RESET_CREDS=false
UNLOCK=false
for arg in "$@"; do
    case "$arg" in
        --check)        CHECK_ONLY=true ;;
        --reset-creds)  RESET_CREDS=true ;;
        --unlock)       UNLOCK=true ;;
        *) printf 'usage: %s [--check] [--reset-creds] [--unlock]\n' "${0##*/}" >&2; exit 2 ;;
    esac
done

say() { printf '\n== %s\n' "$*"; }
ok()  { printf '   ok    %s\n' "$*"; }
bad() { printf '   FAIL  %s\n' "$*" >&2; }
die() { bad "$*"; exit 1; }

# ---------------------------------------------------------------------------
# 1. The cluster
# ---------------------------------------------------------------------------
say "1. Cluster"

# /usr/local/bin/kubectl on a k3s node is a symlink to k3s, and that wrapper
# defaults to /etc/rancher/k3s/k3s.yaml - root-owned, mode 0600. With KUBECONFIG
# unset it fails with a permission error that reads like a cluster problem and
# is not. This is the single most common way this procedure dies on line one.
if [ -z "${KUBECONFIG:-}" ] && [ -r "$HOME/.kube/config" ]; then
    export KUBECONFIG="$HOME/.kube/config"
    ok "KUBECONFIG was unset; using $KUBECONFIG"
fi
kubectl version --client >/dev/null 2>&1 || die "no usable kubectl"
kubectl get ns "$NS" >/dev/null 2>&1 || die "namespace $NS not found - run make-lab-vm.sh first"
ok "namespace $NS"

PHASE="$(kubectl -n "$NS" get vmi "$VM" -o jsonpath='{.status.phase}' 2>/dev/null || true)"
[ "$PHASE" = "Running" ] || die "vmi $VM is '${PHASE:-absent}', not Running"
ok "vmi $VM Running"

IP="$(kubectl -n "$NS" get vmi "$VM" -o jsonpath='{.status.interfaces[0].ipAddress}')"
[ -n "$IP" ] || die "vmi $VM reports no address yet"
ok "address $IP"

# ---------------------------------------------------------------------------
# 2. The VM
# ---------------------------------------------------------------------------
say "2. VM"

[ -f "$KEY" ] || die "no private key at $KEY (set WAS_LAB_KEY)"
ok "key $KEY"

SSH_OPTS=(-i "$KEY" -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o LogLevel=ERROR)
# -n: ssh reads stdin by default and would swallow the rest of this script when
# it is piped in rather than run from a file. The one call that needs stdin -
# handing the password to the VM - uses ssh directly instead of this helper.
vm() { ssh -n "${SSH_OPTS[@]}" "$VM_USER@$IP" "$@"; }

vm true 2>/dev/null || die "cannot ssh $VM_USER@$IP with $KEY"
ok "ssh as $VM_USER"

# The install role runs imcl with become, so Installation Manager is an ADMIN
# installation: imcl as the service account fails with CRIMC1018E. Everything
# below therefore goes through sudo, and sudo has to be passwordless because
# most of these calls have no TTY to type a password into.
vm "sudo -n true" 2>/dev/null || die "passwordless sudo does not work on the VM"
ok "passwordless sudo"

vm "test -x $IMTOOLS/imcl" || die "no imcl at $IMTOOLS/imcl - run the lab_install_im.yml job first"
IMVER="$(vm "sudo $IMTOOLS/imcl version" | awk -F': *' '/^Version:/ {print $2; exit}')"
[ -n "$IMVER" ] || die "could not read the Installation Manager version"
# Version compare, not string compare: 1.10.1.4 is above 1.8.5 and sorts below it.
if [ "$(printf '%s\n%s\n' "$IM_MIN_VERSION" "$IMVER" | sort -V | head -1)" != "$IM_MIN_VERSION" ]; then
    die "Installation Manager $IMVER is below the required $IM_MIN_VERSION"
fi
ok "Installation Manager $IMVER (>= $IM_MIN_VERSION)"

# An Installation Manager abandoned at an interactive prompt keeps holding
# /app/data/IM/agentdata/.imlock, and every later call then dies on CRIMA1130E
# rather than on anything to do with this procedure. Catch it here, by name.
# The bracket in '[e]clipse' is not cosmetic. ssh runs this pattern inside a
# remote shell whose own command line contains it, so a plain pgrep -f matches
# that shell and reports a running Installation Manager every single time -
# and a plain pkill -f kills the shell it is running in, which ends this script
# with no output at all. The class matches the real process and not the text.
IM_PATTERN='[e]clipse/tools/imcl'
# The .imlock FILE is a normal artefact and stays behind; the lock itself is an
# flock held by a live process. So only the process matters here, and deleting
# that file fixes nothing.
if vm "pgrep -f '$IM_PATTERN' >/dev/null 2>&1"; then
    if $UNLOCK; then
        # pkill exits 1 when it matched nothing, which is not an error here.
        vm "sudo pkill -f '$IM_PATTERN' || true"
        if vm "pgrep -f '$IM_PATTERN' >/dev/null 2>&1"; then
            die "an Installation Manager survived the kill - look at it by hand"
        fi
        ok "killed the abandoned Installation Manager"
    else
        bad "an Installation Manager is already running on the VM and holds the lock"
        printf '\n   Finish it in the terminal that started it, or pass --unlock to\n   this script to kill it and remove the lock.\n\n'
        exit 1
    fi
else
    ok "no Installation Manager holding the lock"
fi

TARGET_PARENT="$(dirname "$TARGET")"
FREE_MB="$(vm "df -Pm $TARGET_PARENT 2>/dev/null | awk 'NR==2 {print \$4}'" || true)"
[ -n "$FREE_MB" ] || FREE_MB=0
[ "$FREE_MB" -ge "$MIN_FREE_MB" ] || die "only ${FREE_MB} MB free at $TARGET_PARENT; ${MIN_FREE_MB} MB wanted"
ok "${FREE_MB} MB free at $TARGET_PARENT"

# ---------------------------------------------------------------------------
# 3. Egress to IBM
# ---------------------------------------------------------------------------
say "3. Egress"

# A 2xx is neither expected nor wanted: these URLs are not browsable and IBM
# answers a redirect. Anything that is not a connection failure proves the only
# thing under test here, which is that the VM can reach the download site.
CODE="$(vm "curl -sS -o /dev/null -w '%{http_code}' --max-time 20 '$REPO'" || true)"
{ [ -n "$CODE" ] && [ "$CODE" != "000" ]; } || die "the VM cannot reach $REPO"
ok "$REPO answers HTTP $CODE"

if $CHECK_ONLY; then
    say "Preconditions pass. Nothing was changed."
    printf '\nRun the same command without --check to do the mirror.\n'
    exit 0
fi

# ---------------------------------------------------------------------------
# 4. The IBMid, once
# ---------------------------------------------------------------------------
say "4. Credentials"

# The master password file encrypts the credential store. It is a local file
# key, not something a human has to remember, so it is generated rather than
# asked for. Root-owned, because imcl reads it as root.
if vm "sudo test -s $MASTERPW"; then
    ok "credential store key already at $MASTERPW"
else
    vm "sudo install -d -m 0700 $(dirname "$MASTERPW") && openssl rand -base64 33 | sudo tee $MASTERPW >/dev/null && sudo chmod 600 $MASTERPW && sudo chown root:root $MASTERPW"
    ok "generated $MASTERPW"
fi

# A credential store written from a typo is the one failure with no way out:
# every later run would say "already there" and then fail to authenticate.
if $RESET_CREDS; then
    vm "sudo rm -f $SECSTORE"
    ok "removed any previous credential store (--reset-creds)"
fi

if vm "sudo test -s $SECSTORE"; then
    ok "credential store already at $SECSTORE - not touching it"
else
    # NOT `imcl -prompt`. The imcl launcher appends -silent, and -silent with
    # -prompt lands in a console dialog that answers a typed line with
    # `ERROR: Invalid entry "0"` and then sits there holding the Installation
    # Manager lock until it is killed. imutilsc saveCredential has no dialog:
    # it takes the credential, writes the store and exits.
    #
    # The password is typed here and never stored. It reaches the VM on stdin,
    # so it stays out of this host's process list and shell history. On the VM
    # it does appear in the imutilsc command line for the second that call
    # lasts - that is imutilsc's interface and no flag avoids it.
    printf '\n   The IBMid goes to IBM, not to this script: nothing here stores\n'
    printf '   or logs it. imutilsc writes it encrypted to the VM, once.\n\n'
    printf '   IBMid (e-mail) : '
    read -r IBMID
    [ -n "$IBMID" ] || die "no IBMid given"
    printf '   Password       : '
    read -rs IBMPW
    printf '\n\n'
    [ -n "$IBMPW" ] || die "no password given"

    # Both repositories need the credential: the offering comes from one and
    # Packaging Utility itself from the other.
    # saveCredential validates against IBM, and when it fails it STILL leaves a
    # store behind. Left in place, the next run would see a store, skip this
    # whole step and fail later on an authentication error with no way back -
    # so a failure here deletes what it wrote.
    for url in "$REPO" "$PUREPO"; do
        if ! printf '%s\n' "$IBMPW" | ssh "${SSH_OPTS[@]}" "$VM_USER@$IP" \
            "read -r PW && sudo $IMTOOLS/imutilsc saveCredential -url '$url' -userName '$IBMID' -userPassword \"\$PW\" -secureStorageFile $SECSTORE -masterPasswordFile $MASTERPW"
        then
            unset IBMPW
            vm "sudo rm -f $SECSTORE"
            die "the IBMid was refused for $url - nothing was kept, just run this again"
        fi
        ok "credential accepted for $url"
    done
    unset IBMPW

    vm "sudo test -s $SECSTORE" || die "no credential store was written to $SECSTORE"
    # imutilsc writes it 0644. The contents are encrypted with the master key,
    # but a credential store has no business being world-readable.
    vm "sudo chmod 600 $SECSTORE"
    ok "credential store at $SECSTORE"
fi

CRED="-secureStorageFile $SECSTORE -masterPasswordFile $MASTERPW"

# ---------------------------------------------------------------------------
# 5. What the repository actually offers
# ---------------------------------------------------------------------------
say "5. Offerings"

# Nothing is hardcoded here, for the reason the role gives: the editions differ
# only by their offering id, and a wrong guess produces an imcl error that
# reads like a licence problem.
AVAIL="$(vm "sudo $IMTOOLS/imcl listAvailablePackages -long -repositories '$REPO' $CRED")" \
    || die "could not read $REPO. If the IBMid or password was mistyped, redo them with --reset-creds"
ok "$(printf '%s\n' "$AVAIL" | grep -c . ) packages advertised"

# Two traps in this output, both of which cost a run to find.
#
#  1. -long prints "<repository> : <package> : <name> : <version>", so the
#     package id is NEVER at the start of a line. A filter anchored on ^com
#     matches nothing and the script then blames the entitlement.
#  2. The list is in ascending order, so the newest level is the LAST match,
#     not the first. head -1 quietly selects the oldest build on offer.
pick() {
    printf '%s\n' "$AVAIL" | grep -oE "${1//./\\.}_[^ ]+" | sort -u | sort -V | tail -1
}

WAS_OFF="$(pick "$WAS_OFFERING_ID" || true)"
SDK_OFF="$(pick "$SDK_OFFERING_ID" || true)"
[ -n "$WAS_OFF" ] || die "$REPO advertises no $WAS_OFFERING_ID - is this IBMid entitled to it?"
ok "WAS offering $WAS_OFF"
if [ -n "$SDK_OFF" ]; then
    ok "SDK offering $SDK_OFF"
else
    bad "no $SDK_OFFERING_ID advertised - was_fixpack refuses a WAS fix pack without a matching SDK one"
fi

# ---------------------------------------------------------------------------
# 6. Packaging Utility - the only thing that makes mirrors
# ---------------------------------------------------------------------------
say "6. Packaging Utility"

# Packaging Utility 1.10 puts its CLI at the root as PUCL (IBMPU is the GUI).
# Older levels shipped it as eclipse/tools/imutilsc, like Installation Manager,
# so both are accepted rather than assuming the layout.
pu_cli() {
    for cand in "$PU_DIR/PUCL" "$PU_DIR/eclipse/tools/imutilsc"; do
        if vm "test -x $cand"; then printf '%s' "$cand"; return 0; fi
    done
    return 1
}

if PUC="$(pu_cli)"; then
    ok "already installed, CLI at $PUC"
else
    vm "sudo $IMTOOLS/imcl install com.ibm.cic.packagingUtility -repositories '$PUREPO' -installationDirectory $PU_DIR -sharedResourcesDirectory $IMSHARED -dataLocation $IMDATA -log $IMLOGS/install_pu.log -acceptLicense $CRED" \
        || die "Packaging Utility did not install - see $IMLOGS/install_pu.log on the VM"
    PUC="$(pu_cli)" || die "Packaging Utility installed but no CLI found under $PU_DIR"
    ok "installed, CLI at $PUC"
fi

# ---------------------------------------------------------------------------
# 7. The mirror
# ---------------------------------------------------------------------------
say "7. Mirror into $TARGET"

vm "sudo install -d -m 0755 -o $VM_USER -g $VM_USER $TARGET"

# The SDK goes into the same mirror deliberately: was_install puts both in one
# imcl call, and a forgotten SDK costs a second multi-minute run.
# Two differences from imcl, both of which cost a run to find:
#
#  - PUCL copy takes ONE package per call. imcl install takes a list, and
#    handing PUCL a second id gets "Unrecognized command line argument".
#  - PUCL has no -showVerboseProgress, and an unknown option is a hard failure.
#
# Successive copies into the same -target merge into one repository, which is
# what was_install wants: a single repository.config at the root.
for offering in "$WAS_OFF" ${SDK_OFF:+$SDK_OFF}; do
    printf '   copying %s\n' "$offering"
    vm "sudo $PUC copy $offering -repositories '$REPO' -target $TARGET -acceptLicense $CRED" \
        || die "copying $offering failed - the repository under $TARGET is now partial; delete it before retrying"
    ok "copied $offering"
done

# ---------------------------------------------------------------------------
# 8. Is it a repository Installation Manager will read?
# ---------------------------------------------------------------------------
say "8. Verify"

vm "test -s $TARGET/repository.config" \
    || die "no repository.config at the root of $TARGET - was_install will refuse this"
ok "$TARGET/repository.config"

LOCAL="$(vm "sudo $IMTOOLS/imcl listAvailablePackages -long -repositories $TARGET")"
printf '%s\n' "$LOCAL" | sed 's/^/   /'
printf '%s\n' "$LOCAL" | grep -q "$WAS_OFFERING_ID" \
    || die "the local repository does not advertise $WAS_OFFERING_ID"
ok "the local repository serves the offering"

# The offering id carries 9.0.5028, which is level 9.0.5.28 - one digit of fix
# pack line and three of fix pack, with leading zeros dropped. Rather than
# reimplement that, take the last field of the -long line: IBM already renders
# the version there, correctly.
LEVEL="$(printf '%s\n' "$AVAIL" | grep -F "$WAS_OFF" | head -1 | awk -F' : ' '{print $NF}' | tr -d ' \r')"

say "Done"
cat <<DONE
   mirror   : $TARGET on $VM
   offering : $WAS_OFF
   level    : ${LEVEL:-unknown}

   The VM no longer needs the internet for the install. Next:

     ansible-playbook -i inventories/lab \\
       ansible_collections/wasevo/websphere/playbooks/lab_install_was.yml \\
       -e was_environment=<code>

   Check one thing first. inventories/lab/group_vars/was_lab.yml asserts
   was_expected_version, set to 9.0.0.0 - the level a Passport Advantage base
   image yields. This mirror came from the live ILAN repository, which serves
   the CURRENT level, so the install will land on ${LEVEL:-9.0.5.x} and that
   assert will fail. Set it to the level above.
DONE
