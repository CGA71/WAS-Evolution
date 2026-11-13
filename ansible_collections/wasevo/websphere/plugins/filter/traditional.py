# -*- coding: utf-8 -*-
# Copyright (c) 2026, CGA
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)
"""Render shared-model declarations into WAS traditional module arguments.

The shared model - layer 1 - says what a datasource is in terms neither
back-end owns: an abstract vendor, a Liberty-style pool with durations like
"30s". Each back-end renders it. The Liberty one does it in a template; this
is the traditional one, and it is Python rather than a Jinja block because the
rendering has rules worth testing on their own - which vendor, which scope,
which pool attribute, how many seconds - and a sixty-line Jinja expression
cannot be tested without running a play.

Every function here is pure: declarations in, arguments and errors out.
Nothing reaches a cell. Errors are returned rather than raised, so the role
can refuse with all of them at once instead of the first one.
"""

from __future__ import absolute_import, division, print_function

__metaclass__ = type

import json
import re

# Liberty-style pool setting -> (WAS ConnectionPool attribute, unit).
# A key not listed here is refused, not dropped: a setting that silently
# disappears on one back-end is a difference between the two that nobody
# chose.
POOL_ATTRIBUTES = {
    "maxPoolSize": ("maxConnections", "count"),
    "minPoolSize": ("minConnections", "count"),
    "connectionTimeout": ("connectionTimeout", "seconds"),
    "reapTime": ("reapTime", "seconds"),
    "maxIdleTime": ("unusedTimeout", "seconds"),
    "agedTimeout": ("agedTimeout", "seconds"),
}

_DURATION = re.compile(r"^\s*(\d+)\s*(s|m|h)?\s*$")
_UNIT = {None: 1, "s": 1, "m": 60, "h": 3600}


def to_seconds(value):
    """30s -> 30, 5m -> 300, 1h -> 3600, 1800 -> 1800. None when unreadable."""
    match = _DURATION.match(str(value))
    if not match:
        return None
    return int(match.group(1)) * _UNIT[match.group(2)]


def resolve_scope(declared, default, cluster_name, cell_name):
    """A declared scope, or the default, made complete.

    Accepts the short form - `scope: cell` - and the dict form. A cluster
    scope with no name is the run's cluster; a cell scope with no name is the
    run's cell. Node and server scopes must name themselves: there is no
    "the node" of a run.
    """
    scope = declared if declared is not None else default
    if isinstance(scope, str):
        scope = {"type": scope}
    scope = dict(scope)
    if scope.get("type") == "cluster":
        scope.setdefault("cluster", cluster_name)
    elif scope.get("type") == "cell":
        scope.setdefault("cell", cell_name)
    return scope


def _scope_key(scope):
    return json.dumps(scope, sort_keys=True)


def jdbc_groups(datasources, vendors, default_scope, cluster_name, cell_name,
                provider_suffix="Provider"):
    """Group the declared datasources by scope, as module arguments.

    Returns {"groups": [{"scope", "providers", "datasources"}], "errors": [...]}.
    One group per distinct scope, in first-seen order, because each module
    call takes one scope - and one wsadmin session per scope is the cost.
    """
    groups = []
    by_key = {}
    errors = []

    for ds in datasources or []:
        name = ds.get("name", "<unnamed>")
        vendor_key = ds.get("vendor")
        vendor = (vendors or {}).get(vendor_key)
        if vendor is None:
            errors.append("%s: vendor %r is not in jdbc_vendors.yml" % (name, vendor_key))
            continue
        trad = vendor["traditional"]

        scope = resolve_scope(ds.get("scope"), default_scope, cluster_name, cell_name)
        if scope.get("type") not in ("cluster", "node", "server", "cell"):
            errors.append("%s: scope %r is not cluster, node, server or cell" % (name, scope))
            continue

        # Errors on this datasource are counted, so one that cannot be fully
        # rendered is left out rather than rendered with a setting missing.
        before = len(errors)
        pool = {}
        for key, value in (ds.get("pool") or {}).items():
            if key not in POOL_ATTRIBUTES:
                errors.append(
                    "%s: pool setting %r has no WAS traditional equivalent here; "
                    "known: %s" % (name, key, ", ".join(sorted(POOL_ATTRIBUTES)))
                )
                continue
            attribute, unit = POOL_ATTRIBUTES[key]
            if unit == "seconds":
                seconds = to_seconds(value)
                if seconds is None:
                    errors.append(
                        "%s: pool %s is %r, which is not a duration in seconds, "
                        "minutes or hours (30s, 5m, 1h, or a number of seconds)"
                        % (name, key, value)
                    )
                    continue
                pool[attribute] = seconds
            else:
                try:
                    pool[attribute] = int(value)
                except (TypeError, ValueError):
                    errors.append("%s: pool %s is %r, not a number" % (name, key, value))

        properties = dict((k, str(v)) for k, v in (ds.get("properties") or {}).items())
        # Liberty's transactional="false" is, on WAS traditional, a custom
        # property of the datasource. Translated rather than dropped.
        if str(ds.get("transactional", "true")).lower() == "false":
            properties["nonTransactionalDataSource"] = "true"

        provider_name = ds.get("provider") or (name + provider_suffix)
        classpath = ""
        if ds.get("driver_dir") and ds.get("driver_jar"):
            classpath = "%s/%s" % (str(ds["driver_dir"]).rstrip("/"), ds["driver_jar"])

        provider = {
            "name": provider_name,
            "database_type": trad["database_type"],
            "provider_type": ds.get("provider_type") or trad["provider_type"],
            "implementation_type": trad["implementation_type"],
            "classpath": classpath,
            "native_path": "",
            "description": vendor.get("description", ""),
        }
        datasource = {
            "name": name,
            "provider": provider_name,
            "jndi_name": ds.get("jndi_name", ""),
            "helper": ds.get("helper") or trad["helper"],
            "auth_alias": ds.get("auth_alias") or "",
            "statement_cache_size": int(ds.get("statement_cache_size", 10)),
            "properties": properties,
            "pool": pool,
        }
        if not datasource["jndi_name"]:
            errors.append("%s: no jndi_name" % name)
        if len(errors) > before:
            continue

        key = _scope_key(scope)
        if key not in by_key:
            by_key[key] = {"scope": scope, "providers": [], "datasources": []}
            groups.append(by_key[key])
        group = by_key[key]

        same = [p for p in group["providers"] if p["name"] == provider_name]
        if same and same[0] != provider:
            errors.append(
                "%s: shares provider %s with another datasource of the same "
                "scope, but declares a different driver for it"
                % (name, provider_name)
            )
            continue
        if not same:
            group["providers"].append(provider)
        group["datasources"].append(datasource)

    return {"groups": groups, "errors": errors}


