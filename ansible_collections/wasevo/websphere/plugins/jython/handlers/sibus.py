# -*- coding: utf-8 -*-
"""Handler for a service integration bus: the bus, its members, its destinations.

The embedded messaging of WAS traditional - what JMS on the default messaging
provider runs on. There is no Liberty equivalent: README section 10 says an
external broker replaces it, so this declaration lives in the traditional part
of the model, not in the shared layer.

ONE BUS, ONE SESSION. The bus, the members that host its messaging engines and
the destinations it carries arrive in one request and are reconciled in one
wsadmin session, in the order they depend on each other.

WHAT IS RECONCILED AND WHAT IS ONLY REPORTED.

  bus           created, its description reconciled
  members       added when missing; a member the cell has and the request does
                not name is left alone, as for cluster members
  destinations  created, their reliability, redelivery limit, exception
                destination and description reconciled

  A member's MESSAGE STORE and MESSAGING ENGINE POLICY are fixed when its
  engine is created. Changing either means removing the member and adding it
  back, which recreates the engine and DISCARDS EVERY MESSAGE IT HOLDS. So a
  declared store or policy that differs from the live one is reported in the
  plan as a drift, and never "corrected" by a run: losing messages has to be a
  decision somebody takes, not a side effect of a replay.

state: absent deletes the bus, which takes its members and destinations with it.

Five callables, same contract as every other handler - see cluster.py.
"""

import _scope


def _ids(text):
    text = (text or "").strip()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    return [part for part in text.replace("\n", " ").split() if part]


def _bus_id(AdminConfig, name):
    for config_id in AdminConfig.list("SIBus").splitlines():
        config_id = config_id.strip()
        if config_id and AdminConfig.showAttribute(config_id, "name") == name:
            return config_id
    return ""


def _member_key(member):
    if member.get("cluster"):
        return "cluster:%s" % member["cluster"]
    return "server:%s/%s" % (member["node"], member["server"])


def _store_of(AdminConfig, AdminTask, bus, entry):
    """file or data, read from the member's messaging engine.

    The store is a child of the ENGINE, not an attribute of the member: an
    engine holds a fileStore or a dataStore. Read through the real API -
    listSIBEngines then the engine's attributes - so this works on a cell and
    not only in the fake one.
    """
    args = ["-bus", bus]
    if entry["cluster"]:
        args += ["-cluster", entry["cluster"]]
    else:
        args += ["-node", entry["node"], "-server", entry["server"]]
    for engine in _ids(AdminTask.listSIBEngines(args)):
        if (AdminConfig.showAttribute(engine, "dataStore") or "").strip():
            return "data"
        return "file"
    return ""


def _members(AdminConfig, AdminTask, bus):
    """The bus members, with the store their engine was created with.

    The engine POLICY is not read back. It lives in the core group's HA
    manager policies, not on the member, and a plan that compared it would be
    comparing a guess. It is applied when the member is added, and reported
    as declared.
    """
    found = {}
    for member_id in _ids(AdminTask.listSIBusMembers(["-bus", bus])):
        entry = {
            "cluster": AdminConfig.showAttribute(member_id, "cluster") or "",
            "node": AdminConfig.showAttribute(member_id, "node") or "",
            "server": AdminConfig.showAttribute(member_id, "server") or "",
        }
        entry["store"] = _store_of(AdminConfig, AdminTask, bus, entry)
        found[_member_key(entry)] = entry
    return found


_TYPES = (("Queue", "queue"), ("TopicSpace", "topic_space"))


def _destinations(AdminConfig, AdminTask, bus):
    found = {}
    for wsadmin_type, kind in _TYPES:
        for dest_id in _ids(AdminTask.listSIBDestinations(["-bus", bus, "-type", wsadmin_type])):
            name = AdminConfig.showAttribute(dest_id, "identifier")
            found[name] = {
                "config_id": dest_id,
                "name": name,
                "type": kind,
                "reliability": AdminConfig.showAttribute(dest_id, "reliability") or "",
                "max_failed_deliveries": int(AdminConfig.showAttribute(dest_id, "maxFailedDeliveries") or 0),
                "exception_destination": AdminConfig.showAttribute(dest_id, "exceptionDestination") or "",
                "description": AdminConfig.showAttribute(dest_id, "description") or "",
            }
    return found


