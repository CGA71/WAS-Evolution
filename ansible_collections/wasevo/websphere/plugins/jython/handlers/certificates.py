# -*- coding: utf-8 -*-
"""Handler for the certificates a cell holds: what expires, and renewing it.

Every key store of the cell is read - the profile's own and any created for an
application - and every certificate in it: the personal certificates an SSL
configuration presents, and the signers a trust store holds to trust a peer.
Each comes back with its expiry, the days left, and the one way it can be
renewed:

  renew           a certificate the cell signed - chained to the cell's root,
                  or self-signed. renewCertificate issues it again under the
                  same alias, and every SSL configuration keeps using it.
  request         a certificate a CA outside the cell signed. renewCertificate
                  would silently replace it with one the cell signs, which no
                  client trusts, so it is refused: a certificate request is
                  generated instead, the CA signs it, and `receive` takes the
                  answer in.
  receive         the signed answer received into the key store, then
                  replaceCertificate moves every SSL configuration from the
                  old alias to the new one and deletes the old certificate.
  refresh_signer  a signer is a peer's certificate. Only the peer can renew
                  it; once it has, the signer is deleted and retrieved again
                  from the peer's port, under the same alias.
  manual          the cell's root. Renewing it re-signs every chained
                  certificate of the cell at once - an operation to plan, not
                  a button.

ONE HANDLER, ONE ACTION PER CALL. params["action"] is `inventory` - read
only, plan_present never changes anything - or one of the four above, on one
certificate named by its key store, management scope name and alias, exactly
as the inventory lists them.

DATES. AdminTask prints a certificate's validity as text, in the JVM's locale:
"Valid from Feb 2, 2026 to Feb 2, 2027." on an English JVM. The three shapes
WAS is known to print are parsed by hand - month names, US numeric, ISO -
because strptime's %b follows the process locale. A date none of them reads
is reported with status `unknown`, never `ok`: an expiry nobody could read is
not one that is far away.

Written with the AdminTask verbs of IBM's certificate procedures -
listPersonalCertificates, listSignerCertificates, renewCertificate,
createCertificateRequest, extractCertificateRequest, listCertificateRequests,
receiveCertificate, replaceCertificate, addSignerCertificate,
deleteSignerCertificate, retrieveSignerFromPort - and AdminConfig for the key
stores and the SSL configurations that use each certificate.

Five callables, same contract as every other handler - see cluster.py.
"""

import datetime
import os
import re

# Key stores a profile creates. A certificate in one of them is the engine's;
# a certificate in any other key store was put there for an application.
ENGINE_STORES = (
    "CellDefaultKeyStore", "CellDefaultTrustStore", "NodeDefaultKeyStore",
    "NodeDefaultTrustStore", "DefaultRootStore", "DefaultSignersStore",
    "CellRSATokenKeyStore", "CellRSATokenTrustStore", "NodeRSATokenKeyStore",
    "NodeRSATokenTrustStore",
)
# Key stores that hold no certificate to watch: LTPA key sets are not X.509,
# and the deleted store is where replaced certificates go.
SKIPPED_USAGES = ("KeySetKeys", "DeletedKeys")

