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
 "params":{"name":"ClusterEXT","cell_name":"Extranet_RIT","prefer_local":"true"},
 "check_mode":false,"save_config":true,"sync_nodes":true}
JSON

payload drift_check <<'JSON'
{"resource":"cluster","state":"present",
 "params":{"name":"ClusterEXT","cell_name":"Extranet_RIT","prefer_local":"false"},
 "check_mode":true,"save_config":true,"sync_nodes":true}
JSON

payload absent <<'JSON'
{"resource":"cluster","state":"absent",
 "params":{"name":"ClusterEXT","cell_name":"Extranet_RIT"},
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

echo "=== module -> driver -> handler -> fake cell ==="
expect "create"                             present     true
expect "replay (idempotency)"               present     false
expect "--check on a real gap"              drift_check true
expect "replay after --check (nothing written)" present false
expect "delete"                             absent      true
expect "replay delete"                      absent      false

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
if [ "$syncs" = "2" ]; then
    echo "  ok     2 syncs for 2 effective changes, none for the no-ops"
else
    echo "  FAIL   expected 2 syncs, state reports $syncs"
    fail=1
fi

echo
if [ "$fail" -eq 0 ]; then
    echo "ALL CHECKS PASSED"
else
    echo "CHECKS FAILED"
fi
exit "$fail"
