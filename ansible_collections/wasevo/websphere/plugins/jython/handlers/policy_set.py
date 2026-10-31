# -*- coding: utf-8 -*-
"""Handler for web services policy sets.

A POLICY SET is a named collection of policy types - WSHTTPS, WSAddressing,
WSSecurity, WSReliableMessaging and the rest - each with its attributes. The
product ships defaults; a cell holds the ones imported into it, and copies an
administrator adjusted.

TWO WAYS IN, ON PURPOSE. from_default imports a product default as it is,
under its own name. copy_of copies a set already in the cell - a default just
imported, or another copy - and the copy is the one adjusted. A default is
never adjusted in place: the next import of it puts the product's version
back, and the adjustment is gone without a word.

ATTACHMENTS ARE NOT HERE. A policy set is attached to an application's
services, which exist once the application is deployed: the attachment is
part of that deployment, the last step. A set still attached to an
application is refused deletion, and the applications are named.

Written and read with the PolicySetManagement AdminTask verbs - there is no
AdminConfig view of a policy set. The attributes a policy type returns are
compared as strings, and only the ones declared.

Five callables, same contract as every other handler - see cluster.py.
"""

import re

_KEY = re.compile(r"(?:^|, )([A-Za-z0-9_.]+)=")


def _ids(text):
    text = (text or "").strip()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    return [part for part in text.replace("\n", " ").split() if part]


def _properties(text):
    """A java.util.Properties as wsadmin prints it - {a=1, b=two words} - as a
    dict. A value may hold a comma; a key may not hold a space."""
    text = (text or "").strip()
    if text.startswith("{") and text.endswith("}"):
        text = text[1:-1]
    found = {}
    marks = [(m.start(), m.end(), m.group(1)) for m in _KEY.finditer(text)]
    for index in range(len(marks)):
        start, end, key = marks[index]
        stop = index + 1 < len(marks) and marks[index + 1][0] or len(text)
        found[key] = text[end:stop]
    return found


def _quoted(value):
    value = str(value)
    if not value or " " in value or "[" in value or "]" in value:
        return '"%s"' % value.replace('"', '\\"')
    return value


def _attributes(pairs):
    return "[%s]" % " ".join("[%s %s]" % (k, _quoted(v)) for k, v in pairs)


def _exists(AdminTask, name):
    """getPolicySet answers a set's attributes, or fails for a name the cell
    does not hold. The failure is a Java ScriptingException, which is why the
    except is bare."""
    try:
        return _properties(AdminTask.getPolicySet(["-policySet", name]))
    except:
        return None


def read(admin, params):
    AdminTask = admin["AdminTask"]
    before = {"exists": True, "policy_sets": []}
    for wanted in params.get("policy_sets") or []:
        shown = _exists(AdminTask, wanted["name"])
        if shown is None:
            continue
        entry = {"name": wanted["name"]}
        if "description" in wanted:
            entry["description"] = shown.get("description", "")
        policies = {}
        types = _ids(AdminTask.listPolicyTypes(["-policySet", wanted["name"]]))
        for policy_type in sorted(wanted.get("policies") or {}):
            if policy_type not in types:
                policies[policy_type] = None
                continue
            keys = sorted(wanted["policies"][policy_type])
            shown_type = _properties(AdminTask.getPolicyType([
                "-policySet", wanted["name"], "-policyType", policy_type,
                "-attributes", "[%s]" % " ".join(keys)]))
            policies[policy_type] = dict((k, shown_type.get(k, "")) for k in keys)
        if wanted.get("state") != "absent":
            entry["policies"] = policies
        before["policy_sets"].append(entry)
    return before


def _wanted(wanted):
    entry = {"name": wanted["name"], "policies": dict(
        (t, dict(a)) for t, a in (wanted.get("policies") or {}).items())}
    if "description" in wanted:
        entry["description"] = wanted["description"]
    return entry


def plan_present(admin, params, before):
    AdminTask = admin["AdminTask"]
    held = dict((p["name"], p) for p in before["policy_sets"])
    coming = []
    after = []
    for wanted in params.get("policy_sets") or []:
        name = wanted["name"]
        if wanted["state"] == "absent":
            if name in held:
                attached = _ids(AdminTask.listAttachmentsForPolicySet(["-policySet", name]))
                if attached:
                    raise ValueError(
                        "policy set %s is attached to %s: deleting it leaves their "
                        "services without the policies they were deployed with. "
                        "Detach it with the application's deployment first"
                        % (name, ", ".join(attached)))
            continue
        source = wanted.get("copy_of")
        if source and name not in held and source not in held and source not in coming:
            raise ValueError(
                "policy set %s copies %s, which this cell does not hold and this "
                "declaration does not import" % (name, source))
        coming.append(name)
        after.append(_wanted(wanted))
    after = sorted(after, key=lambda p: p["name"])
    current = sorted([p for p in before["policy_sets"]
                      if [w for w in params.get("policy_sets") or []
                          if w["name"] == p["name"] and w["state"] != "absent"]],
                     key=lambda p: p["name"])
    deleted = [w["name"] for w in params.get("policy_sets") or []
               if w["state"] == "absent" and w["name"] in held]
    return after != current or bool(deleted), {"exists": True, "policy_sets": after}


def plan_absent(admin, params, before):
    raise ValueError(
        "policy sets have no state absent of their own: declare state: absent "
        "on the sets to delete"
    )


def write_present(admin, params, before):
    AdminTask = admin["AdminTask"]
    held = dict((p["name"], p) for p in before["policy_sets"])
    for wanted in params.get("policy_sets") or []:
        name = wanted["name"]
        if wanted["state"] == "absent":
            if name in held:
                AdminTask.deletePolicySet(["-policySet", name])
            continue

        current = held.get(name)
        if current is None:
            if wanted.get("from_default"):
                AdminTask.importPolicySet(["-defaultPolicySet", wanted["from_default"]])
            else:
                AdminTask.copyPolicySet([
                    "-sourcePolicySet", wanted["copy_of"], "-newPolicySet", name,
                    "-newDescription", wanted.get("description", ""),
                    "-transferAttachments", "false"])
            current = {"name": name, "description": wanted.get("description"), "policies": {}}
            types = _ids(AdminTask.listPolicyTypes(["-policySet", name]))
            for policy_type in wanted.get("policies") or {}:
                # Not "in types and {} or None": an empty dict is false.
                if policy_type in types:
                    current["policies"][policy_type] = {}
                else:
                    current["policies"][policy_type] = None

        if "description" in wanted and current.get("description") != wanted["description"]:
            AdminTask.updatePolicySet(["-policySet", name, "-attributes",
                                       _attributes([("description", wanted["description"])])])

        for policy_type in sorted(wanted.get("policies") or {}):
            declared = wanted["policies"][policy_type]
            shown = (current.get("policies") or {}).get(policy_type)
            if shown is None:
                AdminTask.addPolicyType(["-policySet", name, "-policyType", policy_type,
                                         "-enabled", "true"])
                shown = {}
            different = [(k, declared[k]) for k in sorted(declared) if shown.get(k) != declared[k]]
            if different:
                AdminTask.setPolicyType(["-policySet", name, "-policyType", policy_type,
                                         "-attributes", _attributes(different)])


def write_absent(admin, params, before):
    plan_absent(admin, params, before)


def sync(admin, params):
    AdminControl = admin["AdminControl"]
    for mbean in AdminControl.queryNames("type=NodeSync,*").splitlines():
        mbean = mbean.strip()
        if mbean:
            AdminControl.invoke(mbean, "sync")
