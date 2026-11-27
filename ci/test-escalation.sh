#!/bin/sh
# Every playbook reaches the WAS account the same way, WHATEVER THE INVENTORY.
#
# The escalation is the collection's (playbooks/group_vars/all.yml). It used
# to live only in the AIX inventory's was_servers group, and a host outside it
# fell back to Ansible's default - sudo to root - which is how the JVM stop job
# failed on another server. ansible-inventory --playbook-dir reads the
# playbook-adjacent group_vars exactly as ansible-playbook does, so this
# resolves what a job would use for each kind of host, contacting nothing.
#
#   sh ci/test-escalation.sh        (from the repository root)

set -eu
PB_DIR="ansible_collections/wasevo/websphere/playbooks"
fail=0

# check <inventory> <host> <variable> <expected>
check() {
    got="$(ansible-inventory -i "$1" --playbook-dir "$PB_DIR" --host "$2" \
        | python3 -c 'import json,sys; print(json.load(sys.stdin).get(sys.argv[1], "<unset>"))' "$3")"
    if [ "$got" = "$4" ]; then
        echo "ok    $1 $2 $3 = $got"
    else
        echo "FAIL  $1 $2 $3 = $got (expected $4)"
        fail=1
    fi
}

# The AIX inventory: a WAS server, by each of its roles.
for host in ServeurAIX ServeurAIX-dmgr ServeurAIX-node; do
    check inventories/aix "$host" ansible_become_method su
    check inventories/aix "$host" ansible_become_exe "sudo su -"
    check inventories/aix "$host" ansible_remote_tmp /tmp
    check inventories/aix "$host" ansible_shell_allow_world_readable_temp True
done
# The site's own, kept in was_servers.yml.
check inventories/aix ServeurAIX-node ihs_control_become_as root

# The AWX web front keeps plain sudo to root.
check inventories/aix awx-web ansible_become_method sudo
check inventories/aix awx-web ansible_become_user root
check inventories/aix awx-web ansible_remote_tmp "~/.ansible/tmp"

# Another inventory, with no was_servers group at all: the same escalation.
for host in dmgr-01 app-01; do
    check inventories/was "$host" ansible_become_method su
    check inventories/was "$host" ansible_become_exe "sudo su -"
    check inventories/was "$host" ansible_remote_tmp /tmp
done

exit "$fail"
