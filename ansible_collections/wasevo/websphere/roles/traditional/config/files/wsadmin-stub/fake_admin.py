# -*- coding: utf-8 -*-
"""A fake WAS cell, persisted to disk, for the CI simulation.

It implements only the AdminConfig / AdminControl / AdminTask / AdminApp surface
the handlers actually call, and it keeps its state in a JSON file inside the
pod. Persistence is the point: it is what makes idempotency observable rather
than asserted. Run the same play twice and the second run must report
changed=false, because the fake cell remembers the first.

Deliberately strict. Where the real wsadmin would tolerate something odd, this
raises, so a handler bug surfaces in CI instead of on a cell. Three rules it
enforces that WAS enforces late or not at all:

* ``createCluster`` on a cluster that exists is a handler that failed to plan.
* ``createClusterMember`` must carry ``-firstMember`` on the first member of a
  cluster and must NOT carry it on any later one. The real API is just as
  strict; getting it wrong is the easiest way to write this handler.
* two servers on one node cannot claim the same port. WAS lets you save that
  configuration and the second server then fails to start, hours later, with
  an error about an address already in use. Here it raises at creation, which
  is the whole reason ``genUniquePorts`` defaults to true for a vertical
  cluster.
"""

import json
import os

STATE_PATH = os.environ.get("WAS_SIM_STATE", "/opt/exploit/was-sim-state.json")

# Where generated ports start. Far enough from the profile port bases that a
# collision in the simulation means a bug here, not an unlucky overlap.
FIRST_GENERATED_PORT = 9080

# The endpoints a server template carries that matter to this simulation.
# Keyed as serverindex.xml names them, because that is what the handler and
# the inventory both use.
TEMPLATE_ENDPOINTS = [
    "WC_defaulthost",
    "BOOTSTRAP_ADDRESS",
    "SOAP_CONNECTOR_ADDRESS",
]

EMPTY = {
    "clusters": {},
    "members": {},
    "indexes": {},
    "entries": {},
    "specials": {},
    "ports": {},
    "next_id": 1,
    "next_port": FIRST_GENERATED_PORT,
    "saved": True,
    "syncs": 0,
}


def _load():
    if not os.path.exists(STATE_PATH):
        return dict((key, _copy(value)) for key, value in EMPTY.items())
    with open(STATE_PATH) as handle:
        state = json.load(handle)
    # A state file written before the member handler existed has no member
    # keys. Filling them in beats refusing to run on it.
    for key, value in EMPTY.items():
        state.setdefault(key, _copy(value))
    return state


def _copy(value):
    return dict(value) if isinstance(value, dict) else value


def _store(state):
    directory = os.path.dirname(STATE_PATH)
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w") as handle:
        json.dump(state, handle, indent=2, sort_keys=True)
    # os.replace, not os.rename: rename refuses an existing destination on
    # Windows, so the first write succeeded and every later one raised. The CI
    # runs on Linux where rename would have worked, which is exactly the kind
    # of bug that only shows up once someone runs the simulation on a laptop.
    os.replace(tmp, STATE_PATH)


def _parse_step(raw):
    """Parse a wsadmin step: "[-flag value -flag value]" -> dict.

    AdminTask takes its arguments either as a bracketed flat string or as a
    list of them. The member handler uses the named-step form, which is what
    the WAS documentation uses for createClusterMember, so that is what this
    parses.
    """
    inner = (raw or "").strip()
    if inner.startswith("[") and inner.endswith("]"):
        inner = inner[1:-1]
    tokens = inner.split()
    parsed = {}
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if not token.startswith("-"):
            raise ValueError("expected a -flag in %r, got %r" % (raw, token))
        if index + 1 < len(tokens) and not tokens[index + 1].startswith("-"):
            parsed[token] = tokens[index + 1]
            index += 2
        else:
            parsed[token] = "true"
            index += 1
    return parsed


