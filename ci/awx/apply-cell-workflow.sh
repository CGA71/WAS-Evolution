#!/usr/bin/env bash
# Declare, in AWX, the workflow that builds a WAS cell on the AIX server from
# nothing: the binaries mount checked, Installation Manager and WAS installed
# from it, the fix packs, a deployment manager and a federated node on the
# same machine, the cluster, its members, all started.
#
#   AWX_API=https://<awx>/api/v2 bash ci/awx/apply-cell-workflow.sh          apply
#   AWX_API=https://<awx>/api/v2 bash ci/awx/apply-cell-workflow.sh --show   the graph
#
# AWX is hosted elsewhere; run this from any host that reaches it. The
# password is typed at the prompt. It is re-runnable: every object is found by
# name and patched. The configuration templates (J2C, JDBC, JMS, security...)
# are appended to the same workflow by apply-templates.sh.
#
# NOTHING SECRET. This script declares the inventory, the templates and the
# workflow - configuration only. Made by hand, in AWX, once:
#
#   Machine credential   "ServeurAIX (ansible)": the SSH key of the WAS account
#                        on ServeurAIX (site_was_user in inventories/aix).
#   WAS credential       of the type apply-templates.sh creates, "WAS
#                        administrative user": the console user and password.
#                        Attached here when it exists; until then the
#                        templates that need it ask for it at launch.
#   Inventory            "WAS AIX", sourced from inventories/aix/hosts.yml by
#                        this script.
#   Survey               environment, channel, topology, names, by
#                        apply-survey.sh, which this script runs at the end.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
API="${AWX_API:-https://awx.example.internal/api/v2}"
AWX_USER="${AWX_USER:-admin}"
WORKFLOW="${AWX_CELL_WORKFLOW:-WAS AIX - cell on ServeurAIX}"
PROJECT="${AWX_PROJECT:-WAS Evolution}"
INVENTORY="${AWX_CELL_INVENTORY:-WAS AIX}"
INVENTORY_FILE="inventories/aix/hosts.yml"
MACHINE_CRED="${AWX_MACHINE_CRED:-ServeurAIX (ansible)}"
WAS_CRED_TYPE="${AWX_WAS_CRED_TYPE:-WAS administrative user}"
COL=ansible_collections/wasevo/websphere/playbooks

say() { printf '\n== %s\n' "$*"; }
ok()  { printf '   ok    %s\n' "$*"; }
note(){ printf '   --    %s\n' "$*"; }
die() { printf '   FAIL  %s\n' "$*" >&2; exit 1; }

# Same credential handling as apply-survey.sh: the netrc and the request body
# live in a private temporary directory made by Python, removed on exit.
WORKDIR="$(python3 -c 'import tempfile; print(tempfile.mkdtemp(prefix="awx-"))')"
[ -d "$WORKDIR" ] || die "could not create the temporary directory"
trap 'rm -rf "$WORKDIR"' EXIT
NETRC="$WORKDIR/netrc"
BODY="$WORKDIR/body"

# AUTHENTICATION, in this order:
#   AWX_TOKEN_FILE   a file holding an AWX personal access token (OAuth2,
#                    User > Tokens in AWX). Preferred: revocable, scoped, no
#                    password typed. Sent as "Authorization: Bearer", from a
#                    0600 header file, so the token never reaches a command line.
#   AWX_NETRC_FILE   a netrc already written by a calling script
#                    (apply-cell-workflow.sh runs apply-survey.sh), reused so
#                    the password is typed once per run.
#   otherwise        AWX_USER's password, typed at the prompt.
if [ -n "${AWX_TOKEN_FILE:-}" ]; then
    [ -r "$AWX_TOKEN_FILE" ] || die "cannot read AWX_TOKEN_FILE ($AWX_TOKEN_FILE)"
    ( umask 077
      printf 'Authorization: Bearer %s\n' "$(tr -d ' \r\n' < "$AWX_TOKEN_FILE")" > "$WORKDIR/auth.header" )
    AUTH=(-H "@$WORKDIR/auth.header")
elif [ -n "${AWX_NETRC_FILE:-}" ] && [ -s "$AWX_NETRC_FILE" ]; then
    NETRC="$AWX_NETRC_FILE"
    AUTH=(--netrc-file "$NETRC")
