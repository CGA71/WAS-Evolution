# -*- coding: utf-8 -*-
"""Read-only: what the OTHER installed applications still use.

Decommissioning an application removes the resources it declared - unless
another application still uses them. This handler answers that question from
the cell itself, in one wsadmin session:

  jndi            every JNDI name another application is bound to: resource
                  references (datasources, connection factories), resource
                  environment references (queues, topics), message-driven
                  bindings (activation specifications, destinations)
  libraries       every shared library another application is bound to
  auth_aliases    every J2C alias, with the datasources and J2C connection
                  factories that present it - an alias stays while something
                  that is not being removed still presents it
  cluster_members every cluster with its members, as node/server - so a
                  cluster or a node is removed only when nothing else is on it
  nodes           for the nodes hosting the decommissioned cluster: their
                  application servers, clustered or not, and the resources
                  scoped to them - a node is removed only when it has neither

Nothing is written: plan_present reports no change, so the driver never calls
a write. The module behind it is an _info module.
"""

# The AdminApp tasks whose bindings name a JNDI resource.
_JNDI_TASKS = (
    "-MapResRefToEJB",
    "-MapResEnvRefToRes",
    "-BindJndiForEJBMessageBinding",
    "-MapMessageDestinationRefToEJB",
)


def _view(AdminApp, name, task):
    try:
        return AdminApp.view(name, [task]) or ""
    except Exception:
        return ""


def _values(text, wanted):
    values = []
    for line in text.splitlines():
        if ":" not in line:
            continue
        label, value = line.split(":", 1)
        value = value.strip()
        if value and wanted(label.strip().lower()):
            values.append(value)
    return values


def _jndi(AdminApp, name):
    found = []
    for task in _JNDI_TASKS:
        for value in _values(_view(AdminApp, name, task), lambda label: "jndi" in label):
            if value not in found:
                found.append(value)
    found.sort()
    return found


def _libraries(AdminApp, name):
    found = []
    for value in _values(_view(AdminApp, name, "-MapSharedLibForMod"),
                         lambda label: label.startswith("shared lib")):
        for one in value.replace(",", "+").split("+"):
            one = one.strip()
            if one and one not in found:
                found.append(one)
    found.sort()
    return found


def _aliases(AdminConfig):
    users = {}
    for config_type in ("DataSource", "J2CConnectionFactory"):
        try:
            ids = AdminConfig.list(config_type).splitlines()
        except Exception:
            # A cell - or a simulation - that knows no such type has none.
            continue
        for config_id in ids:
            config_id = config_id.strip()
            if not config_id:
                continue
            try:
                alias = AdminConfig.showAttribute(config_id, "authDataAlias") or ""
            except Exception:
                alias = ""
            if not alias:
                continue
            users.setdefault(alias, []).append(AdminConfig.showAttribute(config_id, "name"))
    for alias in users.keys():
        users[alias].sort()
    return users


def _targets(AdminApp, name):
    found = []
    for value in _values(_view(AdminApp, name, "-MapModulesToServers"), lambda label: label == "server"):
        for one in value.split("+"):
            one = one.strip()
            if one.startswith("WebSphere:"):
                one = one[len("WebSphere:"):]
            pairs = {}
            for part in one.split(","):
                if "=" in part:
                    key, val = part.split("=", 1)
                    pairs[key.strip()] = val.strip()
            if "cluster" in pairs:
                one = "cluster=%s" % pairs["cluster"]
            elif "server" in pairs:
                one = "node=%s,server=%s" % (pairs.get("node", ""), pairs["server"])
            if one and one not in found and "webserver" not in one.lower():
                found.append(one)
    found.sort()
    return found


def _cluster_members(AdminConfig):
    """cluster name -> ["node/server", ...], for the cluster and node removal
    decisions: a node still carrying a member of another cluster stays."""
    clusters = {}
    for cluster_id in AdminConfig.list("ServerCluster").splitlines():
        cluster_id = cluster_id.strip()
        if not cluster_id:
            continue
        members = (AdminConfig.showAttribute(cluster_id, "members") or "").strip()
        if members.startswith("[") and members.endswith("]"):
            members = members[1:-1]
        found = []
        for member_id in members.split():
            found.append("%s/%s" % (AdminConfig.showAttribute(member_id, "nodeName"),
                                    AdminConfig.showAttribute(member_id, "memberName")))
        found.sort()
        clusters[AdminConfig.showAttribute(cluster_id, "name")] = found
    return clusters