def library_groups(libraries, expanded, default_scope, cluster_name, cell_name):
    """Group the declared shared libraries by scope, as module arguments.

    `expanded` maps a library name to the jars its dir + includes matched on
    the deployment manager - the role fills it with the find module, because
    WAS traditional has no wildcard in a library class path. A library that
    lists its `jars` explicitly is taken as written, in its order.

    Returns {"groups": [{"scope", "libraries"}], "errors": [...]}.
    """
    groups = []
    by_key = {}
    errors = []

    for library in libraries or []:
        name = library.get("name", "<unnamed>")

        if library.get("jars"):
            class_path = [str(j) for j in library["jars"]]
        elif library.get("dir"):
            # Sorted: the order find returns files in is the filesystem's, and
            # a class path that reshuffles between runs would read as a change
            # every time.
            class_path = sorted((expanded or {}).get(name) or [])
            if not class_path:
                errors.append(
                    "%s: %s/%s matched no file on the deployment manager. A "
                    "library with an empty class path provides nothing, and the "
                    "applications using it would fail on their first class "
                    "load. Deploy the jars first, or list them under `jars`."
                    % (name, str(library["dir"]).rstrip("/"), library.get("includes", "*.jar"))
                )
                continue
        else:
            errors.append("%s: declares neither `dir` nor `jars`" % name)
            continue

        scope = resolve_scope(library.get("scope"), default_scope, cluster_name, cell_name)
        if scope.get("type") not in ("cluster", "node", "server", "cell"):
            errors.append("%s: scope %r is not cluster, node, server or cell" % (name, scope))
            continue

        key = _scope_key(scope)
        if key not in by_key:
            by_key[key] = {"scope": scope, "libraries": []}
            groups.append(by_key[key])
        by_key[key]["libraries"].append({
            "name": name,
            "class_path": class_path,
            "native_path": [str(p) for p in library.get("native_path") or []],
            "description": library.get("description", ""),
            "isolated": bool(library.get("isolated", False)),
        })

    return {"groups": groups, "errors": errors}


SIB_RELIABILITY = (
    "BEST_EFFORT_NONPERSISTENT",
    "EXPRESS_NONPERSISTENT",
    "RELIABLE_NONPERSISTENT",
    "RELIABLE_PERSISTENT",
    "ASSURED_PERSISTENT",
)
SIB_POLICIES = ("HA", "SCALABILITY", "SCALABILITY_HA")


def sibus_specs(sibuses, cluster_name):
    """The declared buses, completed and checked, as module arguments.

    A bus that names no member gets the run's cluster - the usual shape, and
    the one that follows the members built before it. Every value WAS
    constrains is checked here, so a typo in a reliability level is refused
    with the accepted values before a wsadmin session starts.

    Returns {"buses": [...], "errors": [...]}.
    """
    buses = []
    errors = []
    for bus in sibuses or []:
        name = bus.get("name", "<unnamed>")
        before = len(errors)

        members = []
        for member in bus.get("members") or [{}]:
            member = dict(member)
            if not member.get("cluster") and not member.get("server"):
                member["cluster"] = cluster_name
            if member.get("server") and not member.get("node"):
                errors.append("%s: member server %s names no node" % (name, member["server"]))
            store = member.get("store", "file")
            if store not in ("file", "data"):
                errors.append("%s: member store %r is not file or data" % (name, store))
            policy = member.get("policy", "HA")
            if member.get("cluster") and policy not in SIB_POLICIES:
                errors.append("%s: engine policy %r is not one of %s"
                              % (name, policy, ", ".join(SIB_POLICIES)))
            members.append(member)

        destinations = []
        seen = []
        for dest in bus.get("destinations") or []:
            dest = dict(dest)
            dname = dest.get("name", "<unnamed>")
            if dname in seen:
                errors.append("%s: destination %s declared twice" % (name, dname))
            seen.append(dname)
            if dest.get("type", "queue") not in ("queue", "topic_space"):
                errors.append("%s: destination %s type %r is not queue or topic_space"
                              % (name, dname, dest.get("type")))
            reliability = dest.get("reliability", "ASSURED_PERSISTENT")
            if reliability not in SIB_RELIABILITY:
                errors.append("%s: destination %s reliability %r is not one of %s"
                              % (name, dname, reliability, ", ".join(SIB_RELIABILITY)))
            destinations.append(dest)

        if len(errors) > before:
            continue
        buses.append({
            "bus": name,
            "description": bus.get("description", ""),
            "security": bool(bus.get("security", False)),
            "members": members,
            "destinations": destinations,
        })
    return {"buses": buses, "errors": errors}


JMS_KINDS = ("connection_factories", "queues", "topics", "activation_specs")
JMS_PROVIDERS = ("sib", "mq")

# What every IBM MQ connection factory and activation spec of a run usually
# shares - the queue manager and how to reach it. Declared once under
# jms.mq_connection; a resource's own key wins.
MQ_CONNECTION_KEYS = ("qmgr", "transport", "host", "port", "channel", "connection_list")


def jms_groups(jms, default_scope, cluster_name, cell_name, default_provider="sib"):
    """Group the declared JMS resources by scope and provider.

    One module call takes one scope and one provider, so the resources are
    grouped on both. Every group also receives `known_destinations` - every
    JMS queue and topic declared anywhere, with its type - because an
    activation spec at cluster scope may listen on a queue declared at cell
    scope: WAS resolves the JNDI name through the scopes, and a check confined
    to one group would refuse a valid configuration.

    IBM MQ connection factories and activation specs take the keys of
    jms.mq_connection they do not set themselves.

    Returns {"groups": [...], "errors": [...]}.
    """
    groups = []
    by_key = {}
    errors = []
    known = {}
    jndi_owner = {}
    mq_connection = dict((k, v) for k, v in ((jms or {}).get("mq_connection") or {}).items()
                         if k in MQ_CONNECTION_KEYS)
    for key in sorted(((jms or {}).get("mq_connection") or {})):
        if key not in MQ_CONNECTION_KEYS:
            errors.append("mq_connection: %s is not one of %s" % (key, ", ".join(MQ_CONNECTION_KEYS)))

    for kind in JMS_KINDS:
        for resource in (jms or {}).get(kind) or []:
            name = resource.get("name", "<unnamed>")
            if not resource.get("jndi_name"):
                errors.append("%s: no jndi_name" % name)
                continue
            jndi = resource["jndi_name"]
            if jndi in jndi_owner:
                errors.append("JNDI name %s is declared by %s and by %s" % (jndi, jndi_owner[jndi], name))
                continue
            jndi_owner[jndi] = name
            if kind == "queues":
                known[jndi] = "javax.jms.Queue"
            elif kind == "topics":
                known[jndi] = "javax.jms.Topic"

    for kind in JMS_KINDS:
        for resource in (jms or {}).get(kind) or []:
            resource = dict(resource)
            name = resource.get("name", "<unnamed>")
            if not resource.get("jndi_name"):
                continue
            provider = resource.pop("provider", None) or default_provider
            if provider not in JMS_PROVIDERS:
                errors.append("%s: provider %r is not one of %s"
                              % (name, provider, ", ".join(JMS_PROVIDERS)))
                continue
            if provider == "sib" and not resource.get("bus"):
                errors.append("%s: a default messaging resource names its bus" % name)
                continue
            if provider == "mq":
                if resource.get("bus"):
                    errors.append("%s: an IBM MQ resource has no bus - it names a queue manager" % name)
                    continue
                if kind == "queues" and not resource.get("queue"):
                    errors.append("%s: an IBM MQ queue names its queue on the queue manager" % name)
                    continue
                if kind == "topics" and not resource.get("topic_name"):
                    errors.append("%s: an IBM MQ topic names its topic string" % name)
                    continue
                if kind in ("connection_factories", "activation_specs"):
                    for key, value in mq_connection.items():
                        resource.setdefault(key, value)
            scope = resolve_scope(resource.pop("scope", None), default_scope, cluster_name, cell_name)
            key = _scope_key(scope) + "|" + provider
            if key not in by_key:
                group = {"scope": scope, "provider": provider}
                for k in JMS_KINDS:
                    group[k] = []
                by_key[key] = group
                groups.append(group)
            by_key[key][kind].append(resource)

    for group in groups:
        group["known_destinations"] = known
    return {"groups": groups, "errors": errors}


