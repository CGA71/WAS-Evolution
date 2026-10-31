# -*- coding: utf-8 -*-
"""Handler for datasources - and their connection pool and custom properties.

A datasource is built on a JDBC provider of the same scope, named in the
request. What the role hands over is already rendered for this back-end: the
abstract vendor of the shared model is now a helper class, Liberty-style pool
settings are now WAS attribute names in seconds. This handler compares and
writes; it does not translate.

ONLY WHAT IS DECLARED IS COMPARED. A datasource carries dozens of pool and
custom properties with WAS defaults. Reporting all of them would bury the one
that changed, and "correcting" the ones nobody declared would overwrite tuning
someone did in the console on purpose. So the pool settings and the custom
properties read back are exactly the ones the request names.

TWO THINGS WAS ALLOWS AND SHOULD NOT. It creates a datasource whose provider
does not exist in that scope, or whose J2C alias does not exist, and the
mistake surfaces at runtime as a connection failure. Both are checked here,
before anything is written, and refused with the step that creates the
missing piece - except in a check run, where that step ran in check mode too
and the piece is a future rather than an absence.

Five callables, same contract as every other handler - see cluster.py.
"""

import _scope


def _type_of(value):
    """The Java type a custom property value is declared with."""
    text = str(value)
    if text.lower() in ("true", "false"):
        return "java.lang.Boolean"
    try:
        int(text)
        return "java.lang.Integer"
    except ValueError:
        return "java.lang.String"


def _ids(text):
    """A bracketed id list as AdminConfig renders it, as a Python list."""
    text = (text or "").strip()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    return [part for part in text.split() if part]


def _providers(AdminConfig, scope_id):
    found = {}
    for config_id in AdminConfig.list("JDBCProvider", scope_id).splitlines():
        config_id = config_id.strip()
        if config_id:
            found[AdminConfig.showAttribute(config_id, "name")] = config_id
    return found


def _aliases(AdminConfig):
    names = []
    for config_id in AdminConfig.list("JAASAuthData").splitlines():
        config_id = config_id.strip()
        if config_id:
            names.append(AdminConfig.showAttribute(config_id, "alias"))
    return names


def _properties(AdminConfig, ds_id):
    """name -> (config_id, value) for every custom property of a datasource."""
    found = {}
    property_set = (AdminConfig.showAttribute(ds_id, "propertySet") or "").strip()
    if not property_set:
        return found, ""
    for prop in _ids(AdminConfig.showAttribute(property_set, "resourceProperties")):
        found[AdminConfig.showAttribute(prop, "name")] = (
            prop, AdminConfig.showAttribute(prop, "value"),
        )
    return found, property_set


def _datasources(AdminConfig, scope_id):
    found = {}
    for config_id in AdminConfig.list("DataSource", scope_id).splitlines():
        config_id = config_id.strip()
        if config_id:
            found[AdminConfig.showAttribute(config_id, "name")] = config_id
    return found


def _as_seen(AdminConfig, ds_id, desired):
    """A live datasource, reduced to what the request declares."""
    provider_id = AdminConfig.showAttribute(ds_id, "provider")
    seen = {
        "name": desired["name"],
        "provider": provider_id and AdminConfig.showAttribute(provider_id, "name") or "",
        "jndi_name": AdminConfig.showAttribute(ds_id, "jndiName") or "",
        "helper": AdminConfig.showAttribute(ds_id, "datasourceHelperClassname") or "",
        "auth_alias": AdminConfig.showAttribute(ds_id, "authDataAlias") or "",
        "statement_cache_size": int(AdminConfig.showAttribute(ds_id, "statementCacheSize") or 0),
        "pool": {},
        "properties": {},
    }
    pool_id = (AdminConfig.showAttribute(ds_id, "connectionPool") or "").strip()
    for key in sorted((desired.get("pool") or {}).keys()):
        seen["pool"][key] = int(AdminConfig.showAttribute(pool_id, key) or 0)
    props, _ = _properties(AdminConfig, ds_id)
    for key in sorted((desired.get("properties") or {}).keys()):
        if key in props:
            seen["properties"][key] = str(props[key][1])
    return seen


def _as_desired(ds):
    return {
        "name": ds["name"],
        "provider": ds["provider"],
        "jndi_name": ds["jndi_name"],
        "helper": ds["helper"],
        "auth_alias": ds.get("auth_alias") or "",
        "statement_cache_size": int(ds.get("statement_cache_size", 10)),
        "pool": dict((k, int(v)) for k, v in (ds.get("pool") or {}).items()),
        "properties": dict((k, str(v)) for k, v in (ds.get("properties") or {}).items()),
    }


def read(admin, params):
    AdminConfig = admin["AdminConfig"]
    scope_id = _scope.find(AdminConfig, params["scope"])
    if not scope_id:
        return {}
    live = _datasources(AdminConfig, scope_id)
    seen = []
    for ds in params.get("datasources") or []:
        if ds["name"] in live:
            seen.append(_as_seen(AdminConfig, live[ds["name"]], ds))
    return {
        "exists": True,
        "scope": _scope.describe(params["scope"]),
        "datasources": sorted(seen, key=lambda d: d["name"]),
    }


