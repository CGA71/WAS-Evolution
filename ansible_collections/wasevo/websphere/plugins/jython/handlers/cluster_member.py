# -*- coding: utf-8 -*-
"""Handler for the application servers that are members of a cluster.

A cluster member IS an application server: the same object, owned by the cell
and created on a federated node. manageprofiles never creates one -- the
managed template gives a node agent and nothing else -- so this handler is
what turns a federated node into a node that runs an application.

VERTICAL AND HORIZONTAL ARE THE SAME CALL. Several members on one node is
vertical, one member on each of several nodes is horizontal, and both at once
is the usual real shape. Neither is a mode of this handler: the caller hands
over the list of (node, name) pairs it wants and the handler makes the cell
match. The distinction lives in how that list was composed, which is
roles/model's business, not wsadmin's.

ONE SESSION FOR THE WHOLE CLUSTER. The members arrive as a list rather than
one per call, because a wsadmin JVM start costs 30 to 60 seconds: eight
members built one call at a time is eight starts and six minutes of JVM
warm-up for a few seconds of work.

The first member of a cluster is a special case in the WAS API, not here:
``createClusterMember`` requires ``-firstMember`` exactly once, when the
cluster has no members yet, because that call is what fixes the server
template every later member is copied from. The handler knows which member is
the first from what it read, so the caller never has to.

Five callables, same contract as every other handler -- see cluster.py.
"""


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

def _cluster_id(AdminConfig, name):
    """Config id of the named cluster, or "" when the cell has no such cluster."""
    for candidate in AdminConfig.list("ServerCluster").splitlines():
        candidate = candidate.strip()
        if not candidate:
            continue
        if AdminConfig.showAttribute(candidate, "name") == name:
            return candidate
    return ""


def _declared_ports(params):
    """Endpoint names any desired member pins, keyed by (node, name).

    Only what the caller declared is ever read back. A run that pins no port
    reads no serverindex, so the cost of honest port drift detection is paid
    only by the runs that asked for it.
    """
    wanted = {}
    for member in params.get("members") or []:
        ports = member.get("ports") or {}
        if ports:
            wanted[(member["node"], member["name"])] = ports
    return wanted


def _read_ports(admin, node, server, endpoints):
    """Live port of each named endpoint of one server, from its node serverindex."""
    AdminConfig = admin["AdminConfig"]
    found = {}

    index_id = AdminConfig.getid("/Node:%s/ServerIndex:/" % node)
    if not index_id:
        return found
    index_id = index_id.strip().splitlines()[0].strip()

    entries = AdminConfig.showAttribute(index_id, "serverEntries") or ""
    for entry in entries.strip("[]").split():
        entry = entry.strip()
        if not entry:
            continue
        if AdminConfig.showAttribute(entry, "serverName") != server:
            continue
        specials = AdminConfig.showAttribute(entry, "specialEndpoints") or ""
        for special in specials.strip("[]").split():
            special = special.strip()
            if not special:
                continue
            name = AdminConfig.showAttribute(special, "endPointName")
            if name not in endpoints:
                continue
            end_point = AdminConfig.showAttribute(special, "endPoint")
            if not end_point:
                continue
            end_point = end_point.strip().splitlines()[0].strip()
            found[name] = int(AdminConfig.showAttribute(end_point, "port"))
    return found


def read(admin, params):
    """The cluster and the members it holds, or {} when the cluster is absent.

    An absent cluster is reported rather than raised on, because the driver
    hands this dict to plan_present and that is where the refusal belongs: a
    check run has to be able to say "the cluster is missing" instead of
    failing the way a real run would.
    """
    AdminConfig = admin["AdminConfig"]

    cluster_id = _cluster_id(AdminConfig, params["cluster_name"])
    if not cluster_id:
        return {}

    wanted_ports = _declared_ports(params)

    members = []
    member_ids = AdminConfig.showAttribute(cluster_id, "members")
    if member_ids:
        for member in member_ids.strip("[]").split():
            member = member.strip()
            if not member:
                continue
            name = AdminConfig.showAttribute(member, "memberName")
            node = AdminConfig.showAttribute(member, "nodeName")
            current = {
                "name": name,
                "node": node,
                "weight": int(AdminConfig.showAttribute(member, "weight") or 2),
            }
            endpoints = wanted_ports.get((node, name))
            if endpoints:
                current["ports"] = _read_ports(admin, node, name, endpoints)
            members.append(current)

    return {
        "exists": True,
        "cluster": params["cluster_name"],
        "config_id": cluster_id,
        "members": members,
    }


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------