# ---------------------------------------------------------------------------
# Server settings: transactions, EJB container, CDI, JPA
# ---------------------------------------------------------------------------
#
# Each function turns one intent of the shared model into the arguments of
# was_server_settings - components and their attributes, JVM properties,
# cluster attributes - and lists everything WAS would accept and should not.
# Returns {"settings": {...}, "errors": [...]}.

def _seconds(errors, name, value):
    seconds = to_seconds(value)
    if seconds is None:
        errors.append("%s: %r is not a duration - 30, 30s, 5m or 1h" % (name, value))
    return seconds


def _count(errors, name, value, minimum=0):
    try:
        number = int(str(value))
    except ValueError:
        errors.append("%s: %r is not a whole number" % (name, value))
        return None
    if number < minimum:
        errors.append("%s: %d is below %d" % (name, number, minimum))
        return None
    return number


# intent key -> TransactionService attribute. WAS spells the propagated
# timeout "propogated"; the intent key does not.
TRANSACTION_TIMEOUTS = (
    ("total_timeout", "totalTranLifetimeTimeout"),
    ("client_inactivity_timeout", "clientInactivityTimeout"),
    ("maximum_timeout", "maximumTransactionTimeout"),
    ("propagated_timeout", "propogatedOrBMTTranLifetimeTimeout"),
)
TRANSACTION_KEYS = tuple(k for k, _ in TRANSACTION_TIMEOUTS) + (
    "heuristic_retry_limit", "heuristic_retry_wait", "log_root", "peer_recovery")


def transaction_settings(tx, cell_name, clustered):
    """The transaction service of every server, and peer recovery.

    log_root is the shared directory every member's recovery log goes under,
    one directory per server - <log_root>/<cell>/<node>/<server> - so that a
    member can recover another's in-flight transactions. Peer recovery with
    the logs left under each profile is refused: WAS accepts it, and the
    recovery fails exactly when it is needed, because the surviving member
    cannot read the failed member's disk.
    """
    tx = tx or {}
    errors = []
    attrs = {}
    for key in sorted(tx):
        if key not in TRANSACTION_KEYS:
            errors.append("transactions: %s is not one of %s" % (key, ", ".join(TRANSACTION_KEYS)))

    seconds = {}
    for key, attribute in TRANSACTION_TIMEOUTS:
        if key in tx:
            value = _seconds(errors, "transactions." + key, tx[key])
            if value is not None:
                seconds[key] = value
                attrs[attribute] = str(value)
    # WAS caps a lifetime timeout at the maximum without a word: the declared
    # value would never be the one in force.
    maximum = seconds.get("maximum_timeout")
    if maximum:
        for key in ("total_timeout", "propagated_timeout"):
            if seconds.get(key) is not None and (seconds[key] == 0 or seconds[key] > maximum):
                errors.append(
                    "transactions.%s is %s, above maximum_timeout %ds: WAS would "
                    "silently cap it at the maximum" % (key, seconds[key] or "0 (no limit)", maximum))
    for key, attribute in (("heuristic_retry_limit", "heuristicRetryLimit"),
                           ("heuristic_retry_wait", "heuristicRetryWait")):
        if key in tx:
            value = _count(errors, "transactions." + key, tx[key])
            if value is not None:
                attrs[attribute] = str(value)

    root = tx.get("log_root")
    if root:
        if not str(root).startswith("/"):
            errors.append("transactions.log_root %r is not an absolute path" % root)
        else:
            attrs["transactionLogDirectory"] = "%s/%s/{node}/{server}" % (str(root).rstrip("/"), cell_name)

    cluster_attributes = {}
    peer = tx.get("peer_recovery")
    if peer is not None:
        if peer and not clustered:
            errors.append("transactions.peer_recovery needs a cluster: a standalone "
                          "server has no peer to recover it")
        if peer and not root:
            errors.append("transactions.peer_recovery without log_root: each member's "
                          "recovery log would stay under its own profile, where no "
                          "other member can read it, and recovery would fail when it "
                          "is needed")
        if clustered:
            cluster_attributes["enableHA"] = "true" if peer else "false"

    settings = {}
    if attrs:
        settings["components"] = {"TransactionService": attrs}
    if cluster_attributes:
        settings["cluster_attributes"] = cluster_attributes
    return {"settings": settings, "errors": errors}


EJB_KEYS = ("passivation_directory", "inactive_pool_cleanup_interval", "cache_size",
            "cache_cleanup_interval", "timers")
EJB_TIMER_KEYS = ("datasource_jndi", "datasource_alias", "table_prefix", "poll_interval",
                  "threads", "scheduler_jndi")


def _milliseconds(errors, name, value):
    """An interval WAS keeps in milliseconds: a bare number is milliseconds,
    a number with a unit is converted."""
    text = str(value).strip()
    if text.isdigit():
        return int(text)
    seconds = _seconds(errors, name, value)
    return None if seconds is None else seconds * 1000


