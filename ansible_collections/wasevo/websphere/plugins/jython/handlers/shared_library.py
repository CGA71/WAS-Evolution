# -*- coding: utf-8 -*-
"""Handler for shared libraries - jars several applications load from one place.

The class path arrives as an explicit, ordered list of jars. The shared model
says `dir` + `includes: "*.jar"`, which Liberty reads as a fileset and rescans
at start; WAS traditional has no wildcard in a library class path, so the role
expands the pattern on the deployment manager and hands over the exact list.
A jar added to the directory then shows up here as a difference on the next
run - which is how Liberty behaves too, one restart later.

THE CLASS PATH IS A LIST, like a JDBC provider's: AdminConfig.modify would
append to it, so a changed class path is unset first, then written.

Associating a library with an application or a server class loader is not
done here: that belongs to the application deployment, which comes last.

Five callables, same contract as every other handler - see cluster.py.
"""

import _scope


def _normalise(value):
    if value is None:
        return []
    value = str(value).strip()
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1]
    return [part for part in value.replace(";", " ").split() if part]


def _live(AdminConfig, scope_id):
    found = {}
    for config_id in AdminConfig.list("Library", scope_id).splitlines():
        config_id = config_id.strip()
        if not config_id:
            continue
        found[AdminConfig.showAttribute(config_id, "name")] = {
            "config_id": config_id,
            "class_path": _normalise(AdminConfig.showAttribute(config_id, "classPath")),
            "native_path": _normalise(AdminConfig.showAttribute(config_id, "nativePath")),
            "description": AdminConfig.showAttribute(config_id, "description") or "",
            "isolated": str(AdminConfig.showAttribute(config_id, "isolatedClassLoader")).lower() == "true",
        }
    return found


def _public(name, entry):
    return {
        "name": name,
        "class_path": entry["class_path"],
        "native_path": entry["native_path"],
        "description": entry["description"],
        "isolated": entry["isolated"],
    }


def _desired(library):
    return {
        "name": library["name"],
        "class_path": list(library.get("class_path") or []),
        "native_path": list(library.get("native_path") or []),
        "description": library.get("description", "") or "",
        "isolated": bool(library.get("isolated", False)),
    }


def read(admin, params):
    scope_id = _scope.find(admin["AdminConfig"], params["scope"])
    if not scope_id:
        return {}
    live = _live(admin["AdminConfig"], scope_id)
    wanted = [lib["name"] for lib in params.get("libraries") or []]
    return {
        "exists": True,
        "scope": _scope.describe(params["scope"]),
        "libraries": sorted(
            [_public(n, live[n]) for n in wanted if n in live],
            key=lambda lib: lib["name"],
        ),
    }


def plan_present(admin, params, before):
    libraries = params.get("libraries") or []

    if not before:
        if not admin.get("check_mode"):
            raise ValueError(
                "%s does not exist in this cell, so no shared library can be "
                "created there." % _scope.describe(params["scope"])
            )
        return True, {
            "exists": False,
            "scope": _scope.describe(params["scope"]),
            "scope_pending": True,
            "libraries": sorted([_desired(lib) for lib in libraries], key=lambda lib: lib["name"]),
        }

    live = dict((lib["name"], lib) for lib in before["libraries"])
    after = []
    changed = False
    for library in libraries:
        planned = _desired(library)
        if live.get(library["name"]) != planned:
            changed = True
        after.append(planned)

    return changed, {
        "exists": True,
        "scope": before["scope"],
        "libraries": sorted(after, key=lambda lib: lib["name"]),
    }


def plan_absent(admin, params, before):
    if not before:
        return False, {}
    doomed = [lib["name"] for lib in params.get("libraries") or []]
    kept = [lib for lib in before["libraries"] if lib["name"] not in doomed]
    after = dict(before)
    after["libraries"] = kept
    return len(kept) != len(before["libraries"]), after


def write_present(admin, params, before):
    AdminConfig = admin["AdminConfig"]
    scope_id = _scope.find(AdminConfig, params["scope"])
    live = _live(AdminConfig, scope_id)

    for library in params.get("libraries") or []:
        planned = _desired(library)
        current = live.get(library["name"])

        if current is None:
            attributes = [
                ["name", planned["name"]],
                ["description", planned["description"]],
                ["isolatedClassLoader", planned["isolated"] and "true" or "false"],
            ]
            if planned["class_path"]:
                attributes.append(["classPath", ";".join(planned["class_path"])])
            if planned["native_path"]:
                attributes.append(["nativePath", ";".join(planned["native_path"])])
            AdminConfig.create("Library", scope_id, attributes)
            continue

        config_id = current["config_id"]
        for attribute, key in (("classPath", "class_path"), ("nativePath", "native_path")):
            if current[key] != planned[key]:
                # Unset first: modify on a list attribute appends.
                AdminConfig.unsetAttributes(config_id, [attribute])
                if planned[key]:
                    AdminConfig.modify(config_id, [[attribute, ";".join(planned[key])]])
        changes = []
        if current["description"] != planned["description"]:
            changes.append(["description", planned["description"]])
        if current["isolated"] != planned["isolated"]:
            changes.append(["isolatedClassLoader", planned["isolated"] and "true" or "false"])
        if changes:
            AdminConfig.modify(config_id, changes)


def write_absent(admin, params, before):
    AdminConfig = admin["AdminConfig"]
    scope_id = _scope.find(AdminConfig, params["scope"])
    live = _live(AdminConfig, scope_id)
    for library in params.get("libraries") or []:
        current = live.get(library["name"])
        if current is not None:
            AdminConfig.remove(current["config_id"])


def sync(admin, params):
    AdminControl = admin["AdminControl"]
    for mbean in AdminControl.queryNames("type=NodeSync,*").splitlines():
        mbean = mbean.strip()
        if mbean:
            AdminControl.invoke(mbean, "sync")
