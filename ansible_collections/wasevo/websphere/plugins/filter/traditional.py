# -*- coding: utf-8 -*-
# Copyright (c) 2026, neo
# GNU General Public License v3.0+
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
JMS_PROVIDERS = ("sib",)


def jms_groups(jms, default_scope, cluster_name, cell_name, default_provider="sib"):
    """Group the declared JMS resources by scope and provider.

    One module call takes one scope and one provider, so the resources are
    grouped on both. Every group also receives `known_destinations` - every
    JMS queue and topic declared anywhere, with its type - because an
    activation spec at cluster scope may listen on a queue declared at cell
    scope: WAS resolves the JNDI name through the scopes, and a check confined
    to one group would refuse a valid configuration.

    Returns {"groups": [...], "errors": [...]}.
    """
    groups = []
    by_key = {}
    errors = []
    known = {}
    jndi_owner = {}

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


class FilterModule(object):
    def filters(self):
        return {
            "jdbc_groups": jdbc_groups,
            "jms_groups": jms_groups,
            "library_groups": library_groups,
            "sibus_specs": sibus_specs,
            "to_seconds": to_seconds,
        }