def ejb_container_settings(ejb):
    """The EJB container, its cache and its timer service, on every server.

    Two refusals here, a third in the handler, which knows how many members
    the cluster really holds: persistent timers on several members with no
    shared datasource.
    """
    ejb = ejb or {}
    errors = []
    container, cache, timer = {}, {}, {}
    requires = []
    for key in sorted(ejb):
        if key not in EJB_KEYS:
            errors.append("ejb_container: %s is not one of %s" % (key, ", ".join(EJB_KEYS)))

    if ejb.get("passivation_directory"):
        container["passivationDirectory"] = str(ejb["passivation_directory"])
    if "inactive_pool_cleanup_interval" in ejb:
        value = _milliseconds(errors, "ejb_container.inactive_pool_cleanup_interval",
                              ejb["inactive_pool_cleanup_interval"])
        if value is not None:
            container["inactivePoolCleanupInterval"] = str(value)
    if "cache_size" in ejb:
        value = _count(errors, "ejb_container.cache_size", ejb["cache_size"], minimum=1)
        if value is not None:
            cache["cacheSize"] = str(value)
    if "cache_cleanup_interval" in ejb:
        value = _milliseconds(errors, "ejb_container.cache_cleanup_interval",
                              ejb["cache_cleanup_interval"])
        if value is not None:
            cache["cleanupInterval"] = str(value)

    timers = ejb.get("timers")
    if timers is not None:
        for key in sorted(timers):
            if key not in EJB_TIMER_KEYS:
                errors.append("ejb_container.timers: %s is not one of %s"
                              % (key, ", ".join(EJB_TIMER_KEYS)))
        # A custom scheduler brings its own database: IBM documents the
        # datasource and the table prefix as ignored then.
        if timers.get("scheduler_jndi") and (timers.get("datasource_jndi") or timers.get("table_prefix")):
            errors.append("ejb_container.timers: scheduler_jndi with datasource_jndi or "
                          "table_prefix - a custom scheduler uses its own database, and "
                          "WAS would ignore them")
        for key, attribute in (("datasource_jndi", "datasourceJNDIName"),
                               ("datasource_alias", "datasourceAlias"),
                               ("table_prefix", "tablePrefix"),
                               ("scheduler_jndi", "schedulerJNDIName")):
            if timers.get(key):
                timer[attribute] = str(timers[key])
        if "poll_interval" in timers:
            value = _seconds(errors, "ejb_container.timers.poll_interval", timers["poll_interval"])
            if value is not None:
                timer["pollInterval"] = str(value)
        if "threads" in timers:
            value = _count(errors, "ejb_container.timers.threads", timers["threads"], minimum=1)
            if value is not None:
                timer["numAlarmThreads"] = str(value)
        if timers.get("datasource_jndi"):
            requires.append(str(timers["datasource_jndi"]))

    components = {}
    if container:
        components["EJBContainer"] = container
    if cache:
        components["EJBCache"] = cache
    # The timer service is sent even empty when declared, so the handler can
    # refuse local timers on a cluster.
    if timers is not None:
        components["EJBTimer"] = timer
    settings = {}
    if components:
        settings["components"] = components
    if requires:
        settings["requires_datasources"] = requires
    return {"settings": settings, "errors": errors}


CDI_PROPERTIES = (
    # intent key -> JVM custom property. false: an archive with no beans.xml is
    # not scanned for beans - the startup cost of CDI on WAS 9 for an
    # application that does not use it. An application's manifest
    # (Enable-Implicit-Bean-Archive) overrides it.
    ("implicit_bean_archives", "com.ibm.ws.cdi.enableImplicitBeanArchives"),
)


def cdi_settings(cdi):
    """CDI, which WAS traditional configures through JVM custom properties."""
    cdi = cdi or {}
    errors = []
    properties = {}
    known = [k for k, _ in CDI_PROPERTIES]
    for key in sorted(cdi):
        if key not in known:
            errors.append("cdi: %s is not one of %s" % (key, ", ".join(known)))
    for key, prop in CDI_PROPERTIES:
        if key in cdi:
            value = cdi[key]
            if not isinstance(value, bool) and str(value).lower() not in ("true", "false"):
                errors.append("cdi.%s: %r is not true or false" % (key, value))
                continue
            properties[prop] = str(value).lower()
    settings = {"jvm_properties": properties} if properties else {}
    return {"settings": settings, "errors": errors}


# provider shorthand -> (class, the JPA level it implements on WAS 9)
JPA_PROVIDERS = {
    "eclipselink": ("org.eclipse.persistence.jpa.PersistenceProvider", "2.1"),
    "wsjpa": ("com.ibm.websphere.persistence.PersistenceProviderImpl", "2.0"),
    "openjpa": ("org.apache.openjpa.persistence.PersistenceProviderImpl", "2.0"),
}
JPA_KEYS = ("spec_level", "provider", "jta_datasource", "non_jta_datasource")


def jpa_settings(jpa, datasources):
    """The JPA defaults of every server, and the JPA level of the target.

    datasources is the model's datasource list, so a JTA default naming a
    non-transactional datasource - or the reverse - is refused here: WAS binds
    it, and the persistence unit then writes outside the transaction, or
    enlists what was meant to stay out of it.
    """
    jpa = jpa or {}
    errors = []
    warnings = []
    for key in sorted(jpa):
        if key not in JPA_KEYS:
            errors.append("jpa: %s is not one of %s" % (key, ", ".join(JPA_KEYS)))

    level = jpa.get("spec_level")
    if level is not None:
        level = str(level)
        if level not in ("2.0", "2.1"):
            errors.append("jpa.spec_level %r is not 2.0 or 2.1" % level)

    attrs = {}
    provider = jpa.get("provider")
    if provider:
        if provider in JPA_PROVIDERS:
            klass, implements = JPA_PROVIDERS[provider]
            if level and level != implements:
                errors.append("jpa.provider %s implements JPA %s, and spec_level is %s: "
                              "the server would start, and every persistence unit fail"
                              % (provider, implements, level))
        else:
            klass = str(provider)
            warnings.append("jpa.provider %s is a third-party class: it must implement "
                            "the JPA level of the target" % klass)
        attrs["defaultPersistenceProvider"] = klass

    by_jndi = dict((d.get("jndi_name"), d) for d in datasources or [] if d.get("jndi_name"))
    requires = []
    for key, attribute, transactional in (
            ("jta_datasource", "defaultJtaDataSourceJndiName", True),
            ("non_jta_datasource", "defaultNonJtaDataSourceJndiName", False)):
        jndi = jpa.get(key)
        if not jndi:
            continue
        attrs[attribute] = str(jndi)
        requires.append(str(jndi))
        declared = by_jndi.get(jndi)
        if declared is not None:
            is_tx = str(declared.get("transactional", "true")).lower() != "false"
            if is_tx != transactional:
                errors.append(
                    "jpa.%s is %s, declared %s: a %s default must be a %s datasource"
                    % (key, jndi, "transactional" if is_tx else "non-transactional",
                       "JTA" if transactional else "non-JTA",
                       "transactional" if transactional else "non-transactional"))
    if jpa.get("jta_datasource") and jpa.get("jta_datasource") == jpa.get("non_jta_datasource"):
        errors.append("jpa: one datasource cannot be both the JTA and the non-JTA default")

    settings = {}
    if attrs:
        settings["components"] = {"JavaPersistenceAPIService": attrs}
    if level and level in ("2.0", "2.1"):
        settings["jpa_spec_level"] = level
    if requires:
        settings["requires_datasources"] = requires
    return {"settings": settings, "errors": errors, "warnings": warnings}


