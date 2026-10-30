#!/usr/bin/env python3
"""Assert that no two servers on one node share an endpoint port.

Reads the simulation's fake cell state on stdin - the JSON file the wsadmin
stub keeps inside the pod - and checks the one property a vertical cluster
lives or dies by: two JVMs on the same node must not be given the same port.

WHY THIS IS ASSERTED AND NOT DESCRIBED. WAS saves a configuration where two
servers of a node claim the same WC_defaulthost without complaint. The second
server then fails to start, possibly hours later, with an error about an
address already in use - and the configuration that produced it looks fine in
the console. genUniquePorts is what prevents it, so whether it actually worked
is worth a check of its own.

Lives in a file rather than inline in .gitlab-ci.yml because Python inside a
YAML block scalar has to be indented and Python objects to that.

    kubectl -n ns exec pod -- cat /opt/exploit/was-sim-state.json \
      | python3 ci/assert-member-ports.py [endpoint ...]

Exit 0 when every (node, port) pair is held by at most one server.
"""

import json
import sys

DEFAULT_ENDPOINTS = ["WC_defaulthost", "BOOTSTRAP_ADDRESS", "SOAP_CONNECTOR_ADDRESS"]


def main():
    endpoints = sys.argv[1:] or DEFAULT_ENDPOINTS
    state = json.load(sys.stdin)

    entries = state.get("entries") or {}
    if not entries:
        print("the fake cell holds no server entry at all - nothing was created")
        return 1

    holders = {}
    for entry in entries.values():
        for special_id in entry.get("special_ids", []):
            special = state["specials"][special_id]
            if special["endPointName"] not in endpoints:
                continue
            port = state["ports"][special["endPoint"]]["port"]
            key = (entry["nodeName"], special["endPointName"], port)
            holders.setdefault(key, []).append(entry["serverName"])

    clashes = dict((key, servers) for key, servers in holders.items() if len(servers) > 1)
    if clashes:
        print("two servers on one node share a port:")
        for (node, endpoint, port), servers in sorted(clashes.items()):
            print("  %s %s %s -> %s" % (node, endpoint, port, ", ".join(sorted(servers))))
        return 1

    nodes = sorted(set(node for node, _, _ in holders))
    print("%d endpoints over %d node(s), all distinct per node: %s"
          % (len(holders), len(nodes), ", ".join(nodes)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