def _public_destination(entry):
    out = dict(entry)
    out.pop("config_id", None)
    return out


def _desired_destination(dest):
    return {
        "name": dest["name"],
        "type": dest.get("type", "queue"),
        "reliability": dest.get("reliability", "ASSURED_PERSISTENT"),
        "max_failed_deliveries": int(dest.get("max_failed_deliveries", 5)),
        "exception_destination": dest.get("exception_destination", "") or "",
        "description": dest.get("description", "") or "",
    }


def _desired_member(member):
    """What is compared about a member: who it is and which store it uses."""
    return {
        "cluster": member.get("cluster") or "",
        "node": member.get("node") or "",
        "server": member.get("server") or "",
        "store": member.get("store", "file"),
    }


def _policy(member):
    """The engine policy, applied when a CLUSTER member is added."""
    return member.get("cluster") and member.get("policy", "HA") or ""


def read(admin, params):
    AdminConfig = admin["AdminConfig"]
    AdminTask = admin["AdminTask"]
    bus = params["bus"]
    bus_id = _bus_id(AdminConfig, bus)
    if not bus_id:
        return {}

    members = _members(AdminConfig, AdminTask, bus)
    destinations = _destinations(AdminConfig, AdminTask, bus)
    wanted_members = [_member_key(m) for m in params.get("members") or []]
    wanted_dests = [d["name"] for d in params.get("destinations") or []]
    return {
        "exists": True,
        "bus": bus,
        "description": AdminConfig.showAttribute(bus_id, "description") or "",
        "members": sorted([members[k] for k in wanted_members if k in members], key=_member_key),
        "destinations": sorted(
            [_public_destination(destinations[n]) for n in wanted_dests if n in destinations],
            key=lambda d: d["name"],
        ),
    }


def _drifts(live_members, desired):
    """A store that differs on an existing member: reported, never fixed."""
    found = []
    for member in desired:
        current = live_members.get(_member_key(member))
        if current is None or not current["store"]:
            continue
        if member["store"] != current["store"]:
            found.append(
                "%s: declared store %s, its engine has %s - changing it "
                "recreates the engine and discards its messages, so it is not "
                "done by a run" % (_member_key(member), member["store"], current["store"])
            )
    return found


def plan_present(admin, params, before):
    desired_members = [_desired_member(m) for m in params.get("members") or []]
    desired_dests = [_desired_destination(d) for d in params.get("destinations") or []]
    planned = {
        "exists": True,
        "bus": params["bus"],
        "description": params.get("description", "") or "",
        "members": sorted(desired_members, key=_member_key),
        "destinations": sorted(desired_dests, key=lambda d: d["name"]),
    }

    # A destination's exception destination must be a destination of the bus,
    # or the system default. Refused by name: WAS accepts any string here, and
    # undeliverable messages then have nowhere to go.
    names = [d["name"] for d in desired_dests]
    for dest in desired_dests:
        target = dest["exception_destination"]
        if target and not target.startswith("_SYSTEM.") and target not in names:
            live = before and [d["name"] for d in before["destinations"]] or []
            if target not in live:
                raise ValueError(
                    "destination %s sends its failed messages to %s, which is "
                    "not a destination of bus %s. Declare it too, or use the "
                    "system default by leaving exception_destination empty."
                    % (dest["name"], target, params["bus"])
                )

    if not before:
        _refuse_missing_clusters(admin, desired_members)
        return True, planned

    live_members = dict((_member_key(m), m) for m in before["members"])
    planned["drifts"] = _drifts(live_members, desired_members)
    # The live store is what the plan reports for an existing member, since a
    # run will not change it - so a drift shows in "drifts", not as a change.
    planned["members"] = sorted(
        [live_members.get(_member_key(m), m) for m in desired_members], key=_member_key,
    )

    changed = (
        before["description"] != planned["description"]
        or len([m for m in desired_members if _member_key(m) not in live_members]) > 0
        or before["destinations"] != planned["destinations"]
    )
    _refuse_missing_clusters(admin, [m for m in desired_members if _member_key(m) not in live_members])
    return changed, planned