def _by_key(members):
    return dict(((m["node"], m["name"]), m) for m in members)


def _sorted(members):
    return sorted(members, key=lambda m: (m["node"], m["name"]))


def _detached(member):
    """A copy of a member that shares no dict with the one it came from.

    dict(member) alone is a shallow copy: the "ports" value would still be the
    very dict held by `before`, so planning a port change would write it into
    the state we are comparing against. write_present would then see the port
    it is supposed to set already set, skip the call, and the diff would show
    a change that never happened. The planner must not be able to touch what
    it was given.
    """
    copy = dict(member)
    if member.get("ports"):
        copy["ports"] = dict(member["ports"])
    return copy


def plan_present(admin, params, before):
    """What the cell is missing, computed without touching it."""
    if not before:
        # In a check run the cluster is a FUTURE, not an absence: the step
        # before this one in the same run is what creates it, and under
        # --check that step wrote nothing. Refusing here would make a dry run
        # of a first build impossible - which is the one run you most want to
        # rehearse. So the plan reports every member as new, and says the
        # cluster is not there yet.
        if admin.get("check_mode"):
            return True, {
                "exists": False,
                "cluster": params["cluster_name"],
                "cluster_pending": True,
                "members": _sorted([
                    _detached({
                        "name": member["name"],
                        "node": member["node"],
                        "weight": int(member.get("weight", 2)),
                        "ports": dict(
                            (endpoint, int(port))
                            for endpoint, port in (member.get("ports") or {}).items()
                        ),
                    })
                    for member in params.get("members") or []
                ]),
            }
        raise ValueError(
            "cluster %s does not exist in this cell, so it cannot be given "
            "members. Declare the cluster first - was_cluster, state present - "
            "in this run or an earlier one." % params["cluster_name"]
        )

    live = _by_key(before["members"])
    after = []
    changed = False

    for desired in params.get("members") or []:
        key = (desired["node"], desired["name"])
        current = live.get(key)

        if current is None:
            planned = {
                "name": desired["name"],
                "node": desired["node"],
                "weight": int(desired.get("weight", 2)),
            }
            if desired.get("ports"):
                planned["ports"] = dict(
                    (endpoint, int(port))
                    for endpoint, port in desired["ports"].items()
                )
            after.append(planned)
            changed = True
            continue

        planned = _detached(current)

        if int(desired.get("weight", current["weight"])) != int(current["weight"]):
            planned["weight"] = int(desired["weight"])
            changed = True

        for endpoint, port in (desired.get("ports") or {}).items():
            if int((current.get("ports") or {}).get(endpoint, -1)) != int(port):
                planned.setdefault("ports", {})[endpoint] = int(port)
                changed = True

        after.append(planned)

    # Members the cell holds and the request did not name are left alone.
    # Removing them is `state: absent` on an explicit list, never a side
    # effect of not naming them: a run limited to one node must not delete
    # the members of every other node.
    desired_keys = _by_key(after).keys()
    for key, current in live.items():
        if key not in desired_keys:
            after.append(_detached(current))

    return changed, {
        "exists": True,
        "cluster": before["cluster"],
        "config_id": before["config_id"],
        "members": _sorted(after),
    }


def plan_absent(admin, params, before):
    """Only the members actually named are removed."""
    if not before:
        return False, {}

    doomed = _by_key(params.get("members") or []).keys()
    kept = [_detached(m) for m in before["members"]
            if (m["node"], m["name"]) not in doomed]
    changed = len(kept) != len(before["members"])

    after = dict(before)
    after["members"] = _sorted(kept)
    return changed, after


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

