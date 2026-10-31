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

# A check run on a cell that has no such cluster. NOT a refusal: under --check
# the cluster is a future, created by the step before this one in the same run,
# and a dry run of a first build is the run most worth rehearsing.
payload member_future_check <<'JSON'
{"resource":"cluster_member","state":"present",
 "params":{"cluster_name":"ClusterNOTYET","cell_name":"Extranet_STUB",
           "members":[{"node":"STUBNode01","name":"ClusterNOTYET_STUBNode01_01"}]},
 "check_mode":true,"save_config":true,"sync_nodes":true}
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

# --------------------------------------------------------------------------
# J2C authentication aliases
# --------------------------------------------------------------------------
# The password used here is a marker, searched for in every driver answer
# below: it must never come back out. The real AdminConfig returns a stored
# password encoded, so a handler that read it back would work in this fake and
# leak or break on a real cell - the fake refuses to serve it at all.
payload j2c_create <<'JSON'
{"resource":"j2c_alias","state":"present",
 "params":{"password_policy":"on_create",
           "aliases":[{"name":"stubDbAlias","user":"app","password":"MARKER-pw-1","description":"stub db"}]},
 "check_mode":false,"save_config":true,"sync_nodes":true}
JSON

payload j2c_user_check <<'JSON'
{"resource":"j2c_alias","state":"present",
 "params":{"password_policy":"on_create",
           "aliases":[{"name":"stubDbAlias","user":"app2","password":"MARKER-pw-1","description":"stub db"}]},
 "check_mode":true,"save_config":true,"sync_nodes":true}
JSON

# A new password under on_create: nothing to compare, so nothing written.
payload j2c_new_pw_on_create <<'JSON'
{"resource":"j2c_alias","state":"present",
 "params":{"password_policy":"on_create",
           "aliases":[{"name":"stubDbAlias","user":"app","password":"MARKER-pw-2","description":"stub db"}]},
 "check_mode":false,"save_config":true,"sync_nodes":true}
JSON

# The same under always: the rotation.
payload j2c_rotate <<'JSON'
{"resource":"j2c_alias","state":"present",
 "params":{"password_policy":"always",
           "aliases":[{"name":"stubDbAlias","user":"app","password":"MARKER-pw-2","description":"stub db"}]},
 "check_mode":false,"save_config":true,"sync_nodes":true}
JSON

payload j2c_absent <<'JSON'
{"resource":"j2c_alias","state":"absent",
 "params":{"aliases":[{"name":"stubDbAlias","user":"app"}]},
 "check_mode":false,"save_config":true,"sync_nodes":true}
JSON

# Run one payload through the driver and print the resulting `changed`, or an
# error. Deliberately goes through the sentinel extraction the module uses, so
# a change to the framing breaks here too.
#
# The raw output of every run is appended to $WORK/<payload>.raw, so a check
# that inspects what the driver said - the password-leak guard - reads the
# answers of the runs that actually happened, all of them, instead of running
# the payload again, which would write twice and skew every count after it.
run_one() {
    "$PY" "$STUB/shim.py" "$DRIVER" "$WORK/$1.json" 2>&1 \
      | tee -a "$WORK/$1.raw" \
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
# The same request under --check is a plan, not a refusal: the cluster is a
# future, and a dry run of a first build has to be possible.
expect "--check on a cluster not created yet"   member_future_check true
expect_value "and it still created nothing" "$(cell_members)" "2"
expect_refusal "two JVMs on one node claiming one port" \
    member_port_clash "cannot share a port"

echo
echo "=== J2C authentication aliases ==="
# The stored password, and how many times it was written - read from the fake
# cell's state, which is the only place it exists.
j2c_pw() {
    "$PY" -c '
import json, os, sys
for o in json.load(open(os.environ["WAS_SIM_STATE"])).get("objects", {}).values():
    if o["type"] == "JAASAuthData" and o["attrs"]["alias"] == sys.argv[1]:
        print("%s/%s" % (o["attrs"]["_password"], o["attrs"]["_password_writes"]))
        sys.exit(0)
print("absent")
' "$1"
}

expect "create an alias"                        j2c_create           true
expect "replay (idempotency)"                   j2c_create           false
expect "--check a new user"                     j2c_user_check       true
expect_value "the check wrote nothing" "$(j2c_pw stubDbAlias)" "MARKER-pw-1/1"
expect "new password, on_create: left alone"    j2c_new_pw_on_create false
expect_value "and it was not written" "$(j2c_pw stubDbAlias)" "MARKER-pw-1/1"
expect "new password, always: rotated"          j2c_rotate           true
expect_value "and it was written once more" "$(j2c_pw stubDbAlias)" "MARKER-pw-2/2"

# The guard that matters most for this resource. Every answer the driver gave
# about an alias is searched for the password markers - including the rotation,
# where the new password was in the request and must not be in the answer.
leak=""
for pl in j2c_create j2c_user_check j2c_new_pw_on_create j2c_rotate; do
    if grep -q "MARKER-pw" "$WORK/$pl.raw"; then
        leak="$leak $pl"
    fi
done
expect_value "no password in any driver answer" "${leak:-none}" "none"

expect "delete"                                 j2c_absent           true
expect "replay delete"                          j2c_absent           false

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
# Nine effective changes above: the cluster created, its members created, a
# port pinned, a member drained, a member deleted, an alias created, its
# password rotated, the alias deleted, the cluster deleted. Every replay, every
# check run, the password left alone under on_create and the refusals must add
# none - a node synchronisation on a cell that did not change is a ripple
# through the estate for nothing.
if [ "$syncs" = "9" ]; then
    echo "  ok     9 syncs for 9 effective changes, none for the replays,"
    echo "         the check runs, the untouched password or the refusals"
else
    echo "  FAIL   expected 9 syncs, state reports $syncs"
    fail=1
fi

echo
if [ "$fail" -eq 0 ]; then
    echo "ALL CHECKS PASSED"
else
    echo "CHECKS FAILED"
fi
exit "$fail"
