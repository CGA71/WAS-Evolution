# -*- coding: utf-8 -*-
"""Handler for JMS resources: connection factories, queues, topics and
activation specifications, on one messaging provider at one scope.

ONE HANDLER, ONE TABLE PER PROVIDER. The four kinds of resource are the same
idea on the default messaging provider (the service integration bus) and on
IBM MQ; what differs is the AdminTask verbs and the attributes. Each provider
is a table below, so adding one is adding a table, not a handler.

READ THROUGH THE show* VERBS. A JMS resource keeps most of what matters in a
property set rather than as plain attributes, and the AdminTask show* verbs
are what flatten it into "{name=..., jndiName=..., busName=...}". That is
what the plan compares, and only for the fields the request declares.

WHAT WAS ACCEPTS AND SHOULD NOT, refused before anything is written:

  - a JMS queue whose bus destination does not exist on the bus, or is a
    topic space; a JMS topic whose topic space is not one
  - an activation specification listening on a JNDI name no JMS queue or
    topic of the request or the scope carries - the message-driven bean then
    deploys, starts, and never receives anything
  - a J2C alias that does not exist
  - two resources on one JNDI name - the lookup returns whichever bound last

In a check run the bus and its destinations may be a future, created by the
bus step of the same run in check mode too; then those checks stand down.

Five callables, same contract as every other handler - see cluster.py.
"""

import _scope

KINDS = ("connection_factories", "queues", "topics", "activation_specs")

# A field: (declaration key, WAS key, default, compared after creation).
# Fields compared False are applied at creation only - a connection factory's
# type, for instance, cannot be changed in place.
PROVIDERS = {
    "sib": {
        "connection_factories": {
            "verbs": ("listSIBJMSConnectionFactories", "showSIBJMSConnectionFactory",
                      "createSIBJMSConnectionFactory", "modifySIBJMSConnectionFactory",
                      "deleteSIBJMSConnectionFactory"),
            "fields": (
                ("jndi_name", "jndiName", "", True),
                ("bus", "busName", "", True),
                ("auth_alias", "authDataAlias", "", True),
                ("description", "description", "", True),
                ("type", "type", "", False),
            ),
        },
        "queues": {
            "verbs": ("listSIBJMSQueues", "showSIBJMSQueue",
                      "createSIBJMSQueue", "modifySIBJMSQueue", "deleteSIBJMSQueue"),
            "fields": (
                ("jndi_name", "jndiName", "", True),
                ("queue", "queueName", "", True),
                ("bus", "busName", "", True),
                ("delivery_mode", "deliveryMode", "Application", True),
                ("description", "description", "", True),
            ),
        },
        "topics": {
            "verbs": ("listSIBJMSTopics", "showSIBJMSTopic",
                      "createSIBJMSTopic", "modifySIBJMSTopic", "deleteSIBJMSTopic"),
            "fields": (
                ("jndi_name", "jndiName", "", True),
                ("topic_space", "topicSpace", "", True),
                ("topic_name", "topicName", "", True),
                ("bus", "busName", "", True),
                ("delivery_mode", "deliveryMode", "Application", True),
                ("description", "description", "", True),
            ),
        },
        "activation_specs": {
            "verbs": ("listSIBJMSActivationSpecs", "showSIBJMSActivationSpec",
                      "createSIBJMSActivationSpec", "modifySIBJMSActivationSpec",
                      "deleteSIBJMSActivationSpec"),
            "fields": (
                ("jndi_name", "jndiName", "", True),
                ("destination_jndi", "destinationJndiName", "", True),
                ("destination_type", "destinationType", "javax.jms.Queue", True),
                ("bus", "busName", "", True),
                ("max_concurrency", "maxConcurrency", "10", True),
                ("auth_alias", "authenticationAlias", "", True),
                ("description", "description", "", True),
            ),
        },
    },
}


def _parse_show(text):
    """{key=value, key=value} -> dict. What every show* verb returns."""
    text = (text or "").strip()
    if text.startswith("{") and text.endswith("}"):
        text = text[1:-1]
    out = {}
    for pair in text.split(", "):
        if "=" in pair:
            key, value = pair.split("=", 1)
            out[key.strip()] = value.strip()
    return out


def _ids(text):
    text = (text or "").strip()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    return [part for part in text.replace("\n", " ").split() if part]


def _table(params):
    provider = params.get("provider", "sib")
    if provider not in PROVIDERS:
        raise ValueError("JMS provider %r is not one of %s" % (provider, ", ".join(sorted(PROVIDERS))))
    return PROVIDERS[provider]


