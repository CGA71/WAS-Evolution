#!/usr/bin/env bash
# Assert the DMGR / node-agent network boundary by sending traffic across it.
#
# WHY TRAFFIC AND NOT THE POLICY OBJECTS. The job used to `kubectl get` the two
# NetworkPolicies and call the boundary proven. That proved a YAML object
# existed, not that anything was blocked: a cluster whose policy controller is
# off holds the same objects and enforces nothing. It also needed a read right
# on networkpolicies that an administrator had to grant by hand, so the test
# could not run on a cluster built from the repository alone.
#
# Here every claim the policies make is checked by a connection:
#
#   node agent -> dmgr, allowed port   must CONNECT     (the allow rule works)
#   node agent -> dmgr, any other port must NOT connect (the dmgr is isolated)
#   dmgr -> node agent                 must NOT connect (deny-ingress-by-default)
#   node agent -> other node agent     must NOT connect (podSelector {} covers
#                                                        its own namespace too)
#
# It needs only pods/exec and get pods, which the simulation identity already
# holds. Nothing to grant, nothing to apply by hand.
#
# A listener is started on the target first, so "connected" and "not
# connected" are unambiguous. Probing a port where nothing listens cannot tell
# a policy that REJECTs from a port that is simply closed: both answer
# "connection refused".

set -euo pipefail

NS_DMGR="${NS_DMGR:-was-sim-dmgr}"
NS_NODES="${NS_NODES:-was-sim-nodeagents}"
DMGR_POD="${DMGR_POD:-was-dmgr-01}"
NODE_A="${NODE_A:-was-node-01}"
NODE_B="${NODE_B:-was-node-02}"

# The port the allow rule names, read from the manifest rather than repeated
# here, so the test follows the policy if the policy changes.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ALLOWED_PORT="$(python3 -c '
import sys, yaml
for d in yaml.safe_load_all(open(sys.argv[1])):
    if d and d.get("kind") == "NetworkPolicy" and d["metadata"]["name"] == "allow-nodeagent-to-dmgr-soap":
        print(d["spec"]["ingress"][0]["ports"][0]["port"])
' "$HERE/k3s/00-namespaces-rbac.yml")"
OTHER_PORT=9043
[ -n "$ALLOWED_PORT" ] || { echo "FAIL: no allowed port found in the manifest"; exit 1; }

fail=0

ip_of() { kubectl -n "$1" get pod "$2" -o jsonpath='{.status.podIP}'; }

# A throwaway listener that dies on its own after 60 seconds, so a failed run
# leaves nothing behind in the pods.
listen() {
    local ns="$1" pod="$2" port="$3"
    kubectl -n "$ns" exec "$pod" -- sh -c \
        "nohup timeout 60 python3 -m http.server $port --bind 0.0.0.0 >/dev/null 2>&1 &"
}

# Exit 0 when a TCP connection is established within 4 seconds.
reaches() {
    local ns="$1" pod="$2" ip="$3" port="$4"
    kubectl -n "$ns" exec "$pod" -- python3 -c \
        "import socket; socket.create_connection(('$ip', $port), 4).close()" \
        >/dev/null 2>&1
}

expect() {
    local want="$1" label="$2" ns="$3" pod="$4" ip="$5" port="$6"
    if reaches "$ns" "$pod" "$ip" "$port"; then got=connects; else got=blocked; fi
    if [ "$got" = "$want" ]; then
        printf '  ok     %-46s %s\n' "$label" "$got"
    else
        printf '  FAIL   %-46s expected %s, got %s\n' "$label" "$want" "$got"
        fail=1
    fi
}

DMGR_IP="$(ip_of "$NS_DMGR" "$DMGR_POD")"
NODE_A_IP="$(ip_of "$NS_NODES" "$NODE_A")"
[ -n "$DMGR_IP" ] && [ -n "$NODE_A_IP" ] || { echo "FAIL: a pod has no IP"; exit 1; }

echo "dmgr $DMGR_IP, $NODE_A $NODE_A_IP, allowed port $ALLOWED_PORT"

listen "$NS_DMGR"  "$DMGR_POD" "$ALLOWED_PORT"
listen "$NS_DMGR"  "$DMGR_POD" "$OTHER_PORT"
listen "$NS_NODES" "$NODE_A"   "$ALLOWED_PORT"
sleep 2

# The positive case first. If it fails, either the allow rule is broken or the
# listener never started - and every "blocked" below would then prove nothing,
# so the message says which question to ask.
expect connects "node agent -> dmgr :$ALLOWED_PORT (allowed)" \
    "$NS_NODES" "$NODE_A" "$DMGR_IP" "$ALLOWED_PORT"
if [ "$fail" -ne 0 ]; then
    echo "  the allowed path does not connect: check the allow rule and the"
    echo "  namespace label was-evolution/role=nodeagents before trusting any"
    echo "  'blocked' result, since a dead listener would also read as blocked"
    exit 1
fi

expect blocked  "node agent -> dmgr :$OTHER_PORT (not allowed)" \
    "$NS_NODES" "$NODE_A" "$DMGR_IP" "$OTHER_PORT"
expect blocked  "dmgr -> node agent :$ALLOWED_PORT" \
    "$NS_DMGR" "$DMGR_POD" "$NODE_A_IP" "$ALLOWED_PORT"
expect blocked  "node agent -> other node agent :$ALLOWED_PORT" \
    "$NS_NODES" "$NODE_B" "$NODE_A_IP" "$ALLOWED_PORT"

if [ "$fail" -eq 0 ]; then
    echo "the boundary holds: every claim the policies make was checked by a connection"
fi
exit "$fail"