def _flag(errors, name, value):
    """A boolean as WAS shows it, "true" or "false"; None when it is neither."""
    if isinstance(value, bool):
        return "true" if value else "false"
    text = str(value).strip().lower()
    if text in ("true", "false"):
        return text
    errors.append("%s: %r is not true or false" % (name, value))
    return None


def _unknown(errors, prefix, declared, known):
    for key in sorted(declared):
        if key not in known:
            errors.append("%s: %s is not one of %s" % (prefix, key, ", ".join(known)))


def _absolute(errors, name, value):
    text = str(value).rstrip("/")
    if not text.startswith("/"):
        errors.append("%s %r is not an absolute path" % (name, value))
        return None
    return text


# ---------------------------------------------------------------------------
# Dynamic cache - family 5
# ---------------------------------------------------------------------------

DYNACACHE_KEYS = ("enabled", "cache_size", "default_priority", "disk_offload",
                  "disk_offload_root", "flush_to_disk_on_stop", "servlet_caching")


def dynacache_settings(dc):
    """The dynamic cache service of every server, and servlet caching.

    disk_offload_root is a root: each server offloads to
    <root>/{node}/{server}. Members sharing one offload directory would
    overwrite each other's cache files - and WAS accepts the shared path.
    """
    dc = dc or {}
    errors = []
    warnings = []
    _unknown(errors, "dynamic_cache", dc, DYNACACHE_KEYS)
    cache = {}
    enabled = None
    if "enabled" in dc:
        enabled = _flag(errors, "dynamic_cache.enabled", dc["enabled"])
        if enabled:
            cache["enable"] = enabled
    if "cache_size" in dc:
        size = _count(errors, "dynamic_cache.cache_size", dc["cache_size"], 1)
        if size is not None:
            cache["cacheSize"] = str(size)
    if "default_priority" in dc:
        priority = _count(errors, "dynamic_cache.default_priority", dc["default_priority"], 1)
        if priority is not None:
            if priority > 255:
                errors.append("dynamic_cache.default_priority %d is above 255" % priority)
            else:
                cache["defaultPriority"] = str(priority)
    offload = None
    if "disk_offload" in dc:
        offload = _flag(errors, "dynamic_cache.disk_offload", dc["disk_offload"])
        if offload:
            cache["enableDiskOffload"] = offload
    for key in ("disk_offload_root", "flush_to_disk_on_stop"):
        if key in dc and offload != "true":
            errors.append("dynamic_cache.%s without disk_offload: true - WAS would keep "
                          "it and never use it" % key)
    if dc.get("disk_offload_root") and offload == "true":
        root = _absolute(errors, "dynamic_cache.disk_offload_root", dc["disk_offload_root"])
        if root:
            cache["diskOffloadLocation"] = "%s/{node}/{server}" % root
    if "flush_to_disk_on_stop" in dc and offload == "true":
        flush = _flag(errors, "dynamic_cache.flush_to_disk_on_stop", dc["flush_to_disk_on_stop"])
        if flush:
            cache["flushToDiskOnStop"] = flush
    if enabled == "false" and len(cache) > 1:
        errors.append("dynamic_cache: settings declared with enabled: false - the service "
                      "would not start, and none of them would apply")

    components = {}
    if cache:
        components["DynamicCache"] = cache
    if "servlet_caching" in dc:
        servlet = _flag(errors, "dynamic_cache.servlet_caching", dc["servlet_caching"])
        if servlet == "true" and enabled == "false":
            errors.append("dynamic_cache.servlet_caching needs the dynamic cache service, "
                          "and enabled is false")
        if servlet == "true":
            warnings.append("dynamic_cache.servlet_caching caches nothing until an "
                            "application ships a cachespec.xml")
        if servlet:
            components["WebContainer"] = {"enableServletCaching": servlet}
    settings = {"components": components} if components else {}
    return {"settings": settings, "errors": errors, "warnings": warnings}


# ---------------------------------------------------------------------------
# Logging and trace - family 5
# ---------------------------------------------------------------------------

LOGGING_MODES = ("basic", "hpel")
LOGGING_COMMON = ("mode", "trace_spec")
LOGGING_HPEL = ("repository_root", "log_max_size", "log_max_age", "trace_max_size", "text_log")
LOGGING_BASIC = ("trace_file_size", "trace_backups")
TRACE_LEVELS = ("all", "finest", "finer", "fine", "detail", "config", "info", "audit",
                "warning", "severe", "fatal", "off")
_TRACE_PART = re.compile(r"^[A-Za-z0-9_.$*\-/]+=(%s)$" % "|".join(TRACE_LEVELS))
_TRACE_LEGACY = re.compile(r"^[A-Za-z0-9_.$*\-/]+=[a-z]+=(enabled|disabled)$")


def _trace_spec(errors, warnings, spec):
    spec = str(spec).strip()
    for part in spec.split(":"):
        if not (_TRACE_PART.match(part) or _TRACE_LEGACY.match(part)):
            errors.append("logging.trace_spec: %r is not <component>=<level>, the level "
                          "one of %s" % (part, ", ".join(TRACE_LEVELS)))
        elif part.startswith("*=") and part.split("=")[1] in ("all", "finest", "finer", "fine"):
            warnings.append("logging.trace_spec %s traces every component of every "
                            "server of the target, from its next start" % part)
    return spec


def _hours(errors, name, value):
    text = str(value).strip()
    if text.isdigit():
        hours = int(text)
    else:
        seconds = _seconds(errors, name, value)
        if seconds is None:
            return None
        if seconds % 3600:
            errors.append("%s: %r is not a whole number of hours" % (name, value))
            return None
        hours = seconds // 3600
    if hours < 1:
        errors.append("%s: %r is under an hour" % (name, value))
        return None
    return hours


