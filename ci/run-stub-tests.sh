#!/usr/bin/env bash
# Exercise the traditional-plane chain with no cluster and no Ansible.
#
# This runs the real driver.py and the real cluster handler against the fake
# cell. It is the cheapest gate in the pipeline and it catches most regressions
# before anything is deployed: dispatch, payload parsing, the read/plan/write
# split, JSON encoding, sentinel framing, and whether changed is honest.
#
# What it does NOT prove: that the wsadmin calls in the handlers are correct
# WAS API usage. Only a real cell proves that.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COLLECTION="$ROOT/ansible_collections/wasevo/websphere"
STUB="$COLLECTION/roles/traditional/config/files/wsadmin-stub"
DRIVER="$COLLECTION/plugins/jython/driver.py"
HANDLERS="$COLLECTION/plugins/jython/handlers"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

export WAS_SIM_STATE="$WORK/state.json"
export PYTHONPATH="$STUB:$HANDLERS"

PY="${PYTHON:-python3}"
fail=0

payload() {
    cat > "$WORK/$1.json"
}

payload present <<'JSON'
{"resource":"cluster","state":"present",
 "params":{"name":"ClusterEXT","cell_name":"Extranet_STUB","prefer_local":"true"},
 "check_mode":false,"save_config":true,"sync_nodes":true}
JSON

payload drift_check <<'JSON'
{"resource":"cluster","state":"present",
 "params":{"name":"ClusterEXT","cell_name":"Extranet_STUB","prefer_local":"false"},
 "check_mode":true,"save_config":true,"sync_nodes":true}
JSON

payload absent <<'JSON'
{"resource":"cluster","state":"absent",
 "params":{"name":"ClusterEXT","cell_name":"Extranet_STUB"},
 "check_mode":false,"save_config":true,"sync_nodes":true}
JSON

# --------------------------------------------------------------------------
# Cluster members: the application servers
# --------------------------------------------------------------------------
# One call carries the whole member list, because a wsadmin JVM start costs 30
# to 60 seconds. This payload is a VERTICAL and HORIZONTAL cluster at once -
# two members on STUBNode01, one on STUBNode02 - which is the shape an estate
# actually has, and the shape that catches the -firstMember rule: the fake cell
# refuses the call if the handler sends -firstMember for anything but the first
# member of the cluster.
payload members <<'JSON'
{"resource":"cluster_member","state":"present",
 "params":{"cluster_name":"ClusterEXT","cell_name":"Extranet_STUB",
           "template_name":"default",
           "members":[{"node":"STUBNode01","name":"ClusterEXT_STUBNode01_01","weight":2,"gen_unique_ports":true},
                      {"node":"STUBNode01","name":"ClusterEXT_STUBNode01_02","weight":2,"gen_unique_ports":true},
                      {"node":"STUBNode02","name":"ClusterEXT_STUBNode02_01","weight":2,"gen_unique_ports":true}]},
 "check_mode":false,"save_config":true,"sync_nodes":true}
JSON

# A pinned port. Only the endpoints named here are read back, so this also
# exercises the serverindex read path that a member with no pinned port skips.
payload member_pin <<'JSON'
{"resource":"cluster_member","state":"present",
 "params":{"cluster_name":"ClusterEXT","cell_name":"Extranet_STUB",
           "members":[{"node":"STUBNode01","name":"ClusterEXT_STUBNode01_02",
                       "ports":{"WC_defaulthost":9382}}]},
 "check_mode":false,"save_config":true,"sync_nodes":true}
JSON

# Weight 0 drains a member without deleting it.
payload member_drain <<'JSON'
{"resource":"cluster_member","state":"present",
 "params":{"cluster_name":"ClusterEXT","cell_name":"Extranet_STUB",
           "members":[{"node":"STUBNode02","name":"ClusterEXT_STUBNode02_01","weight":0}]},
 "check_mode":false,"save_config":true,"sync_nodes":true}
JSON

payload member_new_check <<'JSON'
{"resource":"cluster_member","state":"present",
 "params":{"cluster_name":"ClusterEXT","cell_name":"Extranet_STUB",
           "members":[{"node":"STUBNode03","name":"ClusterEXT_STUBNode03_01"}]},
 "check_mode":true,"save_config":true,"sync_nodes":true}
JSON

