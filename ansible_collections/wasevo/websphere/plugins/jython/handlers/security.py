# -*- coding: utf-8 -*-
"""Handler for global security and the active user registry.

ONE OF FOUR REGISTRIES. WAS offers federated repositories, a standalone LDAP,
the local operating system and a custom registry. The cell holds the
configuration of all four in security.xml, and one is active. This handler
configures the declared one and makes it active, with the administrative and
application security flags, in one session.

WRITTEN WITH THE ADMINTASK VERBS, READ FROM THE CONFIGURATION. IBM's
procedure configures a registry with configureAdmin<type>UserRegistry and
activates it with setAdminActiveSecuritySettings; those verbs validate, and
-verifyRegistry makes WAS check that the primary administrator exists in the
registry before it is saved. What they wrote is read back with AdminConfig,
the attributes of security.xml, which is what a plan can compare.

THE BIND PASSWORD CANNOT BE COMPARED, like a J2C alias password. It is
written when the LDAP configuration is written - on a change, or on every run
under password_policy: always - and never appears in what this handler
returns.

WHAT WAS ACCEPTS AND SHOULD NOT, refused before anything is written:

  - the local operating system registry on a cell whose nodes run on more
    than one host: each node would check passwords against its own
    operating system, and the same user would have a different password, or
    none, depending on the server that answers

Every change applies when the deployment manager, the node agents and the
servers restart; the module says so, and restarts nothing.

Five callables, same contract as every other handler - see cluster.py.
"""

REGISTRY_TYPES = ("WIMUserRegistry", "LDAPUserRegistry", "LocalOSUserRegistry", "CustomUserRegistry")

# Security attribute -> the flag setAdminActiveSecuritySettings takes.
FLAGS = (
    ("admin_security", "enabled", "-enableGlobalSecurity"),
    ("app_security", "appEnabled", "-appSecurityEnabled"),
    ("java2_security", "enforceJava2Security", "-enforceJava2Security"),
)

# AdminConfig attribute -> configureAdminLDAPUserRegistry flag.
LDAP_FLAGS = (
    ("primaryAdminId", "-primaryAdminId"),
    ("type", "-ldapServerType"),
    ("baseDN", "-baseDN"),
    ("bindDN", "-bindDN"),
    ("sslEnabled", "-sslEnabled"),
    ("sslConfig", "-sslConfig"),
    ("searchTimeout", "-searchTimeout"),
    ("reuseConnection", "-reuseConnection"),
)


def _ids(text):
    text = (text or "").strip()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    return [part for part in text.replace("\n", " ").split() if part]


def _first(AdminConfig, config_type):
    found = _ids(AdminConfig.list(config_type))
    return found and found[0] or ""


def _hosts(AdminConfig, registry_id):
    return [{"host": AdminConfig.showAttribute(e, "host"), "port": AdminConfig.showAttribute(e, "port")}
            for e in _ids(AdminConfig.showAttribute(registry_id, "hosts"))]


def _properties(AdminConfig, registry_id):
    found = {}
    for prop in _ids(AdminConfig.showAttribute(registry_id, "properties")):
        found[AdminConfig.showAttribute(prop, "name")] = (prop, AdminConfig.showAttribute(prop, "value"))
    return found


def _active_type(AdminConfig, security_id):
    active = AdminConfig.showAttribute(security_id, "activeUserRegistry")
    for config_type in REGISTRY_TYPES:
        if active and active in _ids(AdminConfig.list(config_type)):
            return config_type
    return ""


def read(admin, params):
    AdminConfig = admin["AdminConfig"]
    security_id = _first(AdminConfig, "Security")
    if not security_id:
        return {}
    registry = params["registry"]
    registry_id = _first(AdminConfig, registry["type"])
    before = {"exists": True, "active_registry": _active_type(AdminConfig, security_id)}
    for key, attribute, _ in FLAGS:
        if key in params:
            before[key] = AdminConfig.showAttribute(security_id, attribute)
    current = {"type": registry["type"], "attributes": dict(
        (a, AdminConfig.showAttribute(registry_id, a) or "") for a in registry["attributes"])}
    if "hosts" in registry:
        current["hosts"] = _hosts(AdminConfig, registry_id)
    if "properties" in registry:
        current["properties"] = dict((n, v[1]) for n, v in _properties(AdminConfig, registry_id).items())
    before["registry"] = current
    return before


def _node_hosts(AdminConfig):
    hosts = []
    for index in _ids(AdminConfig.list("ServerIndex")):
        host = AdminConfig.showAttribute(index, "hostName")
        if host and host not in hosts:
            hosts.append(host)
    return hosts


def _wanted_registry(params):
    registry = params["registry"]
    wanted = {"type": registry["type"], "attributes": dict(registry["attributes"])}
    for key in ("hosts", "properties"):
        if key in registry:
            wanted[key] = registry[key]
    return wanted