def _member_config(member):
    """The -memberConfig step.

    genUniquePorts is what keeps two JVMs on one node from claiming the same
    WC_defaulthost, SOAP and ORB ports -- the failure mode of a vertical
    cluster, and one that only shows up when the second member is started.
    Pinned ports are applied afterwards with modifyServerPort, because
    createClusterMember has no argument for them.
    """
    return (
        "[-memberNode %s -memberName %s -memberWeight %d "
        "-genUniquePorts %s -replicatorEntry false]" % (
            member["node"],
            member["name"],
            int(member.get("weight", 2)),
            "true" if member.get("gen_unique_ports", True) else "false",
        )
    )


def _first_member(params):
    """The -firstMember step, valid exactly once per cluster.

    This is the call that fixes the server template every later member is
    copied from, which is why the API requires it and why it cannot be
    replayed.
    """
    step = "-templateName %s" % params.get("template_name", "default")
    if params.get("template_server_node") and params.get("template_server_name"):
        step += " -templateServerNode %s -templateServerName %s" % (
            params["template_server_node"],
            params["template_server_name"],
        )
    if params.get("node_group"):
        step += " -nodeGroup %s" % params["node_group"]
    if params.get("core_group"):
        step += " -coreGroup %s" % params["core_group"]
    return "[%s]" % step


def write_present(admin, params, before):
    AdminTask = admin["AdminTask"]
    AdminConfig = admin["AdminConfig"]

    live = _by_key(before["members"])
    # Whether the cluster is still empty is tracked as we go: the second
    # member of a brand new cluster must NOT carry -firstMember.
    empty = not before["members"]

    for desired in params.get("members") or []:
        key = (desired["node"], desired["name"])
        current = live.get(key)

        if current is None:
            args = [
                "-clusterName", params["cluster_name"],
                "-memberConfig", _member_config(desired),
            ]
            if empty:
                args.extend(["-firstMember", _first_member(params)])
                empty = False
            AdminTask.createClusterMember(args)

        elif int(desired.get("weight", current["weight"])) != int(current["weight"]):
            AdminConfig.modify(
                _member_id(AdminConfig, before["config_id"], desired),
                [["weight", int(desired["weight"])]],
            )

        for endpoint, port in (desired.get("ports") or {}).items():
            live_port = ((current or {}).get("ports") or {}).get(endpoint)
            if live_port is not None and int(live_port) == int(port):
                continue
            AdminTask.modifyServerPort([
                desired["name"],
                "-nodeName", desired["node"],
                "-endPointName", endpoint,
                "-host", "*",
                "-port", str(int(port)),
            ])


def _member_id(AdminConfig, cluster_id, member):
    """Config id of one existing ClusterMember."""
    members = AdminConfig.showAttribute(cluster_id, "members") or ""
    for candidate in members.strip("[]").split():
        candidate = candidate.strip()
        if not candidate:
            continue
        if (AdminConfig.showAttribute(candidate, "memberName") == member["name"]
                and AdminConfig.showAttribute(candidate, "nodeName") == member["node"]):
            return candidate
    raise ValueError(
        "member %s on node %s vanished between the read and the write"
        % (member["name"], member["node"])
    )


def write_absent(admin, params, before):
    # Deleting a cluster member deletes the application server. The legacy
    # repository left this out, like 29 other deletions, which is why
    # decommissioning was a console exercise.
    AdminTask = admin["AdminTask"]
    live = _by_key(before["members"])

    for member in params.get("members") or []:
        if (member["node"], member["name"]) not in live:
            continue
        AdminTask.deleteClusterMember([
            "-clusterName", params["cluster_name"],
            "-memberNode", member["node"],
            "-memberName", member["name"],
        ])


def sync(admin, params):
    """Push the saved configuration to the nodes.

    A member exists in the master repository as soon as it is saved, and on
    the node only after a sync. Without this the node agent is asked to start
    a server it has never heard of.
    """
    AdminControl = admin["AdminControl"]
    for mbean in AdminControl.queryNames("type=NodeSync,*").splitlines():
        mbean = mbean.strip()
        if mbean:
            AdminControl.invoke(mbean, "sync")
