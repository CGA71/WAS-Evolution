# -*- coding: utf-8 -*-
"""Handler for the settings every application server of a target carries:
its transaction service, its EJB container, its JPA defaults, its dynamic
cache, its logging and trace, its PMI service, its JVM custom properties -
and the cluster-wide settings that go with them.

ONE HANDLER FOR SEVERAL ROLES. The transactions, EJB container, CDI, JPA,
dynamic cache, logging and PMI roles all set attributes on objects every
server already has. What differs
is which objects and which attributes, and that is the role's business: the
role translates an intent ("peer recovery", "no implicit bean archives") into
WAS attributes, and this handler applies them, the same way, to every server
of the target.

THE TARGET IS READ FROM THE CELL. A cluster target means the members the cell
holds now, not a list the run computed - so a member added since the last run
gets the settings on the next replay, and a member the run does not know
about is not silently left behind.

ATTRIBUTE NAMES ARE CHECKED AGAINST THE CELL. Before anything is written,
every declared attribute is looked up in AdminConfig.attributes(type). A
misspelt or unsupported name is refused with the list of valid ones, instead
of AdminConfig.modify failing halfway through a member list - or, worse,
succeeding on an attribute WAS ignores.

WHAT WAS ACCEPTS AND SHOULD NOT, refused before anything is written:

  - persistent EJB timers on a cluster of several members, with neither a
    shared datasource nor a custom scheduler: each member then keeps its own
    timer database, and a timer created at startup fires once per member
  - a datasource the settings name (a timer database, a JPA default) that the
    cell does not have - the JDBC job comes first

ONE VALUE PER SERVER WHERE IT MUST BE. A value may carry {node} and {server},
replaced for each server - a transaction log directory is per server by
nature, and peer recovery needs each member's own log where every other
member can read it.

There is no state absent: a setting is not removed, it is set back to the WAS
default by declaring that default.

Five callables, same contract as every other handler - see cluster.py.
"""

# type -> (parent type, created under the parent when missing)
# Every server has all of them as soon as it exists, except the JPA service,
# created on first use, which is what the IBM procedure for a default
# persistence provider does. The parent of a service is the Server itself,
# not its ApplicationServer component, as server.xml nests them.
COMPONENTS = {
    "TransactionService": ("ApplicationServer", False),
    "EJBContainer": ("ApplicationServer", False),
    "EJBCache": ("EJBContainer", False),
    "EJBTimer": ("EJBContainer", False),
    "JavaPersistenceAPIService": ("ApplicationServer", True),
    # Dynamic cache and servlet caching - family 5.
    "DynamicCache": ("ApplicationServer", False),
    "WebContainer": ("ApplicationServer", False),
    # Logging and trace, in both modes - family 5. A server holds the basic
    # mode's services and the HPEL ones at once; the enable flags say which
    # one runs.
    "RASLoggingService": ("Server", False),
    "TraceService": ("Server", False),
    "TraceLog": ("TraceService", False),
    "HighPerformanceExtensibleLogging": ("Server", False),
    "HPELLog": ("HighPerformanceExtensibleLogging", False),
    "HPELTrace": ("HighPerformanceExtensibleLogging", False),
    "HPELTextLog": ("HighPerformanceExtensibleLogging", False),
    # Performance Monitoring Infrastructure - family 6.
    "PMIService": ("Server", False),
}


def _ids(text):
    text = (text or "").strip()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    return [part for part in text.replace("\n", " ").split() if part]


def _text(value):
    """What AdminConfig shows for a value: a string, booleans in lower case."""
    if value is True:
        return "true"
    if value is False:
        return "false"
    if value is None:
        return ""
    return str(value)


def _target(admin, params):
    """(target config id or "", [(node, server, server id)]) - None when absent."""
    AdminConfig = admin["AdminConfig"]
    target = params["target"]
    if target.get("cluster"):
        cluster_id = AdminConfig.getid("/ServerCluster:%s/" % target["cluster"])
        if not cluster_id:
            return None
        servers = []
        for member in _ids(AdminConfig.showAttribute(cluster_id, "members")):
            node = AdminConfig.showAttribute(member, "nodeName")
            name = AdminConfig.showAttribute(member, "memberName")
            servers.append((node, name, AdminConfig.getid("/Node:%s/Server:%s/" % (node, name))))
        servers.sort()
        return cluster_id, servers
    server_id = AdminConfig.getid("/Node:%s/Server:%s/" % (target["node"], target["server"]))
    if not server_id:
        return None
    return server_id, [(target["node"], target["server"], server_id)]