class FakeAdminConfig(object):
    """The configuration repository."""

    def __init__(self):
        self.state = _load()

    # -- ids ---------------------------------------------------------------

    def _next(self, kind, name):
        config_id = "%s(cells/TestCell/%s|%s.xml#%s_%d)" % (
            name, kind, kind, kind, self.state["next_id"],
        )
        self.state["next_id"] += 1
        return config_id

    # -- reads ------------------------------------------------------------

    def list(self, config_type):
        if config_type != "ServerCluster":
            # Only what the handlers need is implemented. An unimplemented type
            # is a bug in the simulation, not something to paper over.
            raise NotImplementedError(
                "fake AdminConfig.list does not know type %r" % config_type
            )
        return "\n".join(sorted(self.state["clusters"].keys()))

    def getid(self, pattern):
        """Containment path lookup. Only /Node:<node>/ServerIndex:/ is needed."""
        parts = [p for p in pattern.strip("/").split("/") if p]
        if len(parts) != 2 or not parts[0].startswith("Node:") or parts[1] != "ServerIndex:":
            raise NotImplementedError(
                "fake AdminConfig.getid does not know pattern %r" % pattern
            )
        node = parts[0].split(":", 1)[1]
        for index_id, index in self.state["indexes"].items():
            if index["node"] == node:
                return index_id
        # The real getid returns an empty string for a path that matches
        # nothing, and the handler treats that as "no ports to read".
        return ""

    def showAttribute(self, config_id, attribute):
        for store, reader in (
            ("clusters", self._show_cluster),
            ("members", self._show_member),
            ("indexes", self._show_index),
            ("entries", self._show_entry),
            ("specials", self._show_special),
            ("ports", self._show_port),
        ):
            if config_id in self.state[store]:
                return reader(self.state[store][config_id], attribute, config_id)
        raise KeyError("no such config id: %r" % config_id)

    @staticmethod
    def _attribute(obj, attribute, config_id):
        if attribute not in obj:
            raise KeyError("no attribute %r on %r" % (attribute, config_id))
        return obj[attribute]

    def _show_cluster(self, cluster, attribute, config_id):
        if attribute == "members":
            # The real AdminConfig returns a bracketed, space-separated list of
            # config ids. Reproduced so the handler parsing is exercised.
            return "[%s]" % " ".join(cluster.get("member_ids", []))
        return self._attribute(cluster, attribute, config_id)

    def _show_member(self, member, attribute, config_id):
        value = self._attribute(member, attribute, config_id)
        # Every AdminConfig read returns a string, including a numeric one.
        # The handler is what has to int() it, so the fake must not hand back
        # an integer and hide a missing cast.
        return str(value) if attribute == "weight" else value

    def _show_index(self, index, attribute, config_id):
        if attribute == "serverEntries":
            return "[%s]" % " ".join(index.get("entry_ids", []))
        return self._attribute(index, attribute, config_id)

    def _show_entry(self, entry, attribute, config_id):
        if attribute == "specialEndpoints":
            return "[%s]" % " ".join(entry.get("special_ids", []))
        return self._attribute(entry, attribute, config_id)

    def _show_special(self, special, attribute, config_id):
        return self._attribute(special, attribute, config_id)

    def _show_port(self, port, attribute, config_id):
        value = self._attribute(port, attribute, config_id)
        return str(value) if attribute == "port" else value

    # -- writes -----------------------------------------------------------

    def modify(self, config_id, attributes):
        for store in ("clusters", "members", "ports"):
            obj = self.state[store].get(config_id)
            if obj is None:
                continue
            for pair in attributes:
                key, value = pair[0], pair[1]
                obj[key] = value
            self.state["saved"] = False
            _store(self.state)
            return
        raise KeyError("no such config id: %r" % config_id)

    def save(self):
        self.state = _load()
        self.state["saved"] = True
        _store(self.state)

    # -- used by AdminTask ------------------------------------------------

    def _create_cluster(self, name, prefer_local):
        config_id = "%s(cells/TestCell/clusters/%s|cluster.xml#ServerCluster_%d)" % (
            name, name, self.state["next_id"],
        )
        self.state["next_id"] += 1
        self.state["clusters"][config_id] = {
            "name": name,
            "preferLocal": str(prefer_local).lower(),
            "member_ids": [],
        }
        self.state["saved"] = False
        _store(self.state)
        return config_id

    def _delete_cluster(self, name):
        for config_id, cluster in list(self.state["clusters"].items()):
            if cluster["name"] == name:
                for member_id in cluster.get("member_ids", []):
                    member = self.state["members"].pop(member_id, None)
                    if member:
                        self._drop_server_entry(member["nodeName"], member["memberName"])
                del self.state["clusters"][config_id]
                self.state["saved"] = False
                _store(self.state)
                return
        raise KeyError("no cluster named %r to delete" % name)

    def _cluster_by_name(self, name):
        for config_id, cluster in self.state["clusters"].items():
            if cluster["name"] == name:
                return config_id, cluster
        raise KeyError("no cluster named %r" % name)

    # -- the node's serverindex ------------------------------------------

    def _index_for(self, node):
        for index_id, index in self.state["indexes"].items():
            if index["node"] == node:
                return index_id
        index_id = self._next("serverindex", node)
        self.state["indexes"][index_id] = {"node": node, "entry_ids": []}
        return index_id

    def _ports_in_use(self, node):
        used = {}
        index = self.state["indexes"].get(self._index_for(node), {})
        for entry_id in index.get("entry_ids", []):
            entry = self.state["entries"][entry_id]
            for special_id in entry.get("special_ids", []):
                special = self.state["specials"][special_id]
                port = self.state["ports"][special["endPoint"]]
                used[int(port["port"])] = (entry["serverName"], special["endPointName"])
        return used

    def _add_server_entry(self, node, server, gen_unique_ports):
        """Create the serverindex entry for a new server, with its endpoints."""
        index_id = self._index_for(node)
        used = self._ports_in_use(node)

        if gen_unique_ports:
            base = self.state["next_port"]
            while any((base + offset) in used for offset in range(len(TEMPLATE_ENDPOINTS))):
                base += 10
            self.state["next_port"] = base + 10
        else:
            # Copying the template's ports is exactly what WAS does when
            # genUniquePorts is false, and on a second member of the same node
            # that is a collision.
            base = FIRST_GENERATED_PORT

        entry_id = self._next("serverentry", server)
        special_ids = []
        for offset, endpoint_name in enumerate(TEMPLATE_ENDPOINTS):
            port = base + offset
            if port in used:
                other_server, other_endpoint = used[port]
                raise RuntimeError(
                    "server %s on node %s claims port %d, which %s already "
                    "uses for %s. Two JVMs on one node cannot share a port: "
                    "WAS saves this configuration and the second server then "
                    "fails to start with an address-already-in-use error. "
                    "This is what genUniquePorts=true prevents."
                    % (server, node, port, other_server, other_endpoint)
                )
            port_id = self._next("endpoint", "%s_%s" % (server, endpoint_name))
            self.state["ports"][port_id] = {"host": "*", "port": port}
            special_id = self._next("specialendpoint", endpoint_name)
            self.state["specials"][special_id] = {
                "endPointName": endpoint_name,
                "endPoint": port_id,
            }
            special_ids.append(special_id)

        self.state["entries"][entry_id] = {
            "serverName": server,
            "nodeName": node,
            "special_ids": special_ids,
        }
        self.state["indexes"][index_id]["entry_ids"].append(entry_id)
        return entry_id

    def _drop_server_entry(self, node, server):
        index_id = self._index_for(node)
        index = self.state["indexes"][index_id]
        for entry_id in list(index["entry_ids"]):
            entry = self.state["entries"][entry_id]
            if entry["serverName"] != server:
                continue
            for special_id in entry["special_ids"]:
                special = self.state["specials"].pop(special_id)
                self.state["ports"].pop(special["endPoint"], None)
            del self.state["entries"][entry_id]
            index["entry_ids"].remove(entry_id)

    def _set_port(self, node, server, endpoint_name, port):
        index = self.state["indexes"][self._index_for(node)]
        for entry_id in index["entry_ids"]:
            entry = self.state["entries"][entry_id]
            if entry["serverName"] != server:
                continue
            for special_id in entry["special_ids"]:
                special = self.state["specials"][special_id]
                if special["endPointName"] != endpoint_name:
                    continue
                for other, (other_server, _) in self._ports_in_use(node).items():
                    if other == int(port) and other_server != server:
                        raise RuntimeError(
                            "port %s on node %s is already used by %s"
                            % (port, node, other_server)
                        )
                self.state["ports"][special["endPoint"]]["port"] = int(port)
                self.state["saved"] = False
                _store(self.state)
                return
        raise KeyError(
            "no endpoint %r on server %r of node %r" % (endpoint_name, server, node)
        )

    def _create_member(self, cluster_name, config, first_member):
        cluster_id, cluster = self._cluster_by_name(cluster_name)
        node = config["-memberNode"]
        name = config["-memberName"]

        for member_id in cluster["member_ids"]:
            member = self.state["members"][member_id]
            if member["memberName"] == name and member["nodeName"] == node:
                raise RuntimeError(
                    "member %r already exists on node %r - the handler should "
                    "have planned no change" % (name, node)
                )

        # The API rule, enforced: -firstMember exactly once per cluster.
        if cluster["member_ids"] and first_member is not None:
            raise RuntimeError(
                "-firstMember was passed for %r, but cluster %r already has "
                "%d member(s). The real createClusterMember rejects this: the "
                "template is fixed by the first member and every later one is "
                "copied from it." % (name, cluster_name, len(cluster["member_ids"]))
            )
        if not cluster["member_ids"] and first_member is None:
            raise RuntimeError(
                "-firstMember is required when creating the first member of "
                "cluster %r: that call is what fixes the server template."
                % cluster_name
            )

        gen_unique = str(config.get("-genUniquePorts", "true")).lower() == "true"
        self._add_server_entry(node, name, gen_unique)

        member_id = self._next("clustermember", name)
        self.state["members"][member_id] = {
            "memberName": name,
            "nodeName": node,
            "weight": int(config.get("-memberWeight", 2)),
            "cluster": cluster_name,
        }
        cluster["member_ids"].append(member_id)
        self.state["saved"] = False
        _store(self.state)
        return member_id

    def _delete_member(self, cluster_name, node, name):
        cluster_id, cluster = self._cluster_by_name(cluster_name)
        for member_id in list(cluster["member_ids"]):
            member = self.state["members"][member_id]
            if member["memberName"] == name and member["nodeName"] == node:
                del self.state["members"][member_id]
                cluster["member_ids"].remove(member_id)
                self._drop_server_entry(node, name)
                self.state["saved"] = False
                _store(self.state)
                return
        raise KeyError(
            "no member %r on node %r of cluster %r" % (name, node, cluster_name)
        )


