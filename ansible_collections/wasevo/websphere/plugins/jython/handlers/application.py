# -*- coding: utf-8 -*-
"""Handler for an application - an EAR, a WAR or an EJB JAR - on a cluster or
on one application server.

WHAT "PRESENT" MEANS. The application is installed, mapped to the declared
target, bound to the declared shared libraries, and - after the nodes have
synchronised - started on every member that is running.

UPDATE IS UNINSTALL THEN INSTALL. The site chose it over AdminApp.update: it
is simpler to reason about and leaves no console-made setting behind. So an
installed application is reinstalled when the caller says the archive changed
(params["reinstall"], decided by the role from the archive's checksum), or when
the declared target is not the one it is mapped to. A difference in shared
libraries alone is an edit, not a reinstall.

Read through AdminApp.view, not through the deployment.xml objects: the
targets and the library bindings are what AdminApp itself reports, which is
also what an operator sees with the same command.

Five callables, same contract as every other handler - see cluster.py.
"""

import time

import _scope


# --------------------------------------------------------------------------
# What the cell says
# --------------------------------------------------------------------------

def _installed(AdminApp):
    return [a.strip() for a in AdminApp.list().splitlines() if a.strip()]


def _view(AdminApp, name, task):
    """AdminApp.view for one task, or "" when the application has no such task
    (a WAR has no EJB bindings, an EJB JAR no web module)."""
    try:
        return AdminApp.view(name, [task]) or ""
    except Exception:
        return ""


def _fields(text, wanted):
    """The values of the "Label:  value" lines whose label matches."""
    values = []
    for line in text.splitlines():
        if ":" not in line:
            continue
        label, value = line.split(":", 1)
        if wanted(label.strip().lower()) and value.strip():
            values.append(value.strip())
    return values


def _canonical(target):
    """One spelling for a target, from a scope dict or from a mapping string.

    "WebSphere:cell=C,cluster=X"            -> "cluster=X"
    "WebSphere:cell=C,node=N,server=S"      -> "node=N,server=S"
    {"type": "cluster", "cluster": "X"}     -> "cluster=X"
    """
    if isinstance(target, type({})):
        if target.get("type") == "cluster":
            return "cluster=%s" % target["cluster"]
        if target.get("type") == "server":
            return "node=%s,server=%s" % (target["node"], target["server"])
        raise ValueError("an application target is a cluster or a server, got %r" % (target,))
    pairs = {}
    text = str(target)
    if text.startswith("WebSphere:"):
        text = text[len("WebSphere:"):]
    for part in text.split(","):
        if "=" in part:
            key, value = part.split("=", 1)
            pairs[key.strip()] = value.strip()
    if "cluster" in pairs:
        return "cluster=%s" % pairs["cluster"]
    if "server" in pairs:
        return "node=%s,server=%s" % (pairs.get("node", ""), pairs["server"])
    return text


def _targets(AdminApp, name):
    found = []
    for value in _fields(_view(AdminApp, name, "-MapModulesToServers"),
                         lambda label: label == "server"):
        for one in value.split("+"):
            one = _canonical(one.strip())
            # The web server a module is also mapped to, for the plug-in, is
            # not where the application runs.
            if one and one not in found and "webserver" not in one.lower():
                found.append(one)
    found.sort()
    return found


def _libraries(AdminApp, name):
    found = []
    for value in _fields(_view(AdminApp, name, "-MapSharedLibForMod"),
                         lambda label: label.startswith("shared lib")):
        for one in value.replace(",", "+").split("+"):
            one = one.strip()
            if one and one not in found:
                found.append(one)
    found.sort()
    return found


def read(admin, params):
    AdminApp = admin["AdminApp"]
    name = params["name"]
    if name not in _installed(AdminApp):
        return {}
    return {
        "installed": True,
        "name": name,
        "targets": _targets(AdminApp, name),
        "shared_libraries": _libraries(AdminApp, name),
    }


# --------------------------------------------------------------------------
# What is asked
# --------------------------------------------------------------------------

def _desired(params):
    libraries = list(params.get("shared_libraries") or [])
    libraries.sort()
    return {
        "installed": True,
        "name": params["name"],
        "targets": [_canonical(params["target"])],
        "shared_libraries": libraries,
        "archive": params["archive"],
    }


def _target_exists(AdminConfig, target):
    if target.get("type") == "cluster":
        return bool(_scope.find(AdminConfig, {"type": "cluster", "cluster": target["cluster"]}))
    return True


def plan_present(admin, params, before):
    after = _desired(params)
    if not _target_exists(admin["AdminConfig"], params["target"]):
        if not admin.get("check_mode"):
            raise ValueError(
                "cluster %s does not exist in this cell, so %s cannot be installed "
                "on it. The cluster job creates it." % (params["target"]["cluster"], params["name"])
            )
        after["target_pending"] = True
        return True, after

    if not before:
        after["action"] = "install"
        return True, after

    if params.get("reinstall"):
        after["action"] = "reinstall: the archive changed"
        return True, after
    if before["targets"] != after["targets"]:
        after["action"] = "reinstall: mapped to %s, declared on %s" % (
            ", ".join(before["targets"]) or "nothing", ", ".join(after["targets"]))
        return True, after
    if before["shared_libraries"] != after["shared_libraries"]:
        after["action"] = "shared libraries rebound"
        return True, after

    after["action"] = "none"
    del after["archive"]
    return False, before