def _refuse_missing_clusters(admin, members):
    """A cluster member of a bus needs the cluster. A future in a check run."""
    if admin.get("check_mode"):
        return
    AdminConfig = admin["AdminConfig"]
    for member in members:
        if member["cluster"] and not _scope.find(AdminConfig, {"type": "cluster", "cluster": member["cluster"]}):
            raise ValueError(
                "bus member cluster %s does not exist in this cell. The cluster "
                "job creates it - traditional_cluster.yml." % member["cluster"]
            )


def plan_absent(admin, params, before):
    if not before:
        return False, {}
    return True, {}


def _member_args(bus, member, raw):
    args = ["-bus", bus]
    if member["cluster"]:
        args += ["-cluster", member["cluster"]]
    else:
        args += ["-node", member["node"], "-server", member["server"]]
    if member["store"] == "data":
        data = raw.get("data_store") or {}
        args += ["-dataStore"]
        if data.get("datasource_jndi"):
            args += ["-createDefaultDatasource", "false",
                     "-datasourceJndiName", data["datasource_jndi"]]
        else:
            args += ["-createDefaultDatasource", "true"]
        if data.get("auth_alias"):
            args += ["-authAlias", data["auth_alias"]]
        if data.get("schema"):
            args += ["-schemaName", data["schema"]]
        args += ["-createTables", data.get("create_tables", True) and "true" or "false"]
    else:
        args += ["-fileStore"]
        files = raw.get("file_store") or {}
        for key, flag in (("log_dir", "-logDirectory"),
                          ("permanent_dir", "-permanentStoreDirectory"),
                          ("temporary_dir", "-temporaryStoreDirectory")):
            if files.get(key):
                args += [flag, files[key]]
    if member["cluster"]:
        # The engine policy: HA is one engine that fails over between the
        # cluster's members; SCALABILITY is one engine per member.
        args += ["-enableAssistance", "true", "-policyName", _policy(raw)]
    return args


def _destination_args(bus, dest):
    args = [
        "-bus", bus,
        "-name", dest["name"],
        "-reliability", dest["reliability"],
        "-maxFailedDeliveries", str(dest["max_failed_deliveries"]),
        "-description", dest["description"],
    ]
    if dest["exception_destination"]:
        args += ["-exceptionDestination", dest["exception_destination"]]
    return args


def write_present(admin, params, before):
    AdminConfig = admin["AdminConfig"]
    AdminTask = admin["AdminTask"]
    bus = params["bus"]
    description = params.get("description", "") or ""

    # 1. The bus.
    if not before:
        AdminTask.createSIBus(["-bus", bus, "-description", description,
                               "-busSecurity", params.get("security") and "true" or "false"])
    elif before["description"] != description:
        AdminTask.modifySIBus(["-bus", bus, "-description", description])

    # 2. The members, which host the engines a queue point needs.
    live_members = _members(AdminConfig, AdminTask, bus)
    raw_members = params.get("members") or []
    for raw in raw_members:
        member = _desired_member(raw)
        if _member_key(member) not in live_members:
            AdminTask.addSIBusMember(_member_args(bus, member, raw))

    # 3. The destinations. A queue is localised on a bus member: the first one
    #    declared, unless the destination names its own.
    live = _destinations(AdminConfig, AdminTask, bus)
    first = raw_members and _desired_member(raw_members[0]) or None
    for raw in params.get("destinations") or []:
        dest = _desired_destination(raw)
        current = live.get(dest["name"])
        if current is None:
            args = _destination_args(bus, dest)
            args += ["-type", dest["type"] == "topic_space" and "TopicSpace" or "Queue"]
            host = raw.get("member") and _desired_member(raw["member"]) or first
            if dest["type"] == "queue" and host:
                if host["cluster"]:
                    args += ["-cluster", host["cluster"]]
                else:
                    args += ["-node", host["node"], "-server", host["server"]]
            AdminTask.createSIBDestination(args)
        elif _public_destination(current) != dest:
            AdminTask.modifySIBDestination(_destination_args(bus, dest))


def write_absent(admin, params, before):
    # Deleting the bus deletes its members, their engines and every message
    # they hold, and its destinations. Only ever on an explicit state: absent.
    admin["AdminTask"].deleteSIBus(["-bus", params["bus"]])


def sync(admin, params):
    AdminControl = admin["AdminControl"]
    for mbean in AdminControl.queryNames("type=NodeSync,*").splitlines():
        mbean = mbean.strip()
        if mbean:
            AdminControl.invoke(mbean, "sync")