def _component(AdminConfig, server_id, config_type):
    found = _ids(AdminConfig.list(config_type, server_id))
    return found and found[0] or ""


def _jvm_properties(AdminConfig, server_id, names):
    """name -> (property id, value) for the declared names the JVM carries."""
    jvm = _component(AdminConfig, server_id, "JavaVirtualMachine")
    found = {}
    if not jvm:
        return jvm, found
    for prop in _ids(AdminConfig.showAttribute(jvm, "systemProperties")):
        name = AdminConfig.showAttribute(prop, "name")
        if name in names:
            found[name] = (prop, AdminConfig.showAttribute(prop, "value"))
    return jvm, found


def read(admin, params):
    AdminConfig = admin["AdminConfig"]
    # Names first: reading a misspelt attribute would fail with a traceback,
    # where the operator needs the list of the valid ones.
    _check_names(AdminConfig, params)
    resolved = _target(admin, params)
    if resolved is None:
        return {}
    target_id, servers = resolved
    components = params.get("components") or {}
    properties = params.get("jvm_properties") or {}

    before = {"exists": True, "servers": {}}
    for node, name, server_id in servers:
        entry = {}
        for config_type in sorted(components):
            config_id = _component(AdminConfig, server_id, config_type)
            if not config_id:
                entry[config_type] = None
                continue
            entry[config_type] = dict(
                (attribute, AdminConfig.showAttribute(config_id, attribute))
                for attribute in components[config_type]
            )
        if properties:
            jvm, found = _jvm_properties(AdminConfig, server_id, properties)
            entry["jvm_properties"] = dict((n, found[n][1]) for n in found)
        before["servers"]["%s/%s" % (node, name)] = entry

    if params.get("cluster_attributes"):
        before["cluster_attributes"] = dict(
            (attribute, AdminConfig.showAttribute(target_id, attribute))
            for attribute in params["cluster_attributes"]
        )
    if params.get("jpa_spec_level"):
        before["jpa_spec_level"] = admin["AdminTask"].showJPASpecLevel(target_id).strip()
    return before


# ---------------------------------------------------------------------------
# What WAS accepts and should not
# ---------------------------------------------------------------------------

def _known_attributes(AdminConfig, config_type):
    """The attribute names AdminConfig.attributes lists for a type."""
    names = []
    for line in AdminConfig.attributes(config_type).splitlines():
        line = line.strip()
        if line:
            names.append(line.split()[0])
    return names


def _check_names(AdminConfig, params):
    """Every declared type and attribute, against what the cell knows."""
    checks = [(t, a) for t, a in (params.get("components") or {}).items()]
    if params.get("cluster_attributes"):
        checks.append(("ServerCluster", params["cluster_attributes"]))
    for config_type, attributes in checks:
        if config_type not in COMPONENTS and config_type != "ServerCluster":
            raise ValueError("%s is not a server setting this handler applies" % config_type)
        known = _known_attributes(AdminConfig, config_type)
        unknown = [a for a in sorted(attributes) if a not in known]
        if unknown:
            raise ValueError(
                "%s has no attribute %s in this cell. Its attributes are: %s"
                % (config_type, ", ".join(unknown), ", ".join(sorted(known)))
            )


def _refuse(admin, params, before):
    AdminConfig = admin["AdminConfig"]

    timer = (params.get("components") or {}).get("EJBTimer")
    servers = before and before.get("servers") or {}
    if timer is not None and len(servers) > 1:
        if not timer.get("datasourceJNDIName") and not timer.get("schedulerJNDIName"):
            raise ValueError(
                "EJB timers are declared for %d servers with neither a shared "
                "datasource nor a custom scheduler. Each member would keep its "
                "own timer database, and a timer an application creates at "
                "startup would fire once per member. Name the shared timer "
                "datasource." % len(servers)
            )

    if admin.get("check_mode"):
        return
    wanted = params.get("requires_datasources") or []
    if wanted:
        present = []
        for ds in AdminConfig.list("DataSource").splitlines():
            ds = ds.strip()
            if ds:
                present.append(AdminConfig.showAttribute(ds, "jndiName"))
        missing = [j for j in wanted if j not in present]
        if missing:
            raise ValueError(
                "%s named by these settings is not a datasource of this cell. "
                "Run the JDBC job first - traditional_jdbc.yml."
                % ", ".join(missing)
            )