def _live(admin, table, kind, scope_id):
    """name -> (config_id, shown) for every resource of a kind in the scope."""
    AdminTask = admin["AdminTask"]
    list_verb, show_verb = table[kind]["verbs"][0], table[kind]["verbs"][1]
    found = {}
    for config_id in _ids(getattr(AdminTask, list_verb)(scope_id)):
        shown = _parse_show(getattr(AdminTask, show_verb)(config_id))
        found[shown.get("name", "")] = (config_id, shown)
    return found


def _desired(table, kind, resource):
    out = {"name": resource["name"]}
    for key, was_key, default, compared in table[kind]["fields"]:
        if compared:
            out[key] = str(resource.get(key, default) or default)
    return out


def _seen(table, kind, name, shown):
    out = {"name": name}
    for key, was_key, default, compared in table[kind]["fields"]:
        if compared:
            out[key] = str(shown.get(was_key, "") or default)
    return out


def read(admin, params):
    table = _table(params)
    scope_id = _scope.find(admin["AdminConfig"], params["scope"])
    if not scope_id:
        return {}
    before = {"exists": True, "scope": _scope.describe(params["scope"])}
    for kind in KINDS:
        live = _live(admin, table, kind, scope_id)
        before[kind] = sorted(
            [_seen(table, kind, r["name"], live[r["name"]][1])
             for r in params.get(kind) or [] if r["name"] in live],
            key=lambda r: r["name"],
        )
    return before


# ---------------------------------------------------------------------------
# What WAS accepts and should not
# ---------------------------------------------------------------------------

def _bus_destinations(admin, bus):
    """{name: 'Queue'|'TopicSpace'} for a bus, or None when the bus is absent."""
    AdminConfig = admin["AdminConfig"]
    AdminTask = admin["AdminTask"]
    exists = False
    for config_id in AdminConfig.list("SIBus").splitlines():
        config_id = config_id.strip()
        if config_id and AdminConfig.showAttribute(config_id, "name") == bus:
            exists = True
    if not exists:
        return None
    found = {}
    for wsadmin_type in ("Queue", "TopicSpace"):
        for dest in _ids(AdminTask.listSIBDestinations(["-bus", bus, "-type", wsadmin_type])):
            found[AdminConfig.showAttribute(dest, "identifier")] = wsadmin_type
    return found


def _aliases(AdminConfig):
    names = []
    for config_id in AdminConfig.list("JAASAuthData").splitlines():
        config_id = config_id.strip()
        if config_id:
            names.append(AdminConfig.showAttribute(config_id, "alias"))
    return names


def _refuse(admin, params, before):
    """Refusals that hold in every run, then the ones a check run stands down."""
    jndi = {}
    for kind in KINDS:
        for resource in params.get(kind) or []:
            name = resource.get("jndi_name", "")
            if name in jndi:
                raise ValueError(
                    "JNDI name %s is used by %s and by %s. The lookup would "
                    "return whichever bound last." % (name, jndi[name], resource["name"])
                )
            jndi[name] = resource["name"]

    # An activation spec must listen on a destination this request declares,
    # the scope already carries, or another scope declares - the role passes
    # every declared queue and topic as known_destinations, because WAS
    # resolves a JNDI name through the scopes.
    carried = dict(params.get("known_destinations") or {})
    for kind, jms_type in (("queues", "javax.jms.Queue"), ("topics", "javax.jms.Topic")):
        for resource in params.get(kind) or []:
            carried[resource["jndi_name"]] = jms_type
        for resource in (before and before.get(kind)) or []:
            carried.setdefault(resource["jndi_name"], jms_type)
    for spec in params.get("activation_specs") or []:
        target = spec.get("destination_jndi", "")
        wanted = spec.get("destination_type", "javax.jms.Queue")
        if target not in carried:
            raise ValueError(
                "activation spec %s listens on %s, which no JMS queue or topic "
                "declared in this run, or carried by %s, has. The "
                "message-driven bean would deploy, start, and never receive a "
                "message." % (spec["name"], target, _scope.describe(params["scope"]))
            )
        if carried[target] != wanted:
            raise ValueError(
                "activation spec %s expects a %s at %s, which is a %s"
                % (spec["name"], wanted, target, carried[target])
            )

    if admin.get("check_mode"):
        return

    AdminConfig = admin["AdminConfig"]
    aliases = _aliases(AdminConfig)
    for kind in KINDS:
        for resource in params.get(kind) or []:
            alias = resource.get("auth_alias")
            if alias and alias not in aliases:
                raise ValueError(
                    "%s names J2C alias %s, which does not exist in the cell. "
                    "Run the J2C job first - traditional_j2c.yml."
                    % (resource["name"], alias)
                )

    if params.get("provider", "sib") != "sib":
        return
    buses = {}
    for kind in KINDS:
        for resource in params.get(kind) or []:
            bus = resource.get("bus")
            if not bus:
                continue
            if bus not in buses:
                buses[bus] = _bus_destinations(admin, bus)
            if buses[bus] is None:
                raise ValueError(
                    "%s names bus %s, which does not exist. Run the bus job "
                    "first - traditional_sibus.yml." % (resource["name"], bus)
                )
    for queue in params.get("queues") or []:
        dests = queue.get("bus") and buses.get(queue["bus"]) or {}
        if dests.get(queue.get("queue")) != "Queue":
            raise ValueError(
                "JMS queue %s points at %s on bus %s, which is %s. A JMS queue "
                "needs a bus queue destination - declare it in the bus job."
                % (queue["name"], queue.get("queue"), queue.get("bus"),
                   queue.get("queue") in dests and "a topic space" or "not a destination of that bus")
            )
    for topic in params.get("topics") or []:
        dests = topic.get("bus") and buses.get(topic["bus"]) or {}
        if dests.get(topic.get("topic_space")) != "TopicSpace":
            raise ValueError(
                "JMS topic %s uses topic space %s on bus %s, which is %s."
                % (topic["name"], topic.get("topic_space"), topic.get("bus"),
                   topic.get("topic_space") in dests and "a queue" or "not a destination of that bus")
            )