def logging_settings(lg):
    """The log and trace mode of every server, and its settings.

    hpel switches the High Performance Extensible Logging service on and the
    basic RAS logging service off - IBM's procedure, both flags in one change,
    applied at the next start. A setting of the other mode is refused rather
    than written: WAS keeps it, and it never applies.
    """
    lg = lg or {}
    errors = []
    warnings = []
    if not lg:
        return {"settings": {}, "errors": errors, "warnings": warnings}
    _unknown(errors, "logging", lg, LOGGING_COMMON + LOGGING_HPEL + LOGGING_BASIC)
    mode = lg.get("mode")
    if mode not in LOGGING_MODES:
        errors.append("logging.mode is %r: declare basic or hpel - the trace "
                      "specification lives in a different place in each" % (mode,))
        return {"settings": {}, "errors": errors, "warnings": warnings}
    other = LOGGING_BASIC if mode == "hpel" else LOGGING_HPEL
    for key in sorted(lg):
        if key in other:
            errors.append("logging.%s belongs to the other mode, and mode is %s: WAS "
                          "would keep it and never use it" % (key, mode))

    components = {}
    spec = _trace_spec(errors, warnings, lg["trace_spec"]) if lg.get("trace_spec") else None
    if mode == "hpel":
        components["HighPerformanceExtensibleLogging"] = {"enable": "true"}
        components["RASLoggingService"] = {"enable": "false"}
        if spec:
            components["HighPerformanceExtensibleLogging"]["startupTraceSpec"] = spec
        log, trace = {}, {}
        if lg.get("repository_root"):
            root = _absolute(errors, "logging.repository_root", lg["repository_root"])
            if root:
                log["dataDirectory"] = trace["dataDirectory"] = "%s/{node}/{server}" % root
        if "log_max_size" in lg:
            size = _count(errors, "logging.log_max_size", lg["log_max_size"], 1)
            if size is not None:
                log.update(purgeBySizeEnabled="true", purgeMaxSize=str(size))
        if "log_max_age" in lg:
            hours = _hours(errors, "logging.log_max_age", lg["log_max_age"])
            if hours is not None:
                log.update(purgeByTimeEnabled="true", purgeMinTime=str(hours))
        if "trace_max_size" in lg:
            size = _count(errors, "logging.trace_max_size", lg["trace_max_size"], 1)
            if size is not None:
                trace.update(purgeBySizeEnabled="true", purgeMaxSize=str(size))
        if log:
            components["HPELLog"] = log
        if trace:
            components["HPELTrace"] = trace
        if "text_log" in lg:
            text = _flag(errors, "logging.text_log", lg["text_log"])
            if text:
                components["HPELTextLog"] = {"enabled": text}
    else:
        components["HighPerformanceExtensibleLogging"] = {"enable": "false"}
        components["RASLoggingService"] = {"enable": "true"}
        if spec:
            components["TraceService"] = {"startupTraceSpecification": spec}
        trace_log = {}
        if "trace_file_size" in lg:
            size = _count(errors, "logging.trace_file_size", lg["trace_file_size"], 1)
            if size is not None:
                trace_log["rolloverSize"] = str(size)
        if "trace_backups" in lg:
            backups = _count(errors, "logging.trace_backups", lg["trace_backups"], 1)
            if backups is not None:
                trace_log["maxNumberOfBackupFiles"] = str(backups)
        if trace_log:
            components["TraceLog"] = trace_log
    return {"settings": {"components": components}, "errors": errors, "warnings": warnings}


# ---------------------------------------------------------------------------
# PMI - family 6
# ---------------------------------------------------------------------------

PMI_KEYS = ("enabled", "statistic_set", "synchronized_update")
PMI_SETS = ("none", "basic", "extended", "all")


def pmi_settings(pmi):
    """The Performance Monitoring Infrastructure of every server."""
    pmi = pmi or {}
    errors = []
    warnings = []
    _unknown(errors, "pmi", pmi, PMI_KEYS)
    attrs = {}
    enabled = None
    if "enabled" in pmi:
        enabled = _flag(errors, "pmi.enabled", pmi["enabled"])
        if enabled:
            attrs["enable"] = enabled
    if "statistic_set" in pmi:
        chosen = str(pmi["statistic_set"]).lower()
        if chosen == "custom":
            errors.append("pmi.statistic_set custom needs a counter-by-counter "
                          "specification this role does not carry - choose one of %s"
                          % ", ".join(PMI_SETS))
        elif chosen not in PMI_SETS:
            errors.append("pmi.statistic_set %r is not one of %s"
                          % (pmi["statistic_set"], ", ".join(PMI_SETS)))
        else:
            if enabled == "false":
                errors.append("pmi.statistic_set with enabled: false - no statistic "
                              "would be collected")
            if chosen == "all":
                warnings.append("pmi.statistic_set all collects every counter on every "
                                "server, at a measurable cost: keep it for a diagnosis")
            attrs["statisticSet"] = chosen
    if "synchronized_update" in pmi:
        sync = _flag(errors, "pmi.synchronized_update", pmi["synchronized_update"])
        if sync == "true":
            warnings.append("pmi.synchronized_update serialises every counter update")
        if sync:
            attrs["synchronizedUpdate"] = sync
    settings = {"components": {"PMIService": attrs}} if attrs else {}
    return {"settings": settings, "errors": errors, "warnings": warnings}


# ---------------------------------------------------------------------------
# Security - family 5
# ---------------------------------------------------------------------------

REGISTRY_TYPES = {
    "federated": "WIMUserRegistry",
    "ldap": "LDAPUserRegistry",
    "localos": "LocalOSUserRegistry",
    "custom": "CustomUserRegistry",
}
SECURITY_KEYS = ("admin_security", "app_security", "java2_security", "registry")
REGISTRY_KEYS = ("type", "primary_admin_id", "realm", "ldap", "custom")
LDAP_KEYS = ("server_type", "hosts", "base_dn", "bind_dn", "bind_password_env", "ssl",
             "ssl_config", "search_timeout", "reuse_connection", "allow_plaintext")
LDAP_SERVER_TYPES = ("IBM_DIRECTORY_SERVER", "ACTIVE_DIRECTORY", "IPLANET", "NETSCAPE", "NDS",
                     "DOMINO502", "SECUREWAY", "CUSTOM")
DEFAULT_REALM = "defaultWIMFileBasedRealm"


def _ldap_hosts(errors, hosts, ssl):
    out = []
    for entry in hosts or []:
        if isinstance(entry, dict):
            host, port = entry.get("host"), entry.get("port", 636 if ssl else 389)
        else:
            host, _, port = str(entry).partition(":")
            port = port or (636 if ssl else 389)
        if not host:
            errors.append("security.registry.ldap.hosts: %r is not host or host:port" % (entry,))
            continue
        number = _count(errors, "security.registry.ldap.hosts %s port" % host, port, 1)
        if number is not None:
            out.append({"host": str(host), "port": str(number)})
    return out