else
    IFS= read -rsp "AWX password for $AWX_USER: " _awx_pw </dev/tty \
        || die "could not read the AWX password from the terminal"
    printf '\n' >&2
    [ -n "$_awx_pw" ] || die "empty AWX password"
    # The host part of AWX_API, by parameter expansion: AIX sed has no -E.
    _host="${API#*://}"; _host="${_host%%/*}"
    ( umask 077
      printf 'machine %s login %s password %s\n' \
          "$_host" "$AWX_USER" "$_awx_pw" > "$NETRC" )
    unset _awx_pw
    AUTH=(--netrc-file "$NETRC")
fi

# --noproxy "*": AWX is reached directly, never through the HTTP proxy the
# environment may declare (http_proxy, https_proxy). Through that proxy the API
# answers 504 Gateway Timeout.
#
# TLS: AWX's certificate is usually signed by an internal authority. With
# AWX_CA_FILE pointing at that authority's certificate it is verified;
# without it, -k accepts it unverified.
if [ -n "${AWX_CA_FILE:-}" ]; then CURL_TLS=(--cacert "$AWX_CA_FILE"); else CURL_TLS=(-k); fi
api() {
    local method="$1" path="$2"
    shift 2
    curl -sS "${CURL_TLS[@]}" --noproxy '*' "${AUTH[@]}" -X "$method" \
        -H "Content-Type: application/json" "$API$path" "$@"
}
py() { python3 -c "$1" "${@:2}"; }
id_of() {
    api GET "/$1/?name=$(py 'import sys,urllib.parse;print(urllib.parse.quote(sys.argv[1]))' "$2")" \
      | py 'import sys,json
for r in json.load(sys.stdin).get("results", []):
    if r["name"] == sys.argv[1]:
        print(r["id"]); break' "$2"
}
# Create or patch an object by name; the body is read from $BODY so a secret
# in it never reaches a command line.
upsert() {
    local kind="$1" name="$2" id
    id="$(id_of "$kind" "$name")"
    if [ -n "$id" ]; then
        api PATCH "/$kind/$id/" --data-binary "@$BODY" >/dev/null || die "could not update $name"
        ok "updated  $name (id $id)" >&2
    else
        id="$(api POST "/$kind/" --data-binary "@$BODY" | py 'import sys,json
d = json.load(sys.stdin)
if "id" not in d:
    raise SystemExit("refused: " + json.dumps(d)[:400])
print(d["id"])')" || die "could not create $name"
        ok "created  $name (id $id)" >&2
    fi
    printf '%s' "$id"
}

if [ "${1:-}" = "--show" ]; then
    WF_ID="$(id_of workflow_job_templates "$WORKFLOW")"
    [ -n "$WF_ID" ] || die "no workflow named \"$WORKFLOW\" yet"
    api GET "/workflow_job_templates/$WF_ID/workflow_nodes/?page_size=200" | py 'import sys,json
for n in json.load(sys.stdin)["results"]:
    u = n.get("summary_fields", {}).get("unified_job_template") or {}
    print("   node %-5s %-50s success -> %s" % (n["id"], u.get("name"), n.get("success_nodes")))'
    exit 0
fi

# ---------------------------------------------------------------------------
say "AWX objects"
# ---------------------------------------------------------------------------
api GET /ping/ >/dev/null || die "cannot reach $API"
ORG_ID="$(api GET "/organizations/" | py 'import sys,json;print(json.load(sys.stdin)["results"][0]["id"])')"
PROJECT_ID="$(id_of projects "$PROJECT")"
[ -n "$PROJECT_ID" ] || die "no project named \"$PROJECT\""
MACHINE_CRED_ID="$(id_of credentials "$MACHINE_CRED")"
[ -n "$MACHINE_CRED_ID" ] || die "no credential named \"$MACHINE_CRED\""
# The WAS administrative credential, when its type and one credential of it
# exist. Neither is made here: the type by apply-templates.sh, the credential
# by a human, because it holds a password.
CT_ID="$(id_of credential_types "$WAS_CRED_TYPE")"
WAS_CRED_ID=""
if [ -n "$CT_ID" ]; then
    WAS_CRED_ID="$(api GET "/credentials/?credential_type=$CT_ID" | py 'import sys,json
