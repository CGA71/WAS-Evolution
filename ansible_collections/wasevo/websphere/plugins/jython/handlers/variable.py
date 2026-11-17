# -*- coding: utf-8 -*-
"""Handler for WebSphere variables - the ${NAME} substitutions of a scope.

A variable lives in the VariableMap of its scope (variables.xml) as a
VariableSubstitutionEntry: symbolicName, value, description. An application
declares the ones it reads - a home directory, a URL, a switch - and they are
created before it is installed and removed when it is decommissioned.

Every variable of a scope in one call, so one wsadmin session serves them all.
A scope that has no VariableMap yet gets one: a fresh cluster has none until
something is written to it.

Five callables, same contract as every other handler - see cluster.py.
"""

import _scope


def _map_id(AdminConfig, scope_id, create=False):
    for config_id in AdminConfig.list("VariableMap", scope_id).splitlines():
        config_id = config_id.strip()
        if config_id:
            return config_id
    if create:
        return AdminConfig.create("VariableMap", scope_id, [])
    return ""


def _live(AdminConfig, map_id):
    found = {}
    if not map_id:
        return found
    for config_id in AdminConfig.list("VariableSubstitutionEntry", map_id).splitlines():
        config_id = config_id.strip()
        if not config_id:
            continue
        found[AdminConfig.showAttribute(config_id, "symbolicName")] = {
            "config_id": config_id,
            "value": AdminConfig.showAttribute(config_id, "value") or "",
            "description": AdminConfig.showAttribute(config_id, "description") or "",
        }
    return found


def _desired(variable):
    return {
        "name": variable["name"],
        "value": str(variable.get("value", "") or ""),
        "description": variable.get("description", "") or "",
    }


def read(admin, params):
    AdminConfig = admin["AdminConfig"]
    scope_id = _scope.find(AdminConfig, params["scope"])
    if not scope_id:
        return {}
    live = _live(AdminConfig, _map_id(AdminConfig, scope_id))
    wanted = [v["name"] for v in params.get("variables") or []]
    variables = []
    for name in wanted:
        if name in live:
            variables.append({"name": name, "value": live[name]["value"],
                              "description": live[name]["description"]})
    variables.sort(key=lambda v: v["name"])
    return {"exists": True, "scope": _scope.describe(params["scope"]), "variables": variables}


def plan_present(admin, params, before):
    variables = params.get("variables") or []
    planned = sorted([_desired(v) for v in variables], key=lambda v: v["name"])

    if not before:
        if not admin.get("check_mode"):
            raise ValueError(
                "%s does not exist in this cell, so no variable can be created "
                "there." % _scope.describe(params["scope"])
            )
        return True, {"exists": False, "scope": _scope.describe(params["scope"]),
                      "scope_pending": True, "variables": planned}

    live = dict((v["name"], v) for v in before["variables"])
    changed = False
    for variable in planned:
        if live.get(variable["name"]) != variable:
            changed = True
    return changed, {"exists": True, "scope": before["scope"], "variables": planned}


def plan_absent(admin, params, before):
    if not before:
        return False, {}
    doomed = [v["name"] for v in params.get("variables") or []]
    kept = [v for v in before["variables"] if v["name"] not in doomed]
    after = dict(before)
    after["variables"] = kept
    return len(kept) != len(before["variables"]), after


def write_present(admin, params, before):
    AdminConfig = admin["AdminConfig"]
    scope_id = _scope.find(AdminConfig, params["scope"])
    map_id = _map_id(AdminConfig, scope_id, create=True)
    live = _live(AdminConfig, map_id)
    for variable in params.get("variables") or []:
        planned = _desired(variable)
        current = live.get(planned["name"])
        if current is None:
            AdminConfig.create("VariableSubstitutionEntry", map_id, [
                ["symbolicName", planned["name"]],
                ["value", planned["value"]],
                ["description", planned["description"]],
            ])
            continue
        changes = []
        if current["value"] != planned["value"]:
            changes.append(["value", planned["value"]])
        if current["description"] != planned["description"]:
            changes.append(["description", planned["description"]])
        if changes:
            AdminConfig.modify(current["config_id"], changes)


def write_absent(admin, params, before):
    AdminConfig = admin["AdminConfig"]
    scope_id = _scope.find(AdminConfig, params["scope"])
    live = _live(AdminConfig, _map_id(AdminConfig, scope_id))
    for variable in params.get("variables") or []:
        current = live.get(variable["name"])
        if current is not None:
            AdminConfig.remove(current["config_id"])


def sync(admin, params):
    AdminControl = admin["AdminControl"]
    for mbean in AdminControl.queryNames("type=NodeSync,*").splitlines():
        mbean = mbean.strip()
        if mbean:
            AdminControl.invoke(mbean, "sync")