payload member_absent <<'JSON'
{"resource":"cluster_member","state":"absent",
 "params":{"cluster_name":"ClusterEXT","cell_name":"Extranet_STUB",
           "members":[{"node":"STUBNode02","name":"ClusterEXT_STUBNode02_01"}]},
 "check_mode":false,"save_config":true,"sync_nodes":true}
JSON

# Members asked for in a cell that has no such cluster. A refusal, not a crash:
# the handler raises ValueError, the driver reports the sentence alone.
payload member_no_cluster <<'JSON'
{"resource":"cluster_member","state":"present",
 "params":{"cluster_name":"ClusterNOPE","cell_name":"Extranet_STUB",
           "members":[{"node":"STUBNode01","name":"whatever"}]},
 "check_mode":false,"save_config":true,"sync_nodes":true}
JSON

# Two members on ONE node with genUniquePorts off. They both copy the
# template's ports, which is a collision - and the reason the module defaults
# it to true. WAS saves this configuration happily and the second server fails
# to start hours later; the fake cell refuses it at creation.
payload member_port_clash <<'JSON'
{"resource":"cluster_member","state":"present",
 "params":{"cluster_name":"ClusterEXT","cell_name":"Extranet_STUB",
           "members":[{"node":"STUBNode09","name":"Clash01","gen_unique_ports":false},
                      {"node":"STUBNode09","name":"Clash02","gen_unique_ports":false}]},
 "check_mode":false,"save_config":true,"sync_nodes":true}
JSON

# Run one payload through the driver and print the resulting `changed`, or an
# error. Deliberately goes through the sentinel extraction the module uses, so
# a change to the framing breaks here too.
run_one() {
    "$PY" "$STUB/shim.py" "$DRIVER" "$WORK/$1.json" 2>&1 \
      | sed -n '/<<<VSSP-JSON>>>/,/<<<END-VSSP-JSON>>>/p' \
      | sed '1d;$d' \
      | "$PY" -c '
import json, sys
answer = json.load(sys.stdin)
if answer.get("failed"):
    print("ERROR " + (answer.get("msg") or "")[:400])
else:
    print(str(answer.get("changed")).lower())
'
}

expect() {
    local label="$1" pl="$2" want="$3"
    local got
    got="$(run_one "$pl")"
    if [ "$got" = "$want" ]; then
        printf '  ok     %-48s changed=%s\n' "$label" "$got"
    else
        printf '  FAIL   %-48s expected %s, got: %s\n' "$label" "$want" "$got"
        fail=1
    fi
}

# The whole message, for the checks that are about what a refusal SAYS.
# A refusal an operator cannot act on is a crash with better manners.
msg_of() {
    "$PY" "$STUB/shim.py" "$DRIVER" "$WORK/$1.json" 2>&1 \
      | sed -n '/<<<VSSP-JSON>>>/,/<<<END-VSSP-JSON>>>/p' \
      | sed '1d;$d' \
      | "$PY" -c '
import json, sys
print((json.load(sys.stdin).get("msg") or "").replace("\n", " "))
'
}

expect_refusal() {
    local label="$1" pl="$2" needle="$3"
    local got
    got="$(msg_of "$pl")"
    case "$got" in
        *"$needle"*)
            printf '  ok     %-48s refused, and says why\n' "$label" ;;
        *)
            printf '  FAIL   %-48s expected a refusal naming "%s", got: %s\n' \
                "$label" "$needle" "${got:-<no message>}"
            fail=1 ;;
    esac
}

# How many members the fake cell holds, and the port of one of them. Asserted
# rather than described: "check mode writes nothing" is only worth claiming if
# something looks.
cell_members() {
    "$PY" -c '
import json, os
state = json.load(open(os.environ["WAS_SIM_STATE"]))
print(len(state.get("members", {})))
'
}

member_port() {
    "$PY" -c '
import json, os, sys
state = json.load(open(os.environ["WAS_SIM_STATE"]))
server, endpoint = sys.argv[1], sys.argv[2]
for entry in state.get("entries", {}).values():
    if entry["serverName"] != server:
        continue
    for special_id in entry["special_ids"]:
        special = state["specials"][special_id]
        if special["endPointName"] == endpoint:
            print(state["ports"][special["endPoint"]]["port"])
            sys.exit(0)
print("absent")
' "$1" "$2"
}

expect_value() {
    local label="$1" got="$2" want="$3"
    if [ "$got" = "$want" ]; then
        printf '  ok     %-48s %s\n' "$label" "$got"
    else
        printf '  FAIL   %-48s expected %s, got %s\n' "$label" "$want" "$got"
        fail=1
    fi
}