def plan_present(admin, params, before):
    if not before:
        raise ValueError("this cell has no security configuration - is it a cell?")
    registry = params["registry"]
    if registry["type"] == "LocalOSUserRegistry":
        hosts = _node_hosts(admin["AdminConfig"])
        if len(hosts) > 1:
            raise ValueError(
                "the local operating system registry on a cell whose nodes run on %d "
                "hosts (%s): each node would check passwords against its own "
                "operating system. Use federated repositories or an LDAP"
                % (len(hosts), ", ".join(hosts)))

    after = {"exists": True, "active_registry": registry["type"],
             "registry": _wanted_registry(params)}
    for key, _, _ in FLAGS:
        if key in params:
            after[key] = params[key]
    changed = after != before
    if not changed and params.get("bind_password") and params.get("password_policy") == "always":
        # Written and not comparable: the run says what it does.
        changed = True
    return changed, after


def plan_absent(admin, params, before):
    raise ValueError(
        "security has no state absent: a cell keeps a registry and administrative "
        "security. Declare the registry the cell should use instead"
    )


def _configure(admin, params, before):
    """configureAdmin<type>UserRegistry, with what differs and what it needs."""
    AdminTask = admin["AdminTask"]
    registry = params["registry"]
    attrs = registry["attributes"]
    verify = ["-verifyRegistry", params.get("verify_registry", True) and "true" or "false"]
    current = (before.get("registry") or {})
    differs = current != _wanted_registry(params) or before.get("active_registry") != registry["type"]
    always = params.get("bind_password") and params.get("password_policy") == "always"
    if not differs and not always:
        return

    kind = registry["type"]
    if kind == "WIMUserRegistry":
        AdminTask.configureAdminWIMUserRegistry(
            ["-realmName", attrs["realm"], "-primaryAdminId", attrs["primaryAdminId"]] + verify)
    elif kind == "LocalOSUserRegistry":
        AdminTask.configureAdminLocalOSUserRegistry(
            ["-primaryAdminId", attrs["primaryAdminId"]] + verify)
    elif kind == "CustomUserRegistry":
        AdminTask.configureAdminCustomUserRegistry(
            ["-customRegClass", attrs["customRegistryClassName"],
             "-primaryAdminId", attrs["primaryAdminId"]] + verify)
    elif kind == "LDAPUserRegistry":
        args = []
        for attribute, flag in LDAP_FLAGS:
            if attribute in attrs and attrs[attribute] != "":
                args += [flag, attrs[attribute]]
        first = registry["hosts"][0]
        args += ["-ldapHost", first["host"], "-ldapPort", first["port"]]
        if params.get("bind_password"):
            args += ["-bindPassword", params["bind_password"]]
        AdminTask.configureAdminLDAPUserRegistry(args + verify)


def _reconcile_lists(admin, params):
    """The LDAP failover hosts and the custom registry properties, which the
    AdminTask verbs set one of, or none: made to match with AdminConfig."""
    AdminConfig = admin["AdminConfig"]
    registry = params["registry"]
    registry_id = _first(AdminConfig, registry["type"])
    if "hosts" in registry and _hosts(AdminConfig, registry_id) != registry["hosts"]:
        for endpoint in _ids(AdminConfig.showAttribute(registry_id, "hosts")):
            AdminConfig.remove(endpoint)
        for entry in registry["hosts"]:
            AdminConfig.create("EndPoint", registry_id,
                               [["host", entry["host"]], ["port", entry["port"]]], "hosts")
    if "properties" in registry:
        found = _properties(AdminConfig, registry_id)
        for name in sorted(registry["properties"]):
            value = registry["properties"][name]
            if name not in found:
                AdminConfig.create("Property", registry_id, [["name", name], ["value", value]],
                                   "properties")
            elif found[name][1] != value:
                AdminConfig.modify(found[name][0], [["value", value]])
        for name in sorted(found):
            if name not in registry["properties"]:
                AdminConfig.remove(found[name][0])


def write_present(admin, params, before):
    _configure(admin, params, before)
    _reconcile_lists(admin, params)

    args = []
    for key, attribute, flag in FLAGS:
        if key in params and before.get(key) != params[key]:
            args += [flag, params[key]]
    if before.get("active_registry") != params["registry"]["type"]:
        args += ["-activeUserRegistry", params["registry"]["type"]]
    if args:
        admin["AdminTask"].setAdminActiveSecuritySettings(args)


def write_absent(admin, params, before):
    plan_absent(admin, params, before)


def sync(admin, params):
    AdminControl = admin["AdminControl"]
    for mbean in AdminControl.queryNames("type=NodeSync,*").splitlines():
        mbean = mbean.strip()
        if mbean:
            AdminControl.invoke(mbean, "sync")