class FakeAdminTask(object):

    # A missing argument is a handler bug, so _named raises by default. An
    # argument that is genuinely optional - -firstMember - asks for None
    # explicitly, which keeps "optional" visible at the call site.
    REQUIRED = object()

    def __init__(self, config):
        self.config = config

    @classmethod
    def _named(cls, args, flag, default=REQUIRED):
        """Pull a value out of the wsadmin-style flat argument list."""
        for index, item in enumerate(args):
            if item == flag:
                return args[index + 1]
        if default is cls.REQUIRED:
            raise ValueError("expected %s in %r" % (flag, args))
        return default

    def createCluster(self, args):
        # -clusterConfig "[[<name> <preferLocal> false]]"
        raw = self._named(args, "-clusterConfig")
        inner = raw.strip().strip("[]").strip()
        parts = inner.split()
        if len(parts) < 2:
            raise ValueError("malformed -clusterConfig: %r" % raw)
        name, prefer_local = parts[0], parts[1]
        for cluster in self.config.state["clusters"].values():
            if cluster["name"] == name:
                raise RuntimeError(
                    "cluster %r already exists - the handler should have "
                    "planned no change" % name
                )
        return self.config._create_cluster(name, prefer_local)

    def deleteCluster(self, args):
        return self.config._delete_cluster(self._named(args, "-clusterName"))

    def createClusterMember(self, args):
        cluster_name = self._named(args, "-clusterName")
        config = _parse_step(self._named(args, "-memberConfig"))
        for required in ("-memberNode", "-memberName"):
            if required not in config:
                raise ValueError(
                    "expected %s inside -memberConfig %r" % (required, member_config)
                )

        raw_first = self._named(args, "-firstMember", None)
        first_member = _parse_step(raw_first) if raw_first is not None else None
        if first_member is not None and "-templateName" not in first_member \
                and "-templateServerName" not in first_member:
            raise ValueError(
                "-firstMember must name a template, either -templateName or "
                "-templateServerNode plus -templateServerName: %r" % raw_first
            )

        return self.config._create_member(cluster_name, config, first_member)

    def deleteClusterMember(self, args):
        return self.config._delete_member(
            self._named(args, "-clusterName"),
            self._named(args, "-memberNode"),
            self._named(args, "-memberName"),
        )

    def modifyServerPort(self, args):
        # modifyServerPort(<server>, '-nodeName n -endPointName e -host * -port p')
        # The handler passes it as one flat list, server name first.
        if not args or args[0].startswith("-"):
            raise ValueError("modifyServerPort expects the server name first: %r" % (args,))
        return self.config._set_port(
            self._named(args, "-nodeName"),
            args[0],
            self._named(args, "-endPointName"),
            self._named(args, "-port"),
        )


class FakeAdminControl(object):
    def __init__(self, config):
        self.config = config

    def completeObjectName(self, query):
        return ""

    def queryNames(self, query):
        if "NodeSync" in query:
            return "WebSphere:name=nodeSync,type=NodeSync,node=TestNode,*"
        return ""

    def invoke(self, mbean, operation, *args):
        if operation == "sync":
            state = _load()
            state["syncs"] = state.get("syncs", 0) + 1
            _store(state)
            return "true"
        raise NotImplementedError("fake AdminControl.invoke: %r" % operation)


class FakeAdminApp(object):
    def install(self, earfile, options):
        raise NotImplementedError(
            "was_application is scheduled for wave 1; the simulation will "
            "gain an AdminApp fake at the same time"
        )


def build():
    """Return the four globals wsadmin injects into a script."""
    config = FakeAdminConfig()
    return {
        "AdminConfig": config,
        "AdminTask": FakeAdminTask(config),
        "AdminControl": FakeAdminControl(config),
        "AdminApp": FakeAdminApp(),
    }