def _refuse_missing(admin, params, scope_id):
    """The provider and the alias each datasource names must exist."""
    if admin.get("check_mode"):
        return
    AdminConfig = admin["AdminConfig"]
    providers = scope_id and _providers(AdminConfig, scope_id) or {}
    aliases = _aliases(AdminConfig)
    for ds in params.get("datasources") or []:
        if ds["provider"] not in providers:
            raise ValueError(
                "datasource %s names JDBC provider %s, which does not exist in "
                "%s. The provider step of the same role creates it; run the "
                "role rather than the datasource step alone."
                % (ds["name"], ds["provider"], _scope.describe(params["scope"]))
            )
        alias = ds.get("auth_alias")
        if alias and alias not in aliases:
            raise ValueError(
                "datasource %s names J2C alias %s, which does not exist in the "
                "cell. WAS would accept it and the datasource would fail at "
                "its first connection. Run the J2C job first - "
                "traditional_j2c.yml." % (ds["name"], alias)
            )


def plan_present(admin, params, before):
    datasources = params.get("datasources") or []

    if not before:
        if not admin.get("check_mode"):
            raise ValueError(
                "%s does not exist in this cell, so no datasource can be "
                "created there." % _scope.describe(params["scope"])
            )
        return True, {
            "exists": False,
            "scope": _scope.describe(params["scope"]),
            "scope_pending": True,
            "datasources": sorted([_as_desired(d) for d in datasources], key=lambda d: d["name"]),
        }

    _refuse_missing(admin, params, _scope.find(admin["AdminConfig"], params["scope"]))

    live = dict((d["name"], d) for d in before["datasources"])
    after = []
    changed = False
    for ds in datasources:
        planned = _as_desired(ds)
        if live.get(ds["name"]) != planned:
            changed = True
        after.append(planned)

    return changed, {
        "exists": True,
        "scope": before["scope"],
        "datasources": sorted(after, key=lambda d: d["name"]),
    }


def plan_absent(admin, params, before):
    if not before:
        return False, {}
    doomed = [d["name"] for d in params.get("datasources") or []]
    kept = [d for d in before["datasources"] if d["name"] not in doomed]
    after = dict(before)
    after["datasources"] = kept
    return len(kept) != len(before["datasources"]), after


def _resource_properties_arg(properties):
    """-configureResourceProperties: [[name type value] ...]."""
    triples = []
    for key in sorted(properties.keys()):
        triples.append("[%s %s %s]" % (key, _type_of(properties[key]), properties[key]))
    return "[%s]" % " ".join(triples)


def _reconcile(AdminConfig, ds_id, desired):
    """Bring an existing datasource to the declaration, one attribute at a time."""
    attributes = []
    for attribute, key in (("jndiName", "jndi_name"),
                           ("datasourceHelperClassname", "helper"),
                           ("authDataAlias", "auth_alias")):
        if (AdminConfig.showAttribute(ds_id, attribute) or "") != desired[key]:
            attributes.append([attribute, desired[key]])
    if int(AdminConfig.showAttribute(ds_id, "statementCacheSize") or 0) != desired["statement_cache_size"]:
        attributes.append(["statementCacheSize", desired["statement_cache_size"]])
    if attributes:
        AdminConfig.modify(ds_id, attributes)

    pool_id = (AdminConfig.showAttribute(ds_id, "connectionPool") or "").strip()
    pool_changes = []
    for key in sorted(desired["pool"].keys()):
        if int(AdminConfig.showAttribute(pool_id, key) or 0) != desired["pool"][key]:
            pool_changes.append([key, desired["pool"][key]])
    if pool_changes:
        AdminConfig.modify(pool_id, pool_changes)

    props, property_set = _properties(AdminConfig, ds_id)
    for key in sorted(desired["properties"].keys()):
        value = desired["properties"][key]
        if key in props:
            if str(props[key][1]) != value:
                AdminConfig.modify(props[key][0], [["value", value]])
        else:
            AdminConfig.create("J2EEResourceProperty", property_set, [
                ["name", key], ["type", _type_of(value)], ["value", value],
            ])


def write_present(admin, params, before):
    AdminConfig = admin["AdminConfig"]
    AdminTask = admin["AdminTask"]
    scope_id = _scope.find(AdminConfig, params["scope"])
    providers = _providers(AdminConfig, scope_id)
    live = _datasources(AdminConfig, scope_id)

    for ds in params.get("datasources") or []:
        desired = _as_desired(ds)
        if ds["name"] not in live:
            args = [
                "-name", desired["name"],
                "-jndiName", desired["jndi_name"],
                "-dataStoreHelperClassName", desired["helper"],
                "-containerManagedPersistence", "true",
            ]
            if desired["auth_alias"]:
                args += ["-componentManagedAuthenticationAlias", desired["auth_alias"]]
            if desired["properties"]:
                # At creation, because some provider templates refuse a
                # datasource whose required properties are absent.
                args += ["-configureResourceProperties",
                         _resource_properties_arg(desired["properties"])]
            AdminTask.createDatasource(providers[desired["provider"]], args)
            live = _datasources(AdminConfig, scope_id)
        # Then the same reconciliation as an update: the pool, the statement
        # cache and anything createDatasource has no argument for.
        _reconcile(AdminConfig, live[ds["name"]], desired)


def write_absent(admin, params, before):
    AdminConfig = admin["AdminConfig"]
    scope_id = _scope.find(AdminConfig, params["scope"])
    live = _datasources(AdminConfig, scope_id)
    for ds in params.get("datasources") or []:
        if ds["name"] in live:
            AdminConfig.remove(live[ds["name"]])


def sync(admin, params):
    AdminControl = admin["AdminControl"]
    for mbean in AdminControl.queryNames("type=NodeSync,*").splitlines():
        mbean = mbean.strip()
        if mbean:
            AdminControl.invoke(mbean, "sync")
