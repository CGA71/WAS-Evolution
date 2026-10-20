#!/usr/bin/env bash
# Build the cloud-init Secret and bring up the lab VM.
#
# The SSH public key stays out of the repository: it is read from the key pair
# on the node and injected into a Secret at apply time.
#
#   bash ci/k3s/make-lab-vm.sh
#
# Teardown, which leaves nothing behind:
#   kubectl delete ns was-lab

set -euo pipefail

KEY="${WAS_LAB_KEY:-$HOME/.ssh/was_lab}"
NS=was-lab
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ ! -f "${KEY}.pub" ]; then
    echo "No public key at ${KEY}.pub."
    echo "Create one with: ssh-keygen -t ed25519 -N '' -C ansible@was-lab -f ${KEY}"
    exit 1
fi

kubectl create namespace "$NS" --dry-run=client -o yaml | kubectl apply -f - >/dev/null

USERDATA="$(mktemp)"
trap 'rm -f "$USERDATA"' EXIT

cat > "$USERDATA" <<EOF
#cloud-config
hostname: was-lab-01
fqdn: was-lab-01.was-lab.svc.cluster.local

users:
  - name: ansible
    groups: [wheel]
    shell: /bin/bash
    sudo: ["ALL=(ALL) NOPASSWD:ALL"]
    ssh_authorized_keys:
      - $(cat "${KEY}.pub")

# Password login stays off: the only way in is the key above.
ssh_pwauth: false
disable_root: true

packages:
  # python3 is what Ansible needs. The rest are Installation Manager's own
  # prerequisites, and psmisc is the one the legacy playbooks installed last
  # instead of first - manageprofiles needs killall.
  - python3
  # NOT python3-libdnf5: that is a dnf5 package and does not exist on Rocky 9.
  # One bad name fails the whole cloud-init package transaction, which is how
  # this VM came up with seven of eight packages and no unzip.
  - unzip
  - tar
  - gzip
  - gettext
  - psmisc
  - procps-ng
  - which

write_files:
  # Raise the limits WAS needs before anything is installed, rather than
  # discovering them when a profile fails to create.
  - path: /etc/security/limits.d/90-was.conf
    content: |
      *  soft  nofile  65536
      *  hard  nofile  65536
      *  soft  nproc   16384
      *  hard  nproc   16384

runcmd:
  # The directory layout the inventory declares. Created here so the install
  # roles find it rather than having to be root to make it.
  - [mkdir, -p, /app/binaries, /app/profiles, /app/logs, /app/data, /mnt/binaries, /opt/exploit]
  - [chown, -R, "ansible:ansible", /app, /mnt/binaries, /opt/exploit]
  - [bash, -c, "echo 'lab VM ready' > /var/log/was-lab-ready"]

final_message: "was-lab-01 up after \$UPTIME seconds"
EOF

kubectl -n "$NS" create secret generic was-lab-cloudinit \
    --from-file=userdata="$USERDATA" \
    --dry-run=client -o yaml | kubectl apply -f - >/dev/null
echo "cloud-init secret in place"

kubectl apply -f "$HERE/20-was-lab-vm.yml"

echo
echo "waiting for the disk image import (about 620 MB)..."
kubectl -n "$NS" wait --for=condition=Ready dv/was-lab-disk --timeout=900s || {
    echo "import did not finish; current state:"
    kubectl -n "$NS" get dv was-lab-disk -o jsonpath='{.status.phase} {.status.progress}{"\n"}'
    exit 1
}

echo "waiting for the VM to report an address..."
for _ in $(seq 1 60); do
    IP="$(kubectl -n "$NS" get vmi was-lab-01 -o jsonpath='{.status.interfaces[0].ipAddress}' 2>/dev/null || true)"
    [ -n "$IP" ] && break
    sleep 5
done

echo
kubectl -n "$NS" get dv,vmi,svc
echo
echo "pod IP   : ${IP:-not yet}"
echo "in-cluster name: was-lab-01.${NS}.svc.cluster.local"
echo
echo "Reach it from the node with:"
echo "  ssh -i $KEY ansible@\$(kubectl -n $NS get vmi was-lab-01 -o jsonpath='{.status.interfaces[0].ipAddress}')"
