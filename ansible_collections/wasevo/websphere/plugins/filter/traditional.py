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


class FilterModule(object):
    def filters(self):
        return {
            "jdbc_groups": jdbc_groups,
            "to_seconds": to_seconds,
        }