# What makes a node still needed, besides its servers: a resource scoped to the
# node, or to one of its servers. J2C aliases live in the cell's security
# configuration, not on a node; WebSphere variables are left out because every
# node's variables.xml carries WAS's own, and a node would never look empty.
_NODE_RESOURCE_TYPES = (
    "JDBCProvider", "DataSource", "Library",
    "SIBJMSConnectionFactory", "SIBJMSQueue", "SIBJMSTopic", "SIBJMSActivationSpec",
    "MQConnectionFactory", "MQQueue", "MQTopic", "J2CActivationSpec",
    "J2CResourceAdapter", "MailProvider", "URLProvider",
)


def _ids(text):
    return [line.strip() for line in (text or "").splitlines() if line.strip()]


def _list(AdminConfig, config_type, scope_id):
    try:
        return _ids(AdminConfig.list(config_type, scope_id))
    except Exception:
        # A type this cell - or the simulation - does not know has nothing.
        return []


def _nodes(AdminConfig, cluster, cluster_members):
    """For every node hosting a member of `cluster`: its application servers -
    every server but the node agent and web servers, clustered or not - and
    the resources scoped to it or to one of its servers."""
    nodes = {}
    for member in cluster_members.get(cluster, []):
        node = member.split("/", 1)[0]
        if node in nodes:
            continue
        node_id = (AdminConfig.getid("/Node:%s/" % node) or "").strip()
        servers = []
        server_scopes = []
        try:
            server_ids = _ids(AdminConfig.list("Server", node_id))
        except Exception:
            server_ids = None
        if server_ids is None:
            # No Server objects to list - the simulation: the members of every
            # cluster on this node are its application servers.
            for members in cluster_members.values():
                for m in members:
                    if m.split("/", 1)[0] == node and m.split("/", 1)[1] not in servers:
                        servers.append(m.split("/", 1)[1])
        else:
            for server_id in server_ids:
                kind = ""
                try:
                    kind = AdminConfig.showAttribute(server_id, "serverType") or ""
                except Exception:
                    pass
                if kind in ("NODE_AGENT", "WEB_SERVER", "PROXY_SERVER"):
                    continue
                servers.append(AdminConfig.showAttribute(server_id, "name"))
        for server in servers:
            scope = (AdminConfig.getid("/Node:%s/Server:%s/" % (node, server)) or "").strip()
            if scope:
                server_scopes.append((server, scope))
        resources = []
        for config_type in _NODE_RESOURCE_TYPES:
            for scope_name, scope in [("", node_id)] + server_scopes:
                for config_id in _list(AdminConfig, config_type, scope):
                    name = ""
                    try:
                        name = AdminConfig.showAttribute(config_id, "name") or ""
                    except Exception:
                        pass
                    entry = "%s %s%s" % (config_type, name or config_id,
                                         scope_name and (" on " + scope_name) or "")
                    if entry not in resources:
                        resources.append(entry)
        servers.sort()
        resources.sort()
        nodes[node] = {"servers": servers, "resources": resources}
    return nodes


def read(admin, params):
    AdminApp = admin["AdminApp"]
    exclude = params.get("exclude") or []
    applications = {}
    for name in [a.strip() for a in AdminApp.list().splitlines() if a.strip()]:
        if name in exclude:
            continue
        applications[name] = {"jndi": _jndi(AdminApp, name), "libraries": _libraries(AdminApp, name),
                              "targets": _targets(AdminApp, name)}

    jndi = []
    libraries = []
    for name in applications.keys():
        for value in applications[name]["jndi"]:
            if value not in jndi:
                jndi.append(value)
        for value in applications[name]["libraries"]:
            if value not in libraries:
                libraries.append(value)
    jndi.sort()
    libraries.sort()
    cluster_members = _cluster_members(admin["AdminConfig"])
    return {
        "applications": applications,
        "jndi": jndi,
        "libraries": libraries,
        "auth_aliases": _aliases(admin["AdminConfig"]),
        "cluster_members": cluster_members,
        "nodes": params.get("cluster") and _nodes(admin["AdminConfig"], params["cluster"], cluster_members) or {},
    }


def plan_present(admin, params, before):
    return False, before


def plan_absent(admin, params, before):
    return False, before


def write_present(admin, params, before):
    raise ValueError("application_refs only reads")


def write_absent(admin, params, before):
    raise ValueError("application_refs only reads")