def security_settings(sec):
    """Global security and the active user registry.

    One of the four registry types WAS offers - federated repositories, a
    standalone LDAP, the local operating system, a custom registry - is
    configured and made the active one. What WAS accepts here and should not
    locks people out or lets them in: refused before any session.
    """
    sec = sec or {}
    errors = []
    warnings = []
    _unknown(errors, "security", sec, SECURITY_KEYS)
    settings = {}

    if _flag(errors, "security.admin_security", sec.get("admin_security", True)) == "false":
        errors.append("security.admin_security false: WAS accepts it, and every "
                      "administrative request is then served unauthenticated. This "
                      "role does not turn administrative security off")
    settings["admin_security"] = "true"
    for key in ("app_security", "java2_security"):
        if key in sec:
            value = _flag(errors, "security." + key, sec[key])
            if value:
                settings[key] = value
    if settings.get("java2_security") == "true":
        warnings.append("security.java2_security: an application that does not declare "
                        "the permissions it uses fails at run time, not at deployment")

    registry = sec.get("registry") or {}
    _unknown(errors, "security.registry", registry, REGISTRY_KEYS)
    kind = registry.get("type")
    if kind not in REGISTRY_TYPES:
        errors.append("security.registry.type is %r: one of %s"
                      % (kind, ", ".join(sorted(REGISTRY_TYPES))))
        return {"settings": settings, "errors": errors, "warnings": warnings}
    for other in ("ldap", "custom"):
        if other in registry and other != kind:
            errors.append("security.registry.%s is declared and the type is %s: it would "
                          "be ignored" % (other, kind))
    admin_id = registry.get("primary_admin_id")
    if not admin_id:
        errors.append("security.registry.primary_admin_id is missing: a registry made "
                      "active without an administrator that exists in it locks every "
                      "administrator out at the next start")
    out = {"type": REGISTRY_TYPES[kind], "attributes": {"primaryAdminId": str(admin_id or "")}}

    if kind == "federated":
        out["attributes"]["realm"] = str(registry.get("realm") or DEFAULT_REALM)
    elif "realm" in registry:
        errors.append("security.registry.realm is the federated repositories' realm "
                      "name; a %s registry names its realm itself" % kind)

    if kind == "ldap":
        ldap = registry.get("ldap") or {}
        _unknown(errors, "security.registry.ldap", ldap, LDAP_KEYS)
        ssl = _flag(errors, "security.registry.ldap.ssl", ldap.get("ssl", False))
        server_type = str(ldap.get("server_type", "")).upper()
        if server_type not in LDAP_SERVER_TYPES:
            errors.append("security.registry.ldap.server_type %r is not one of %s"
                          % (ldap.get("server_type"), ", ".join(LDAP_SERVER_TYPES)))
        if not ldap.get("base_dn"):
            errors.append("security.registry.ldap.base_dn is missing: every search "
                          "would start at the root of the directory")
        hosts = _ldap_hosts(errors, ldap.get("hosts"), ssl == "true")
        if not hosts:
            errors.append("security.registry.ldap.hosts is empty")
        if ssl != "true" and not ldap.get("allow_plaintext"):
            errors.append("security.registry.ldap.ssl is false: the bind password and "
                          "every user's password would cross the network in clear. Set "
                          "ssl: true, or allow_plaintext: true to say it is deliberate")
        if ldap.get("bind_dn") and not ldap.get("bind_password_env"):
            errors.append("security.registry.ldap.bind_dn without bind_password_env: "
                          "the bind password comes from a credential, by the name of "
                          "the variable that carries it")
        attrs = out["attributes"]
        attrs.update(type=server_type, baseDN=str(ldap.get("base_dn", "")),
                     bindDN=str(ldap.get("bind_dn", "")), sslEnabled=ssl or "false")
        if ldap.get("ssl_config"):
            attrs["sslConfig"] = str(ldap["ssl_config"])
        if "search_timeout" in ldap:
            seconds = _seconds(errors, "security.registry.ldap.search_timeout", ldap["search_timeout"])
            if seconds is not None:
                attrs["searchTimeout"] = str(seconds)
        if "reuse_connection" in ldap:
            reuse = _flag(errors, "security.registry.ldap.reuse_connection", ldap["reuse_connection"])
            if reuse:
                attrs["reuseConnection"] = reuse
        out["hosts"] = hosts
        if ldap.get("bind_password_env"):
            settings["bind_password_env"] = str(ldap["bind_password_env"])

    if kind == "custom":
        custom = registry.get("custom") or {}
        _unknown(errors, "security.registry.custom", custom, ("class", "properties"))
        if not custom.get("class"):
            errors.append("security.registry.custom.class is missing")
        out["attributes"]["customRegistryClassName"] = str(custom.get("class", ""))
        out["properties"] = dict((str(k), str(v)) for k, v in (custom.get("properties") or {}).items())
        warnings.append("security.registry custom: the class must be on the class path "
                        "of the deployment manager and of every node")

    settings["registry"] = out
    return {"settings": settings, "errors": errors, "warnings": warnings}


# ---------------------------------------------------------------------------
# SSL - family 5
# ---------------------------------------------------------------------------

# What IBM's createSSLConfig reference lists, less what negotiates below TLS
# 1.2. A comma-separated list is accepted from 9.0.5.11, of TLS versions only.
SSL_PROTOCOLS = ("TLSv1.2", "TLSv1.3", "TLSv1.2,TLSv1.3")
SSL_REFUSED = ("SSL", "SSLv2", "SSLv3", "SSL_TLS", "SSL_TLSv2", "TLS", "TLSv1", "TLSv1.1")
SSL_LEVELS = ("HIGH", "MEDIUM")
SSL_CLIENT_AUTH = ("none", "supported", "required")
SSL_CONFIG_KEYS = ("alias", "scope", "keystore", "truststore", "protocol",
                   "security_level", "client_auth", "state")
SIGNER_KEYS = ("alias", "host", "port", "truststore", "scope", "state")
# Created with the profile, and what every endpoint without its own falls back to.
SSL_DEFAULT_CONFIGS = ("CellDefaultSSLSettings", "NodeDefaultSSLSettings", "XDADefaultSSLSettings")


def _ssl_scope(errors, name, scope):
    if scope in (None, "cell"):
        return {"type": "cell"}
    if isinstance(scope, dict) and scope.get("node"):
        return {"type": "node", "node": str(scope["node"])}
    errors.append("%s.scope %r is cell or {node: <name>}" % (name, scope))
    return None