d=json.load(sys.stdin)
print(d["results"][0]["id"] if d.get("count") else "")')"
fi
[ -n "$WAS_CRED_ID" ] || note "no \"$WAS_CRED_TYPE\" credential yet - the profile, cluster and start jobs will ask for one at launch"
EE_ID="$(api GET "/job_templates/?page_size=200" | py 'import sys,json
for t in json.load(sys.stdin)["results"]:
    if t.get("execution_environment"):
        print(t["execution_environment"]); break')"
[ -n "$EE_ID" ] || die "could not work out which Execution Environment to use"

# The project first: a template naming a playbook pushed after the project's
# last update is refused as "Playbook not found".
UPDATE_ID="$(api POST "/projects/$PROJECT_ID/update/" | py 'import sys,json;print(json.load(sys.stdin).get("id",""))')"
for _ in $(seq 1 60); do
    st="$(api GET "/project_updates/$UPDATE_ID/" | py 'import sys,json;print(json.load(sys.stdin).get("status",""))')"
    case "$st" in successful) break ;; failed|error|canceled) die "project update $st" ;; *) sleep 2 ;; esac
done
ok "project updated"

py 'import json,sys
print(json.dumps({"name": sys.argv[1], "organization": int(sys.argv[2]),
  "description": "ServeurAIX: a deployment manager and a federated node on one AIX server - inventories/aix"}))' \
  "$INVENTORY" "$ORG_ID" > "$BODY"
INV_ID="$(upsert inventories "$INVENTORY")"

py 'import json,sys
print(json.dumps({"name": sys.argv[1] + " from project", "inventory": int(sys.argv[2]),
  "source": "scm", "source_project": int(sys.argv[3]), "source_path": sys.argv[4],
  "overwrite": True, "update_on_launch": True, "execution_environment": int(sys.argv[5])}))' \
  "$INVENTORY" "$INV_ID" "$PROJECT_ID" "$INVENTORY_FILE" "$EE_ID" > "$BODY"
SRC_ID="$(upsert inventory_sources "$INVENTORY from project")"

# ---------------------------------------------------------------------------
say "Job templates"
# ---------------------------------------------------------------------------
# name | playbook | needs the WAS credential | extra vars
#
# Every job runs on ServeurAIX with the machine credential, become on: the
# roles ask for root (sudo, from the AIX Toolbox) only on the tasks that need
# it. lab_hosts and profile_hosts point the install and profile playbooks at
# the installation entry; config_dmgr_hosts lets the plays that act on the
# deployment manager run on an inventory with no environment group, which this
# one deliberately is - the same server is built as any environment.
#
# The fix pack playbook appears twice, as two templates: the first pass lifts
# Installation Manager to the level WAS needs, the second patches what the WAS
# and IHS jobs installed (WAS, the SDK, IHS, the plugin). A workflow node is
# found by its template here, so one template cannot be two nodes. Names are
# the key too: renaming a step leaves the old node in the workflow.
STEPS=(
  "WAS AIX - 0a. Binaries share: mount|$COL/binaries_mount.yml||mount_hosts: was_install"
  "WAS AIX - 0. Binaries mount point|$COL/binaries_mount_check.yml||mount_check_hosts: was_install"
  "WAS AIX - 1. Installation Manager|$COL/lab_install_im.yml||lab_hosts: was_install"
  "WAS AIX - 2. Fix packs: Installation Manager|$COL/lab_apply_fixpacks.yml||lab_hosts: was_install"
  "WAS AIX - 3. WAS|$COL/lab_install_was.yml||lab_hosts: was_install"
  "WAS AIX - 3b. IHS|$COL/lab_install_ihs.yml||lab_hosts: was_install"
  "WAS AIX - 3c. Web server plugin|$COL/lab_install_plugin.yml||lab_hosts: was_install"
  "WAS AIX - 4. Fix packs: WAS|$COL/lab_apply_fixpacks.yml||lab_hosts: was_install"
  "WAS AIX - 5. Profiles: deployment manager, federated node|$COL/lab_create_profiles.yml|was|profile_hosts: was_install"
  "WAS AIX - 6. Cluster|$COL/traditional_cluster.yml|was|config_dmgr_hosts: dmgr"
  "WAS AIX - 7. Cluster members|$COL/traditional_cluster_members.yml|was|config_dmgr_hosts: dmgr"
  "WAS AIX - 8. Start|$COL/traditional_start.yml|was|config_dmgr_hosts: dmgr"
)