def plan_absent(admin, params, before):
    if not before:
        return False, {}
    return True, {"installed": False, "name": params["name"], "action": "uninstall"}


# --------------------------------------------------------------------------
# Writes
# --------------------------------------------------------------------------

def _install_options(params):
    name = params["name"]
    target = params["target"]
    options = ["-appname", name]
    if target["type"] == "cluster":
        options.extend(["-cluster", target["cluster"]])
    else:
        options.extend(["-node", target["node"], "-server", target["server"]])
    if params.get("context_root"):
        options.extend(["-contextroot", params["context_root"]])
    if params.get("map_web_modules", True):
        options.extend(["-MapWebModToVH", [[".*", ".*", params.get("virtual_host") or "default_host"]]])
    libraries = params.get("shared_libraries") or []
    if libraries:
        options.extend(["-MapSharedLibForMod", [[".*", ".*", "+".join(libraries)]]])
    for extra in params.get("install_options") or []:
        options.append(extra)
    return options


def _servers(AdminConfig, target):
    """(node, server) of every JVM the application runs in."""
    if target["type"] == "server":
        return [(target["node"], target["server"])]
    cluster_id = _scope.find(AdminConfig, {"type": "cluster", "cluster": target["cluster"]})
    if not cluster_id:
        return []
    members = AdminConfig.showAttribute(cluster_id, "members") or ""
    members = members.strip()
    if members.startswith("[") and members.endswith("]"):
        members = members[1:-1]
    found = []
    for member_id in members.split():
        found.append((AdminConfig.showAttribute(member_id, "nodeName"),
                      AdminConfig.showAttribute(member_id, "memberName")))
    return found


def _application_manager(AdminControl, node, server):
    query = "type=ApplicationManager,node=%s,process=%s,*" % (node, server)
    names = [n.strip() for n in (AdminControl.queryNames(query) or "").splitlines() if n.strip()]
    # An empty answer is a stopped server: nothing to start or stop there, and
    # the application starts with it next time.
    if names:
        return names[0]
    return ""


def _each_running(admin, target, operation, name):
    done = []
    for node, server in _servers(admin["AdminConfig"], target):
        mbean = _application_manager(admin["AdminControl"], node, server)
        if not mbean:
            continue
        try:
            admin["AdminControl"].invoke(mbean, operation, name)
            done.append("%s/%s" % (node, server))
        except Exception:
            # Stopping an application that is already stopped raises; so does
            # starting one that runs. Neither is a failure of this call.
            pass
    return done


def _uninstall(admin, name, target):
    _each_running(admin, target, "stopApplication", name)
    admin["AdminApp"].uninstall(name)


def write_present(admin, params, before):
    AdminApp = admin["AdminApp"]
    AdminConfig = admin["AdminConfig"]
    name = params["name"]
    desired = _desired(params)

    if before:
        reinstall = params.get("reinstall") or before["targets"] != desired["targets"]
        if not reinstall:
            libraries = params.get("shared_libraries") or []
            AdminApp.edit(name, ["-MapSharedLibForMod", [[".*", ".*", "+".join(libraries)]]])
            return
        # Stopped where it ran, on the target it was MAPPED to - which is the
        # declared one unless the target is what changed.
        old = params["target"]
        if before["targets"] and before["targets"][0].startswith("cluster="):
            old = {"type": "cluster", "cluster": before["targets"][0][len("cluster="):]}
        _uninstall(admin, name, old)
        # Saved between the two, so the install does not meet the name of an
        # application whose removal is still only in this session's workspace.
        AdminConfig.save()

    AdminApp.install(params["archive"], _install_options(params))


def write_absent(admin, params, before):
    target = params.get("target") or {}
    if not target and before.get("targets"):
        first = before["targets"][0]
        if first.startswith("cluster="):
            target = {"type": "cluster", "cluster": first[len("cluster="):]}
    if not target:
        target = {"type": "server", "node": "", "server": ""}
    _uninstall(admin, params["name"], target)


def sync(admin, params):
    """Synchronise the nodes, then - for an installed application - wait until
    every node has it and start it where its servers run."""
    AdminControl = admin["AdminControl"]
    for mbean in AdminControl.queryNames("type=NodeSync,*").splitlines():
        mbean = mbean.strip()
        if mbean:
            AdminControl.invoke(mbean, "sync")

    name = params["name"]
    if name not in _installed(admin["AdminApp"]) or not params.get("start", True):
        return

    deadline = time.time() + int(params.get("ready_timeout", 300))
    while str(admin["AdminApp"].isAppReady(name)).lower() != "true":
        if time.time() > deadline:
            raise ValueError(
                "%s is installed but the nodes have not finished expanding it after "
                "%s s - it was not started. Start it once AdminApp.isAppReady says "
                "true, or raise ready_timeout." % (name, params.get("ready_timeout", 300))
            )
        time.sleep(5)
    _each_running(admin, params["target"], "startApplication", name)