def ssl_settings(ssl):
    """SSL configurations, and the signers their trust stores need."""
    ssl = ssl or {}
    errors = []
    warnings = []
    _unknown(errors, "ssl", ssl, ("configs", "signers"))
    configs = []
    seen = []
    for index, item in enumerate(ssl.get("configs") or []):
        _unknown(errors, "ssl.configs[%d]" % index, item, SSL_CONFIG_KEYS)
        alias = item.get("alias")
        if not alias:
            errors.append("ssl.configs[%d] has no alias" % index)
            continue
        name = "ssl config %s" % alias
        scope = _ssl_scope(errors, name, item.get("scope"))
        key = (alias, json.dumps(scope, sort_keys=True))
        if key in seen:
            errors.append("%s is declared twice at one scope" % name)
        seen.append(key)
        if item.get("state", "present") == "absent":
            if alias in SSL_DEFAULT_CONFIGS:
                errors.append("%s is a default the profile created, which every "
                              "endpoint without its own configuration uses: it is "
                              "modified, never deleted" % name)
            configs.append({"alias": alias, "scope": scope, "state": "absent"})
            continue
        protocol = str(item.get("protocol", "TLSv1.2"))
        if protocol in SSL_REFUSED:
            errors.append("%s: protocol %s accepts a version of SSL or TLS below 1.2, "
                          "which WAS negotiates if the peer asks for it" % (name, protocol))
        elif protocol not in SSL_PROTOCOLS:
            errors.append("%s: protocol %r is not one of %s" % (name, protocol, " | ".join(SSL_PROTOCOLS)))
        level = str(item.get("security_level", "HIGH")).upper()
        if level == "LOW":
            errors.append("%s: security_level LOW enables export-grade and null ciphers" % name)
        elif level == "CUSTOM":
            errors.append("%s: security_level CUSTOM needs a cipher list this role does "
                          "not carry - HIGH or MEDIUM" % name)
        elif level not in SSL_LEVELS:
            errors.append("%s: security_level %r is not HIGH or MEDIUM" % (name, level))
        auth = str(item.get("client_auth", "none")).lower()
        if auth not in SSL_CLIENT_AUTH:
            errors.append("%s: client_auth %r is not one of %s" % (name, auth, ", ".join(SSL_CLIENT_AUTH)))
        if not item.get("keystore") or not item.get("truststore"):
            errors.append("%s needs a keystore and a truststore" % name)
        configs.append({
            "alias": alias, "scope": scope, "state": "present",
            "keystore": str(item.get("keystore", "")), "truststore": str(item.get("truststore", "")),
            "protocol": protocol, "security_level": level,
            "client_auth": "true" if auth == "required" else "false",
            "client_auth_supported": "true" if auth in ("supported", "required") else "false",
        })

    signers = []
    for index, item in enumerate(ssl.get("signers") or []):
        _unknown(errors, "ssl.signers[%d]" % index, item, SIGNER_KEYS)
        if not item.get("alias"):
            errors.append("ssl.signers[%d] has no alias" % index)
            continue
        name = "signer %s" % item["alias"]
        scope = _ssl_scope(errors, name, item.get("scope"))
        state = item.get("state", "present")
        default_store = "CellDefaultTrustStore" if (scope or {}).get("type") == "cell" \
            else "NodeDefaultTrustStore"
        signer = {"alias": str(item["alias"]), "scope": scope, "state": state,
                  "truststore": str(item.get("truststore") or default_store)}
        if state == "present":
            if not item.get("host") or not item.get("port"):
                errors.append("%s needs the host and port it is retrieved from" % name)
            else:
                port = _count(errors, name + ".port", item["port"], 1)
                signer.update(host=str(item["host"]), port=str(port))
        signers.append(signer)
    return {"settings": {"configs": configs, "signers": signers},
            "errors": errors, "warnings": warnings}


# ---------------------------------------------------------------------------
# Web services policy sets - family 1
# ---------------------------------------------------------------------------

POLICY_SET_KEYS = ("name", "from_default", "copy_of", "description", "policies", "state")


def _policy_value(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def policy_set_settings(policy_sets):
    """Policy sets: imported from the product's defaults, or copied from one
    and adjusted. Attaching them is the application deployment's business."""
    errors = []
    warnings = []
    out = []
    declared = []
    items = list(policy_sets or [])
    for index, item in enumerate(items):
        name = item.get("name")
        if not name:
            errors.append("policy_sets[%d] has no name" % index)
            continue
        label = "policy set %s" % name
        _unknown(errors, label, item, POLICY_SET_KEYS)
        if name in declared:
            errors.append("%s is declared twice" % label)
        declared.append(name)
        if item.get("state", "present") == "absent":
            out.append({"name": name, "state": "absent"})
            continue
        source = item.get("from_default")
        copy_of = item.get("copy_of")
        if bool(source) == bool(copy_of):
            errors.append("%s: one of from_default (import a product default as it is) "
                          "or copy_of (copy a set, then adjust the copy)" % label)
        if source and source != name:
            errors.append("%s: from_default imports %s under its own name - to rename "
                          "or adjust it, import it, then declare a copy_of it" % (label, source))
        policies = item.get("policies") or {}
        if source and policies:
            errors.append("%s: policies on an imported default. Adjust a copy - a "
                          "default is what the next import puts back" % label)
        if copy_of:
            deleted = [o["name"] for o in out if o["state"] == "absent"]
            later = [i.get("name") for i in items[index + 1:]]
            if copy_of in deleted:
                errors.append("%s copies %s, which this declaration deletes" % (label, copy_of))
            elif copy_of in later:
                errors.append("%s copies %s, declared after it: declare the source first"
                              % (label, copy_of))
        rendered = {}
        for policy_type in sorted(policies):
            rendered[policy_type] = dict((str(k), _policy_value(v))
                                         for k, v in (policies[policy_type] or {}).items())
        entry = {"name": name, "state": "present", "policies": rendered}
        if source:
            entry["from_default"] = str(source)
        if copy_of:
            entry["copy_of"] = str(copy_of)
        if "description" in item:
            entry["description"] = str(item["description"])
        out.append(entry)
    return {"settings": {"policy_sets": out}, "errors": errors, "warnings": warnings}


class FilterModule(object):
    def filters(self):
        return {
            "cdi_settings": cdi_settings,
            "dynacache_settings": dynacache_settings,
            "ejb_container_settings": ejb_container_settings,
            "jdbc_groups": jdbc_groups,
            "jms_groups": jms_groups,
            "jpa_settings": jpa_settings,
            "library_groups": library_groups,
            "logging_settings": logging_settings,
            "pmi_settings": pmi_settings,
            "policy_set_settings": policy_set_settings,
            "security_settings": security_settings,
            "sibus_specs": sibus_specs,
            "ssl_settings": ssl_settings,
            "to_seconds": to_seconds,
            "transaction_settings": transaction_settings,
        }
