# -*- coding: utf-8 -*-
"""Where a resource lives in the cell: shared by every resource handler.

A scope arrives as a dict, the same shape for every family:

    {"type": "cluster", "cluster": "ClusterEXT01"}
    {"type": "node",    "node": "EXTNode01"}
    {"type": "server",  "node": "EXTNode01", "server": "ClusterEXT01_EXTNode01_01"}
    {"type": "cell",    "cell": "Extranet_PREPROD_Cell"}

Cluster is the default the roles hand over, because the resources a cluster's
applications use belong to the cluster - every member, vertical or horizontal,
sees them, and a member added tomorrow sees them too. A resource names another
scope when it needs one.

Not a handler: the driver dispatches to handlers by name and nothing here is
one. The leading underscore says so.
"""

_PATHS = {
    "cluster": lambda s: "/ServerCluster:%s/" % s["cluster"],
    "node": lambda s: "/Node:%s/" % s["node"],
    "server": lambda s: "/Node:%s/Server:%s/" % (s["node"], s["server"]),
    "cell": lambda s: "/Cell:%s/" % s["cell"],
}

_ARGS = {
    "cluster": lambda s: "Cluster=%s" % s["cluster"],
    "node": lambda s: "Node=%s" % s["node"],
    "server": lambda s: "Node=%s,Server=%s" % (s["node"], s["server"]),
    "cell": lambda s: "Cell=%s" % s["cell"],
}


def describe(scope):
    """A scope as a person reads it - for messages, never for wsadmin."""
    kind = scope.get("type")
    if kind == "server":
        return "server %s on node %s" % (scope["server"], scope["node"])
    if kind in _PATHS:
        return "%s %s" % (kind, scope[kind])
    return repr(scope)


def _check(scope):
    kind = scope.get("type")
    if kind not in _PATHS:
        raise ValueError(
            "scope type %r is not one of cluster, node, server, cell" % kind
        )
    return kind


_NEEDS = {
    "cluster": "a cluster name",
    "node": "a node name",
    "server": "a node name and a server name",
    "cell": "a cell name",
}


def _render(table, scope):
    kind = _check(scope)
    try:
        return table[kind](scope)
    except KeyError:
        # ValueError, so the driver reports a sentence rather than a traceback:
        # an incomplete scope is a refusal of the request, not a defect.
        raise ValueError("a %s scope needs %s, got %r" % (kind, _NEEDS[kind], scope))


def find(AdminConfig, scope):
    """Config id of the scope object, or "" when the cell has no such thing."""
    found = (AdminConfig.getid(_render(_PATHS, scope)) or "").strip()
    if not found:
        return ""
    return found.splitlines()[0].strip()


def admintask_arg(scope):
    """The -scope value AdminTask expects: Cluster=X, Node=X,Server=Y ..."""
    return _render(_ARGS, scope)