def plan_present(admin, params, before):
    table = _table(params)
    _refuse(admin, params, before)

    planned = {"exists": True, "scope": _scope.describe(params["scope"])}
    for kind in KINDS:
        planned[kind] = sorted(
            [_desired(table, kind, r) for r in params.get(kind) or []],
            key=lambda r: r["name"],
        )

    if not before:
        if not admin.get("check_mode"):
            raise ValueError(
                "%s does not exist in this cell, so no JMS resource can be "
                "created there." % _scope.describe(params["scope"])
            )
        planned["exists"] = False
        planned["scope_pending"] = True
        return True, planned

    changed = False
    for kind in KINDS:
        if before[kind] != planned[kind]:
            changed = True
    return changed, planned


def plan_absent(admin, params, before):
    if not before:
        return False, {}
    after = dict(before)
    changed = False
    for kind in KINDS:
        doomed = [r["name"] for r in params.get(kind) or []]
        kept = [r for r in before[kind] if r["name"] not in doomed]
        changed = changed or len(kept) != len(before[kind])
        after[kind] = kept
    return changed, after


def _flags(table, kind, resource, only=None):
    """AdminTask arguments for a resource: -wasKey value, for set fields."""
    args = []
    for key, was_key, default, compared in table[kind]["fields"]:
        if only is not None and key not in only:
            continue
        value = resource.get(key, default)
        if value not in (None, ""):
            args += ["-" + was_key, str(value)]
    return args


def write_present(admin, params, before):
    table = _table(params)
    AdminTask = admin["AdminTask"]
    scope_id = _scope.find(admin["AdminConfig"], params["scope"])

    # Destinations before what refers to them: an activation spec names the
    # JNDI of a queue, so queues and topics are written first.
    for kind in ("connection_factories", "queues", "topics", "activation_specs"):
        verbs = table[kind]["verbs"]
        live = _live(admin, table, kind, scope_id)
        for resource in params.get(kind) or []:
            if resource["name"] not in live:
                getattr(AdminTask, verbs[2])(
                    scope_id, ["-name", resource["name"]] + _flags(table, kind, resource),
                )
                continue
            config_id, shown = live[resource["name"]]
            current = _seen(table, kind, resource["name"], shown)
            wanted = _desired(table, kind, resource)
            different = [k for k in wanted if k != "name" and wanted[k] != current.get(k)]
            if different:
                getattr(AdminTask, verbs[3])(config_id, _flags(table, kind, resource, only=different))


def write_absent(admin, params, before):
    table = _table(params)
    AdminTask = admin["AdminTask"]
    scope_id = _scope.find(admin["AdminConfig"], params["scope"])
    # The reverse order: what listens goes before what it listens on.
    for kind in ("activation_specs", "topics", "queues", "connection_factories"):
        live = _live(admin, table, kind, scope_id)
        for resource in params.get(kind) or []:
            if resource["name"] in live:
                getattr(AdminTask, table[kind]["verbs"][4])(live[resource["name"]][0])


def sync(admin, params):
    AdminControl = admin["AdminControl"]
    for mbean in AdminControl.queryNames("type=NodeSync,*").splitlines():
        mbean = mbean.strip()
        if mbean:
            AdminControl.invoke(mbean, "sync")