def _for(value, node, server):
    return _text(value).replace("{node}", node).replace("{server}", server)


def _wanted(params, node, server):
    """The declared values for one server, placeholders replaced."""
    components = params.get("components") or {}
    entry = {}
    for config_type in sorted(components):
        entry[config_type] = dict(
            (a, _for(v, node, server)) for a, v in components[config_type].items())
    if params.get("jvm_properties"):
        entry["jvm_properties"] = dict(
            (n, _for(v, node, server)) for n, v in params["jvm_properties"].items())
    return entry


def plan_present(admin, params, before):
    _refuse(admin, params, before)
    if not before:
        target = params["target"]
        what = target.get("cluster") and "cluster %s" % target["cluster"] \
            or "server %s on node %s" % (target.get("server"), target.get("node"))
        if not admin.get("check_mode"):
            raise ValueError(
                "%s does not exist in this cell. Run the cluster and member "
                "jobs first." % what
            )
        return True, {"exists": False, "target_pending": True}

    planned = {"exists": True, "servers": {}}
    changed = False
    for key in sorted(before["servers"]):
        current = before["servers"][key]
        node, server = key.split("/", 1)
        wanted = _wanted(params, node, server)
        entry = {}
        for config_type in wanted:
            if config_type != "jvm_properties" and current.get(config_type) is None \
                    and not COMPONENTS[config_type][1]:
                raise ValueError(
                    "server %s has no %s, which every application server "
                    "carries. Is it an application server?" % (key, config_type)
                )
            entry[config_type] = dict(wanted[config_type])
            if (current.get(config_type) or {}) != entry[config_type]:
                changed = True
        planned["servers"][key] = entry

    if params.get("cluster_attributes"):
        planned["cluster_attributes"] = dict(
            (a, _text(v)) for a, v in params["cluster_attributes"].items())
        changed = changed or planned["cluster_attributes"] != before.get("cluster_attributes")
    if params.get("jpa_spec_level"):
        planned["jpa_spec_level"] = _text(params["jpa_spec_level"])
        changed = changed or planned["jpa_spec_level"] != before.get("jpa_spec_level")
    return changed, planned


def plan_absent(admin, params, before):
    raise ValueError(
        "server settings have no state absent: a setting is not removed, it "
        "is set back by declaring the WAS default"
    )


def write_present(admin, params, before):
    AdminConfig = admin["AdminConfig"]
    target_id, servers = _target(admin, params)

    for node, name, server_id in servers:
        wanted = _wanted(params, node, name)
        for config_type in sorted(params.get("components") or {}):
            config_id = _component(AdminConfig, server_id, config_type)
            values = wanted[config_type]
            if not config_id:
                parent = _component(AdminConfig, server_id, COMPONENTS[config_type][0])
                AdminConfig.create(config_type, parent, [[a, values[a]] for a in sorted(values)])
                continue
            different = [[a, values[a]] for a in sorted(values)
                         if AdminConfig.showAttribute(config_id, a) != values[a]]
            if different:
                AdminConfig.modify(config_id, different)

        properties = wanted.get("jvm_properties") or {}
        if properties:
            jvm, found = _jvm_properties(AdminConfig, server_id, properties)
            for prop_name in sorted(properties):
                if prop_name not in found:
                    AdminConfig.create("Property", jvm,
                                       [["name", prop_name], ["value", properties[prop_name]]])
                elif found[prop_name][1] != properties[prop_name]:
                    AdminConfig.modify(found[prop_name][0], [["value", properties[prop_name]]])

    if params.get("cluster_attributes"):
        different = [[a, _text(v)] for a, v in sorted(params["cluster_attributes"].items())
                     if AdminConfig.showAttribute(target_id, a) != _text(v)]
        if different:
            AdminConfig.modify(target_id, different)

    if params.get("jpa_spec_level"):
        AdminTask = admin["AdminTask"]
        level = _text(params["jpa_spec_level"])
        if AdminTask.showJPASpecLevel(target_id).strip() != level:
            AdminTask.modifyJPASpecLevel(target_id, ["-specLevel", level])


def write_absent(admin, params, before):
    plan_absent(admin, params, before)


def sync(admin, params):
    AdminControl = admin["AdminControl"]
    for mbean in AdminControl.queryNames("type=NodeSync,*").splitlines():
        mbean = mbean.strip()
        if mbean:
            AdminControl.invoke(mbean, "sync")