JT_IDS=()
for step in "${STEPS[@]}"; do
    IFS='|' read -r name playbook needs_was extra <<<"$step"
    py 'import json,sys
name, playbook, ask_cred, extra, inv, proj, ee = sys.argv[1:8]
b = {"name": name, "job_type": "run", "inventory": int(inv), "project": int(proj),
     "playbook": playbook, "execution_environment": int(ee),
     "become_enabled": True, "verbosity": 1, "timeout": 5400,
     "ask_job_type_on_launch": True, "ask_variables_on_launch": True,
     "ask_credential_on_launch": ask_cred == "true"}
b["extra_vars"] = ("---\n%s\n" % extra.strip()) if extra.strip() else ""
print(json.dumps(b))' "$name" "$playbook" \
        "$([ "$needs_was" = "was" ] && [ -z "$WAS_CRED_ID" ] && echo true || echo false)" \
        "$extra" "$INV_ID" "$PROJECT_ID" "$EE_ID" > "$BODY"
    jt="$(upsert job_templates "$name")"
    api POST "/job_templates/$jt/credentials/" -d "{\"id\": $MACHINE_CRED_ID}" >/dev/null || true
    if [ "$needs_was" = "was" ] && [ -n "$WAS_CRED_ID" ]; then
        api POST "/job_templates/$jt/credentials/" -d "{\"id\": $WAS_CRED_ID}" >/dev/null || true
    fi
    JT_IDS+=("$jt")
done

# ---------------------------------------------------------------------------
say "Workflow"
# ---------------------------------------------------------------------------
py 'import json,sys
print(json.dumps({"name": sys.argv[1], "organization": int(sys.argv[2]), "inventory": int(sys.argv[3]),
  "description": "ServeurAIX: binaries mount checked, Installation Manager, WAS and fix packs from it, "
                 "a deployment manager and a federated node, the cluster and its members, started.",
  "ask_variables_on_launch": True}))' "$WORKFLOW" "$ORG_ID" "$INV_ID" > "$BODY"
WF_ID="$(upsert workflow_job_templates "$WORKFLOW")"

prev=""
for jt in "${JT_IDS[@]}"; do
    node="$(api GET "/workflow_job_templates/$WF_ID/workflow_nodes/?page_size=200" | py 'import sys,json
for n in json.load(sys.stdin)["results"]:
    if str((n.get("summary_fields", {}).get("unified_job_template") or {}).get("id")) == sys.argv[1]:
        print(n["id"]); break' "$jt")"
    if [ -z "$node" ]; then
        node="$(api POST "/workflow_job_templates/$WF_ID/workflow_nodes/" -d "{\"unified_job_template\": $jt}" \
                | py 'import sys,json;print(json.load(sys.stdin).get("id",""))')"
        [ -n "$node" ] || die "could not add template $jt to the workflow"
        ok "node $node for template $jt"
    else
        ok "template $jt is node $node"
    fi
    if [ -n "$prev" ]; then
        # The chain is exactly STEPS, in order: an edge left over from an
        # earlier version of this list (3 -> 4 before 3b was inserted) is
        # removed, or a node would be reached twice.
        for stale in $(api GET "/workflow_job_template_nodes/$prev/success_nodes/" | py 'import sys,json
for n in json.load(sys.stdin).get("results", []):
    if str(n["id"]) != sys.argv[1]:
        print(n["id"])' "$node"); do
            api POST "/workflow_job_template_nodes/$prev/success_nodes/" \
                -d "{\"id\": $stale, \"disassociate\": true}" >/dev/null || true
            ok "edge $prev -> $stale removed"
        done
        api POST "/workflow_job_template_nodes/$prev/success_nodes/" -d "{\"id\": $node}" >/dev/null || true
    fi
    prev="$node"
done

say "Survey"
AWX_NETRC_FILE="$NETRC" AWX_WORKFLOW="$WORKFLOW" bash "$HERE/apply-survey.sh" | tail -4

say "Done"
printf '   Launch it in AWX:\n     %s\n' \
    "$(printf '%s' "$API" | sed 's#/api/v2##')/#/templates/workflow_job_template/$WF_ID/details"
