# -*- coding: utf-8 -*-
"""Handler for JDBC providers - the driver a datasource is built on.

One provider per scope and name. The provider type, database type and
implementation type come from roles/model/vars/jdbc_vendors.yml, rendered by
the role from the datasource's abstract `vendor`; this handler only checks
them against what the cell offers.

ASKING THE CELL, NOT TRUSTING THE TABLE. Before a provider is created, the
cell's own JDBC provider templates are listed and the requested provider type
must match one. A provider type the cell does not know makes createJDBCProvider
fail with an exception that names neither the type nor the alternatives; here
it is refused with the list of what the cell does offer, so a wrong entry in
the vendor table shows up on its first real run as a sentence.

THE CLASSPATH IS A LIST. AdminConfig.modify APPENDS to a list attribute rather
than replacing it, so a changed classpath set with a plain modify would leave
the old jar in front of the new one - and the old driver would win. The
attribute is unset first, then written.

Five callables, same contract as every other handler - see cluster.py.
"""

import _scope


def _normalise(value):
    """A classpath or native path as one ';'-joined string, whatever its form."""
    if value is None:
        return ""
    value = str(value).strip()
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1]
    parts = []
    for chunk in value.replace(";", " ").split():
        if chunk:
            parts.append(chunk)
    return ";".join(parts)


def _live(AdminConfig, scope_id):
    found = {}
    for config_id in AdminConfig.list("JDBCProvider", scope_id).splitlines():
        config_id = config_id.strip()
        if not config_id:
            continue
        found[AdminConfig.showAttribute(config_id, "name")] = {
            "config_id": config_id,
            "classpath": _normalise(AdminConfig.showAttribute(config_id, "classpath")),
            "native_path": _normalise(AdminConfig.showAttribute(config_id, "nativepath")),
            "description": AdminConfig.showAttribute(config_id, "description") or "",
        }
    return found


def _public(name, entry):
    return {
        "name": name,
        "classpath": entry["classpath"],
        "native_path": entry["native_path"],
        "description": entry["description"],
    }


def _desired(provider):
    return {
        "name": provider["name"],
        "classpath": _normalise(provider.get("classpath")),
        "native_path": _normalise(provider.get("native_path")),
        "description": provider.get("description", "") or "",
    }


def _templates(AdminConfig):
    """The provider template names the cell offers."""
    names = []
    for template in AdminConfig.listTemplates("JDBCProvider").splitlines():
        template = template.strip()
        if template:
            names.append(template.split("(templates/")[0].strip())
    return names


def _check_template(AdminConfig, provider):
    wanted = provider["provider_type"]
    offered = _templates(AdminConfig)
    for name in offered:
        if name == wanted or name.startswith(wanted):
            return
    raise ValueError(
        "provider type %r is not offered by this cell, so provider %s cannot "
        "be created. The cell offers: %s. Correct the entry in "
        "roles/model/vars/jdbc_vendors.yml, or name a provider_type explicitly."
        % (wanted, provider["name"], ", ".join(sorted(set(offered))) or "(nothing)")
    )


def read(admin, params):
    scope_id = _scope.find(admin["AdminConfig"], params["scope"])
    if not scope_id:
        return {}
    live = _live(admin["AdminConfig"], scope_id)
    wanted = [p["name"] for p in params.get("providers") or []]
    return {
        "exists": True,
        "scope": _scope.describe(params["scope"]),
        "providers": sorted(
            [_public(n, live[n]) for n in wanted if n in live],
            key=lambda p: p["name"],
        ),
    }


def plan_present(admin, params, before):
    providers = params.get("providers") or []

    if not before:
        # Same reasoning as the cluster members: in a check run the scope is a
        # future, created by an earlier step of the same run; in a real run it
        # is an absence, and the refusal says which step creates it.
        if not admin.get("check_mode"):
            raise ValueError(
                "%s does not exist in this cell, so no JDBC provider can be "
                "created there. Create it first - the cluster job, or the "
                "profile job for a node or a server."
                % _scope.describe(params["scope"])
            )
        for provider in providers:
            _check_template(admin["AdminConfig"], provider)
        return True, {
            "exists": False,
            "scope": _scope.describe(params["scope"]),
            "scope_pending": True,
            "providers": sorted([_desired(p) for p in providers], key=lambda p: p["name"]),
        }

    live = dict((p["name"], p) for p in before["providers"])
    after = []
    changed = False
    for provider in providers:
        planned = _desired(provider)
        current = live.get(provider["name"])
        if current is None:
            _check_template(admin["AdminConfig"], provider)
            changed = True
        elif current != planned:
            changed = True
        after.append(planned)

    return changed, {
        "exists": True,
        "scope": before["scope"],
        "providers": sorted(after, key=lambda p: p["name"]),
    }


def plan_absent(admin, params, before):
    if not before:
        return False, {}
    doomed = [p["name"] for p in params.get("providers") or []]
    kept = [p for p in before["providers"] if p["name"] not in doomed]
    after = dict(before)
    after["providers"] = kept
    return len(kept) != len(before["providers"]), after


def write_present(admin, params, before):
    AdminConfig = admin["AdminConfig"]
    AdminTask = admin["AdminTask"]
    scope_id = _scope.find(AdminConfig, params["scope"])
    live = _live(AdminConfig, scope_id)

    for provider in params.get("providers") or []:
        planned = _desired(provider)
        current = live.get(provider["name"])

        if current is None:
            args = [
                "-scope", _scope.admintask_arg(params["scope"]),
                "-databaseType", provider["database_type"],
                "-providerType", provider["provider_type"],
                "-implementationType", provider["implementation_type"],
                "-name", provider["name"],
                "-description", planned["description"],
            ]
            if planned["classpath"]:
                args += ["-classpath", planned["classpath"]]
            if planned["native_path"]:
                args += ["-nativePath", planned["native_path"]]
            AdminTask.createJDBCProvider(args)
            continue

        config_id = current["config_id"]
        for attribute, key in (("classpath", "classpath"), ("nativepath", "native_path")):
            if _normalise(current[key]) != planned[key]:
                # Unset first: modify on a list attribute appends, and the old
                # jar would stay ahead of the new one on the classpath.
                AdminConfig.unsetAttributes(config_id, [attribute])
                if planned[key]:
                    AdminConfig.modify(config_id, [[attribute, planned[key]]])
        if current["description"] != planned["description"]:
            AdminConfig.modify(config_id, [["description", planned["description"]]])


def write_absent(admin, params, before):
    # Removing a provider removes the datasources built on it. The role
    # removes datasources first anyway, so this is the backstop, not the plan.
    AdminConfig = admin["AdminConfig"]
    scope_id = _scope.find(AdminConfig, params["scope"])
    live = _live(AdminConfig, scope_id)
    for provider in params.get("providers") or []:
        current = live.get(provider["name"])
        if current is not None:
            AdminConfig.remove(current["config_id"])


def sync(admin, params):
    AdminControl = admin["AdminControl"]
    for mbean in AdminControl.queryNames("type=NodeSync,*").splitlines():
        mbean = mbean.strip()
        if mbean:
            AdminControl.invoke(mbean, "sync")
