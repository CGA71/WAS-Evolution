# -*- coding: utf-8 -*-
"""Handler for WAS server clusters.

The read / plan / write split is what makes idempotency real. The legacy code
needed two wsadmin JVM starts for this -- clusterExist.py printing RC_0 or
RC_3, then clusterCreate.py -- and the caller scraped stdout for the string
RC_3. Here all three steps run in one session and the answer is structured.

Every handler exposes the same five callables, which is what lets driver.py
stay generic:

    read(admin, params)                -> dict describing live state, {} if absent
    plan_present(admin, params, before) -> (changed, after)
    plan_absent(admin, params, before)  -> (changed, after)
    write_present(admin, params, before)
    write_absent(admin, params, before)
    sync(admin, params)                 optional
"""


def read(admin, params):
    """Current state of the cluster, or an empty dict when it does not exist."""
    AdminConfig = admin["AdminConfig"]

    cluster_id = ""
    for candidate in AdminConfig.list("ServerCluster").splitlines():
        candidate = candidate.strip()
        if not candidate:
            continue
        if AdminConfig.showAttribute(candidate, "name") == params["name"]:
            cluster_id = candidate
            break

    if not cluster_id:
        return {}

    members = []
    member_ids = AdminConfig.showAttribute(cluster_id, "members")
    if member_ids:
        for member in member_ids.strip("[]").split():
            if not member:
                continue
            members.append({
                "name": AdminConfig.showAttribute(member, "memberName"),
                "node": AdminConfig.showAttribute(member, "nodeName"),
            })

    return {
        "exists": True,
        "name": params["name"],
        "config_id": cluster_id,
        "prefer_local": AdminConfig.showAttribute(cluster_id, "preferLocal"),
        "members": members,
    }


def plan_present(admin, params, before):
    """Decide whether anything has to change, without changing it.

    This is the half that makes --check and --diff meaningful: it runs even in
    check mode, so the operator sees the real gap before approving.
    """
    if not before:
        return True, {
            "exists": True,
            "name": params["name"],
            "prefer_local": params.get("prefer_local", "true"),
            "members": [],
        }

    desired = params.get("prefer_local")
    if desired is not None and str(before.get("prefer_local")).lower() != str(desired).lower():
        after = dict(before)
        after["prefer_local"] = desired
        return True, after

    return False, before


def plan_absent(admin, params, before):
    if not before:
        return False, {}
    return True, {}


def write_present(admin, params, before):
    AdminTask = admin["AdminTask"]
    AdminConfig = admin["AdminConfig"]

    if not before:
        AdminTask.createCluster([
            "-clusterConfig",
            "[[%s %s false]]" % (params["name"], params.get("prefer_local", "true")),
        ])
        return

    desired = params.get("prefer_local")
    if desired is not None:
        AdminConfig.modify(before["config_id"], [["preferLocal", str(desired).lower()]])


def write_absent(admin, params, before):
    # The legacy repository advertises state: absent on 34 resource types and
    # implements it on 5; for clusters the call was left commented out. It is
    # implemented here because wave 6 (decommissioning) depends on it.
    admin["AdminTask"].deleteCluster(["-clusterName", params["name"]])


def sync(admin, params):
    """Push the saved configuration to the nodes.

    Only called when something actually changed, which is the point of having a
    truthful `changed`: no change, no ripple.
    """
    AdminControl = admin["AdminControl"]
    for mbean in AdminControl.queryNames("type=NodeSync,*").splitlines():
        mbean = mbean.strip()
        if mbean:
            AdminControl.invoke(mbean, "sync")