echo "=== module -> driver -> handler -> fake cell ==="
expect "create"                             present     true
expect "replay (idempotency)"               present     false
expect "--check on a real gap"              drift_check true
expect "replay after --check (nothing written)" present false

echo
echo "=== cluster members: the application servers ==="
# Vertical and horizontal in one call: 2 JVMs on STUBNode01, 1 on STUBNode02.
expect "create 3 members in one wsadmin call"  members          true
expect "replay (idempotency)"                  members          false
expect_value "members in the cell" "$(cell_members)" "3"
expect_value "vertical members got distinct ports" \
    "$([ "$(member_port ClusterEXT_STUBNode01_01 WC_defaulthost)" \
       != "$(member_port ClusterEXT_STUBNode01_02 WC_defaulthost)" ] && echo distinct)" \
    "distinct"

expect "pin an endpoint port"                  member_pin       true
expect_value "the pinned port was applied" \
    "$(member_port ClusterEXT_STUBNode01_02 WC_defaulthost)" "9382"
# The regression this guards: planning a port change used to mutate the state
# it was comparing against - a shallow dict copy - so the write was skipped and
# the diff claimed a change that never happened. Convergence is the proof.
expect "replay the pinned port (convergence)"  member_pin       false

expect "drain a member with weight 0"          member_drain     true
expect "replay the drain"                      member_drain     false

expect "--check a new member"                  member_new_check true
expect_value "check mode created nothing" "$(cell_members)" "3"

expect "delete one member"                     member_absent    true
expect "replay the delete"                     member_absent    false
expect_value "members left in the cell" "$(cell_members)" "2"

expect_refusal "members in a cluster that does not exist" \
    member_no_cluster "does not exist in this cell"
expect_refusal "two JVMs on one node claiming one port" \
    member_port_clash "cannot share a port"

echo
echo "=== the cluster, deleted with its members ==="
expect "delete"                             absent      true
expect "replay delete"                      absent      false
expect_value "deleting the cluster took its members" "$(cell_members)" "0"

echo
echo "=== guard: credentials on the command line must be refused ==="
# This is the regression that matters most. Anything on a wsadmin command line
# is visible in ps and lands in the Ansible log.
set +e
sh "$STUB/wsadmin.sh" -lang jython -username wsadmin -password secret \
   -f "$DRIVER" "$WORK/present.json" >"$WORK/guard.out" 2>&1
rc=$?
set -e
if [ "$rc" -eq 93 ]; then
    echo "  ok     refused with exit 93"
else
    echo "  FAIL   expected exit 93, got $rc"
    sed 's/^/         /' "$WORK/guard.out" | head -4
    fail=1
fi

echo
echo "=== guard: the properties file must be 0600 ==="
install -m 0644 /dev/null "$WORK/loose.props"
set +e
sh "$STUB/wsadmin.sh" -lang jython -wsadmin_properties "$WORK/loose.props" \
   -f "$DRIVER" "$WORK/present.json" >"$WORK/mode.out" 2>&1
rc=$?
set -e
if [ "$rc" -eq 98 ]; then
    echo "  ok     refused with exit 98"
else
    echo "  FAIL   expected exit 98, got $rc"
    sed 's/^/         /' "$WORK/mode.out" | head -4
    fail=1
fi

echo
echo "=== sync only on real change ==="
# "No change, no ripple" is the property a truthful `changed` buys. The fake
# cell counts syncs, so it can be asserted rather than described.
syncs="$("$PY" -c '
import json, os
print(json.load(open(os.environ["WAS_SIM_STATE"])).get("syncs", 0))
')"
# Six effective changes above: the cluster created, its members created, a
# port pinned, a member drained, a member deleted, the cluster deleted. Every
# replay, every check run and the two refusals must add none - a node
# synchronisation on a cell that did not change is a ripple through the estate
# for nothing.
if [ "$syncs" = "6" ]; then
    echo "  ok     6 syncs for 6 effective changes, none for the replays,"
    echo "         the check runs or the refusals"
else
    echo "  FAIL   expected 6 syncs, state reports $syncs"
    fail=1
fi

echo
if [ "$fail" -eq 0 ]; then
    echo "ALL CHECKS PASSED"
else
    echo "CHECKS FAILED"
fi
exit "$fail"
