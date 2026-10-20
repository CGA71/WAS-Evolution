# -*- coding: utf-8 -*-
"""A fake WAS cell, persisted to disk, for the CI simulation.

It implements only the AdminConfig / AdminControl / AdminTask / AdminApp surface
the handlers actually call, and it keeps its state in a JSON file inside the
pod. Persistence is the point: it is what makes idempotency observable rather
than asserted. Run the same play twice and the second run must report
changed=false, because the fake cell remembers the first.

Deliberately strict. Where the real wsadmin would tolerate something odd, this
raises, so a handler bug surfaces in CI instead of on a cell.
"""

import json
import os

STATE_PATH = os.environ.get("WAS_SIM_STATE", "/opt/exploit/was-sim-state.json")


def _load():
    if not os.path.exists(STATE_PATH):
        return {"clusters": {}, "next_id": 1, "saved": True, "syncs": 0}
    with open(STATE_PATH) as handle:
        return json.load(handle)


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


class FakeAdminConfig(object):
    """The configuration repository."""

    def __init__(self):
        self.state = _load()

    # -- reads ------------------------------------------------------------

    def list(self, config_type):
        if config_type != "ServerCluster":
            # Only what the handlers need is implemented. An unimplemented type
            # is a bug in the simulation, not something to paper over.
            raise NotImplementedError(
                "fake AdminConfig.list does not know type %r" % config_type
            )
        return "\n".join(sorted(self.state["clusters"].keys()))

    def showAttribute(self, config_id, attribute):
        cluster = self.state["clusters"].get(config_id)
        if cluster is None:
            raise KeyError("no such config id: %r" % config_id)
        if attribute == "members":
            # The real AdminConfig returns a bracketed, space-separated list of
            # config ids. Reproduced so the handler parsing is exercised.
            return "[%s]" % " ".join(cluster.get("member_ids", []))
        if attribute not in cluster:
            raise KeyError("no attribute %r on %r" % (attribute, config_id))
        return cluster[attribute]

    # -- writes -----------------------------------------------------------

    def modify(self, config_id, attributes):
        cluster = self.state["clusters"].get(config_id)
        if cluster is None:
            raise KeyError("no such config id: %r" % config_id)
        for pair in attributes:
            key, value = pair[0], pair[1]
            cluster[key] = value
        self.state["saved"] = False
        _store(self.state)

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
                del self.state["clusters"][config_id]
                self.state["saved"] = False
                _store(self.state)
                return
        raise KeyError("no cluster named %r to delete" % name)


class FakeAdminTask(object):
    def __init__(self, config):
        self.config = config

    @staticmethod
    def _named(args, flag):
        """Pull a value out of the wsadmin-style flat argument list."""
        for index, item in enumerate(args):
            if item == flag:
                return args[index + 1]
        raise ValueError("expected %s in %r" % (flag, args))

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
