# -*- coding: utf-8 -*-
"""Handler for J2C authentication aliases - the credentials a datasource,
a JMS connection factory or a bus member presents to what it connects to.

CELL-WIDE, ALWAYS. An alias lives in the cell's security configuration, not in
a cluster or a server, so it takes no scope. A datasource at cluster scope
refers to it by name.

THE PASSWORD CANNOT BE COMPARED. WAS stores it encoded and returns nothing a
plan could compare against, so idempotency on the password is not something a
handler can honestly claim. The caller chooses:

    password_policy: on_create   the password is set when the alias is created
                                 and left alone afterwards. Replays report
                                 changed only for what can be compared - user
                                 and description. The default.
    password_policy: always      the password is written on every run, and
                                 every run reports changed - because it might
                                 have, and saying "unchanged" would be a guess.

Rotating a database password is therefore one replay of this role with
`always`, and nothing else.

The password never appears in what this handler returns: not in `before`, not
in `after`, so not in a diff and not in a log. It travels only in the 0600
payload file, which the module removes.

Five callables, same contract as every other handler - see cluster.py.
"""


def _aliases(AdminConfig):
    """Every alias in the cell: name -> {config_id, user, description}."""
    found = {}
    for config_id in AdminConfig.list("JAASAuthData").splitlines():
        config_id = config_id.strip()
        if not config_id:
            continue
        name = AdminConfig.showAttribute(config_id, "alias")
        found[name] = {
            "config_id": config_id,
            "user": AdminConfig.showAttribute(config_id, "userId") or "",
            "description": AdminConfig.showAttribute(config_id, "description") or "",
        }
    return found


def _public(name, entry):
    """What may be reported. Never the password."""
    return {"name": name, "user": entry["user"], "description": entry["description"]}


def read(admin, params):
    """The aliases the request names, as the cell holds them.

    Only the named ones are reported: the cell holds aliases for everything
    else it runs, and a diff that listed them all would bury the change that
    matters under the ones nobody asked about.
    """
    live = _aliases(admin["AdminConfig"])
    wanted = [a["name"] for a in params.get("aliases") or []]
    return {
        "exists": True,
        "aliases": sorted(
            [_public(n, live[n]) for n in wanted if n in live],
            key=lambda a: a["name"],
        ),
    }


def plan_present(admin, params, before):
    live = dict((a["name"], a) for a in before["aliases"])
    always = params.get("password_policy", "on_create") == "always"

    after = []
    changed = False
    for desired in params.get("aliases") or []:
        current = live.get(desired["name"])
        planned = {
            "name": desired["name"],
            "user": desired["user"],
            "description": desired.get("description", "") or "",
        }
        if current is None:
            changed = True
        elif (current["user"] != planned["user"]
              or current["description"] != planned["description"]):
            changed = True
        elif always:
            # The password is written and cannot be compared, so this run
            # reports what it does rather than what it cannot know.
            changed = True
        after.append(planned)

    return changed, {"exists": True, "aliases": sorted(after, key=lambda a: a["name"])}


def plan_absent(admin, params, before):
    doomed = [a["name"] for a in params.get("aliases") or []]
    kept = [a for a in before["aliases"] if a["name"] not in doomed]
    return len(kept) != len(before["aliases"]), {"exists": True, "aliases": kept}


def write_present(admin, params, before):
    AdminTask = admin["AdminTask"]
    live = _aliases(admin["AdminConfig"])
    always = params.get("password_policy", "on_create") == "always"

    for desired in params.get("aliases") or []:
        name = desired["name"]
        description = desired.get("description", "") or ""
        current = live.get(name)

        if current is None:
            AdminTask.createAuthDataEntry([
                "-alias", name,
                "-user", desired["user"],
                "-password", desired["password"],
                "-description", description,
            ])
            continue

        args = []
        if current["user"] != desired["user"]:
            args += ["-user", desired["user"]]
        if current["description"] != description:
            args += ["-description", description]
        if always:
            args += ["-password", desired["password"]]
        if args:
            AdminTask.modifyAuthDataEntry(["-alias", name] + args)


def write_absent(admin, params, before):
    AdminTask = admin["AdminTask"]
    present = [a["name"] for a in before["aliases"]]
    for alias in params.get("aliases") or []:
        if alias["name"] in present:
            AdminTask.deleteAuthDataEntry(["-alias", alias["name"]])


def sync(admin, params):
    """Security changes reach the nodes on synchronisation, like everything."""
    AdminControl = admin["AdminControl"]
    for mbean in AdminControl.queryNames("type=NodeSync,*").splitlines():
        mbean = mbean.strip()
        if mbean:
            AdminControl.invoke(mbean, "sync")