MONTHS = dict((name, index + 1) for index, name in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")))

ACTIONS = ("inventory", "renew", "request", "receive", "refresh_signer")


# -- parsing what AdminTask prints ------------------------------------------

def _tree(text):
    """'[ [alias a] [issuedTo [CN=x]] ]' -> nested lists of text and groups."""
    stack = [[]]
    chunk = []
    for char in text or "":
        if char == "[":
            if "".join(chunk).strip():
                stack[-1].append("".join(chunk).strip())
            chunk = []
            stack.append([])
        elif char == "]":
            if "".join(chunk).strip():
                stack[-1].append("".join(chunk).strip())
            chunk = []
            if len(stack) > 1:
                group = stack.pop()
                stack[-1].append(group)
        else:
            chunk.append(char)
    return stack[0]


def _flat(node):
    if isinstance(node, list):
        return " ".join([_flat(child) for child in node]).strip()
    return node


def _attributes(group):
    """One certificate group -> {key: value}: [alias a] gives alias=a, and
    [issuedTo [CN=x, O=y]] gives issuedTo='CN=x, O=y'."""
    found = {}
    for child in group:
        if not isinstance(child, list) or not child:
            continue
        head = child[0]
        if isinstance(head, list):
            continue
        parts = head.split(None, 1)
        key = parts[0]
        value = parts[1] if len(parts) > 1 else _flat(child[1:])
        found[key] = value
    return found


def _certificate_groups(node):
    """Every group whose first element is [alias ...], at any depth."""
    found = []
    if isinstance(node, list):
        first = node[0] if node else None
        if isinstance(first, list) and first and not isinstance(first[0], list) \
                and first[0].startswith("alias "):
            return [node]
        for child in node:
            found.extend(_certificate_groups(child))
    return found


def parse_certificates(text):
    return [_attributes(group) for group in _certificate_groups(_tree(text))]


def parse_expiry(validity):
    """'Valid from Feb 2, 2026 to Feb 2, 2027.' -> '2027-02-02', or None."""
    match = re.search(r"\bto\s+(.+?)\.?\s*$", validity or "")
    if not match:
        return None
    text = match.group(1)
    named = re.search(r"([A-Za-z]{3,})\.?\s+(\d{1,2}),?\s+(\d{4})", text)
    if named and named.group(1)[:3].lower() in MONTHS:
        year, month, day = int(named.group(3)), MONTHS[named.group(1)[:3].lower()], int(named.group(2))
    else:
        iso = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", text)
        numeric = re.search(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", text)
        if iso:
            year, month, day = int(iso.group(1)), int(iso.group(2)), int(iso.group(3))
        elif numeric:
            month, day, year = int(numeric.group(1)), int(numeric.group(2)), int(numeric.group(3))
            if year < 100:
                year += 2000
        else:
            return None
    try:
        return datetime.date(year, month, day).isoformat()
    except ValueError:
        return None


# -- the cell -----------------------------------------------------------------

def _ids(text):
    text = (text or "").strip()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    return [part for part in text.replace("\n", " ").split() if part]


def _attr(AdminConfig, config_id, name):
    try:
        return AdminConfig.showAttribute(config_id, name) or ""
    except Exception:
        return ""


def _today(params):
    if params.get("today"):
        return datetime.date(*[int(p) for p in params["today"].split("-")])
    return datetime.date.today()


def _keystores(AdminConfig):
    """[{name, scope, usage}] for every key store worth reading."""
    stores = []
    for config_id in _ids(AdminConfig.list("KeyStore")):
        scope = AdminConfig.showAttribute(config_id, "managementScope")
        usage = _attr(AdminConfig, config_id, "usage") or "SSLKeys"
        if usage in SKIPPED_USAGES:
            continue
        stores.append({"name": AdminConfig.showAttribute(config_id, "name"),
                       "scope": AdminConfig.showAttribute(scope, "scopeName"),
                       "usage": usage})
    return stores


def _users(AdminConfig):
    """(key store, scope, alias) -> [SSL configuration aliases presenting it]."""
    users = {}
    for config_id in _ids(AdminConfig.list("SSLConfig")):
        scope = AdminConfig.showAttribute(AdminConfig.showAttribute(config_id, "managementScope"),
                                          "scopeName")
        setting = AdminConfig.showAttribute(config_id, "setting")
        key_store = AdminConfig.showAttribute(setting, "keyStore")
        if not key_store:
            continue
        store = AdminConfig.showAttribute(key_store, "name")
        aliases = []
        for attribute in ("serverKeyAlias", "clientKeyAlias"):
            value = _attr(AdminConfig, setting, attribute)
            if value and value not in aliases:
                aliases.append(value)
        # No alias named: JSSE presents the only, or the "default", one.
        for alias in aliases or ["default"]:
            users.setdefault((store, scope, alias), []).append(
                AdminConfig.showAttribute(config_id, "alias"))
    return users


def _method(kind, store, attrs):
    issued_to = attrs.get("issuedTo", "")
    issued_by = attrs.get("issuedBy", "")
    if kind == "signer":
        # A CA's own root, trusted as a signer, is renewed by that CA and
        # imported again; there is no port it can be retrieved from.
        return "manual" if issued_to == issued_by else "refresh_signer"
    if store["usage"] == "RootKeys":
        return "manual"
    if issued_to == issued_by or "OU=Root Certificate" in issued_by:
        return "renew"
    return "request"


def _status(days_left, window):
    if days_left is None:
        return "unknown"
    if days_left < 0:
        return "expired"
    if days_left <= 30:
        return "critical"
    if days_left <= window:
        return "warning"
    return "ok"


def _entry(kind, store, attrs, users, today, window):
    not_after = parse_expiry(attrs.get("validity", ""))
    days_left = None
    if not_after:
        days_left = (datetime.date(*[int(p) for p in not_after.split("-")]) - today).days
    alias = attrs.get("alias", "")
    return {
        "id": "%s|%s|%s|%s" % (kind, store["scope"], store["name"], alias),
        "kind": kind,
        "domain": "trust" if kind == "signer" else (
            "engine" if store["name"] in ENGINE_STORES else "application"),
        "scope": store["scope"],
        "keystore": store["name"],
        "alias": alias,
        "subject": attrs.get("issuedTo", ""),
        "issuer": attrs.get("issuedBy", ""),
        "serial": attrs.get("serialNumber", ""),
        "validity": attrs.get("validity", ""),
        "not_after": not_after or "",
        "days_left": days_left,
        "status": _status(days_left, window),
        "method": _method(kind, store, attrs),
        "used_by": users.get((store["name"], store["scope"], alias), []) if kind == "personal" else [],
    }


def _store_args(keystore, scope):
    return ["-keyStoreName", keystore, "-keyStoreScope", scope]


def _list(AdminTask, verb, keystore, scope):
    return parse_certificates(getattr(AdminTask, verb)(_store_args(keystore, scope)))


def _pending(AdminTask, keystore, scope):
    """Aliases of the certificate requests waiting in a key store."""
    try:
        listed = AdminTask.listCertificateRequests(_store_args(keystore, scope))
    except Exception:
        return []
    return [attrs.get("alias", "") for attrs in parse_certificates(listed)]


def inventory(admin, params):
    AdminConfig = admin["AdminConfig"]
    AdminTask = admin["AdminTask"]
    today = _today(params)
    window = int(params.get("renew_within_days", 90))
    users = _users(AdminConfig)
    found = []
    unreadable = []
    for store in _keystores(AdminConfig):
        for kind, verb in (("personal", "listPersonalCertificates"),
                           ("signer", "listSignerCertificates")):
            try:
                listed = _list(AdminTask, verb, store["name"], store["scope"])
            except Exception as exc:
                # A store a verb does not apply to - a root store has no
                # signers to list on some fix packs - is reported, not fatal.
                unreadable.append("%s %s at %s: %s" % (verb, store["name"], store["scope"],
                                                       str(exc).splitlines()[0][:160]))
                continue
            pending = _pending(AdminTask, store["name"], store["scope"]) if kind == "personal" else []
            for attrs in listed:
                entry = _entry(kind, store, attrs, users, today, window)
                # A request made to renew this certificate and not answered
                # yet: the next step is `receive`, with this alias.
                base = re.sub(r"_\d{8}$", "", entry["alias"])
                entry["pending_requests"] = [a for a in pending if a.startswith(base + "_")]
                found.append(entry)
    found.sort(key=lambda c: (c["days_left"] is None, c["days_left"], c["id"]))
    summary = {}
    for certificate in found:
        summary[certificate["status"]] = summary.get(certificate["status"], 0) + 1
    return {
        "exists": True,
        "cell": admin["AdminControl"].getCell(),
        "today": today.isoformat(),
        "renew_within_days": window,
        "certificates": found,
        "summary": summary,
        "unreadable": unreadable,
    }


# -- one certificate --------------------------------------------------------

def _target(admin, params):
    """The certificate the action names, as the inventory describes it."""
    store = None
    for candidate in _keystores(admin["AdminConfig"]):
        if candidate["name"] == params["keystore"] and candidate["scope"] == params["scope"]:
            store = candidate
    if store is None:
        raise ValueError("no key store %s at %s in this cell - take the key store and the "
                         "scope exactly as the inventory lists them"
                         % (params["keystore"], params["scope"]))
    kind = "signer" if params["action"] == "refresh_signer" else "personal"
    verb = "listSignerCertificates" if kind == "signer" else "listPersonalCertificates"
    users = _users(admin["AdminConfig"])
    today = _today(params)
    window = int(params.get("renew_within_days", 90))
    held = {}
    for attrs in _list(admin["AdminTask"], verb, store["name"], store["scope"]):
        held[attrs.get("alias", "")] = _entry(kind, store, attrs, users, today, window)
    return store, held


def _request_alias(params, current):
    """The alias a renewal by request gives the new certificate.

    Deterministic for one renewal cycle, so a replay finds the request it made:
    the alias of the certificate being replaced, stripped of any earlier
    suffix, and the expiry of that certificate.
    """
    if params.get("request_alias"):
        return params["request_alias"]
    base = re.sub(r"_\d{8}$", "", params["alias"])
    stamp = (current or {}).get("not_after", "").replace("-", "") or "next"
    return "%s_%s" % (base, stamp)


def read(admin, params):
    action = params.get("action", "inventory")
    if action not in ACTIONS:
        raise ValueError("action %r is not one of %s" % (action, ", ".join(ACTIONS)))
    if action == "inventory":
        return inventory(admin, params)

    store, held = _target(admin, params)
    current = held.get(params["alias"])
    before = {"exists": True, "action": action, "keystore": store["name"], "scope": store["scope"],
              "alias": params["alias"], "certificate": current}
    if action in ("request", "receive"):
        before["request_alias"] = _request_alias(params, current)
        before["pending"] = _pending(admin["AdminTask"], store["name"], store["scope"])
        before["replacement"] = held.get(before["request_alias"])
    return before


def _due(params, certificate):
    if params.get("force"):
        return True
    if certificate is None:
        return True
    days = certificate["days_left"]
    return days is None or days <= int(params.get("renew_within_days", 90))


def plan_present(admin, params, before):
    action = params.get("action", "inventory")
    if action == "inventory":
        return False, before

    current = before["certificate"]
    name = "%s in %s at %s" % (params["alias"], params["keystore"], params["scope"])
    after = dict(before)

    if action == "renew":
        if current is None:
            raise ValueError("no personal certificate %s" % name)
        if current["method"] == "manual":
            raise ValueError("%s is the cell's root: renewing it re-signs every chained "
                             "certificate of the cell at once. Plan it, do not press it" % name)
        if current["method"] == "request":
            raise ValueError("%s is issued by %s, a CA outside the cell. renewCertificate would "
                             "replace it with one the cell signs, which no client trusts - "
                             "renew it with action request, then receive"
                             % (name, current["issuer"]))
        changed = _due(params, current)
        if changed:
            after["certificate"] = dict(current, not_after="(issued again by the cell)",
                                        days_left=None, status="renewed")
        return changed, after

    if action == "request":
        if current is None:
            raise ValueError("no personal certificate %s to renew by request" % name)
        if current["method"] == "manual":
            raise ValueError("%s is the cell's root; it is not renewed by request" % name)
        if not params.get("request_file"):
            raise ValueError("request needs request_file: where the certificate request is "
                             "written on the deployment manager")
        changed = before["request_alias"] not in before["pending"] \
            and before["replacement"] is None and _due(params, current)
        if changed:
            after["pending"] = before["pending"] + [before["request_alias"]]
        else:
            _extract_request(admin, params, before)
        return changed, after

    if action == "receive":
        if not params.get("request_alias"):
            raise ValueError("receive needs request_alias: the alias the request job reported. "
                             "Once the old certificate is replaced it cannot be worked out again")
        if not params.get("certificate_file"):
            raise ValueError("receive needs certificate_file: the signed certificate, on the "
                             "deployment manager")
        waiting = before["request_alias"] in before["pending"]
        received = before["replacement"] is not None
        if not waiting and not received:
            raise ValueError("no certificate request %s in %s at %s - run action request first, "
                             "and give the CA that request"
                             % (before["request_alias"], params["keystore"], params["scope"]))
        # Received and the old alias already gone: the replay finds nothing to do.
        changed = waiting or (received and current is not None)
        if changed:
            after["pending"] = [a for a in before["pending"] if a != before["request_alias"]]
            after["certificate"] = None
            after["replacement"] = before["replacement"] or {"alias": before["request_alias"]}
        return changed, after

    # refresh_signer
    if not params.get("host") or not params.get("port"):
        raise ValueError("refresh_signer needs the peer's host and port: a signer is retrieved "
                         "again from the peer that presents it")
    changed = _due(params, current)
    if changed:
        after["certificate"] = dict(current or {"alias": params["alias"]},
                                    not_after="(retrieved again from %s:%s)"
                                    % (params["host"], params["port"]),
                                    days_left=None, status="renewed")
    return changed, after


def plan_absent(admin, params, before):
    raise ValueError("certificates has no state absent: a certificate is renewed, and the one "
                     "it replaces goes to the deleted store")


def write_present(admin, params, before):
    AdminTask = admin["AdminTask"]
    action = params["action"]
    store = _store_args(before["keystore"], before["scope"])

    if action == "renew":
        AdminTask.renewCertificate(store + ["-certificateAlias", params["alias"]])
        return

    if action == "request":
        current = before["certificate"]
        AdminTask.createCertificateRequest(store + [
            "-certificateAlias", before["request_alias"],
            "-subjectDN", params.get("subject_dn") or current["subject"],
            "-keySize", str(params.get("key_size", 2048)),
            "-signatureAlgorithm", params.get("signature_algorithm", "SHA256withRSA"),
            "-certificateRequestFilePath", params["request_file"]])
        return

    if action == "receive":
        if before["request_alias"] in before["pending"]:
            if params.get("ca_file"):
                ca_alias = "%s_ca" % before["request_alias"]
                signers = [a.get("alias") for a in _list(AdminTask, "listSignerCertificates",
                                                         before["keystore"], before["scope"])]
                if ca_alias not in signers:
                    AdminTask.addSignerCertificate(store + [
                        "-certificateAlias", ca_alias, "-certificateFilePath", params["ca_file"],
                        "-base64Encoded", "true"])
            AdminTask.receiveCertificate(store + [
                "-certificateFilePath", params["certificate_file"], "-isBase64Encoded", "true"])
        if before["certificate"] is not None:
            AdminTask.replaceCertificate(store + [
                "-certificateAlias", params["alias"],
                "-replacementCertificateAlias", before["request_alias"],
                "-deleteOldCert", "true", "-deleteOldSigners", "false"])
        return

    # refresh_signer
    if before["certificate"] is not None:
        AdminTask.deleteSignerCertificate(store + ["-certificateAlias", params["alias"]])
    AdminTask.retrieveSignerFromPort(store + [
        "-certificateAlias", params["alias"], "-host", params["host"], "-port", str(params["port"])])


def write_absent(admin, params, before):
    plan_absent(admin, params, before)


def _extract_request(admin, params, before):
    """Write a waiting request to request_file again - a replay that changed
    nothing still hands the CA the request it is waiting for. A file, not the
    configuration: nothing to save, nothing to synchronise, and not in a check
    run."""
    if admin.get("check_mode"):
        return
    path = params.get("request_file")
    if path and before["request_alias"] in before["pending"] and not os.path.exists(path):
        admin["AdminTask"].extractCertificateRequest(
            _store_args(before["keystore"], before["scope"])
            + ["-certificateAlias", before["request_alias"], "-certificateRequestFilePath", path])


def sync(admin, params):
    AdminControl = admin["AdminControl"]
    for mbean in AdminControl.queryNames("type=NodeSync,*").splitlines():
        mbean = mbean.strip()
        if mbean:
            AdminControl.invoke(mbean, "sync")
