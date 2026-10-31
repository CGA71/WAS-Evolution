# -*- coding: utf-8 -*-
"""Handler for SSL configurations and the signer certificates their trust
stores need.

AN SSL CONFIGURATION is an alias at a management scope - the cell, or a
node - naming a key store, a trust store, a protocol, a cipher strength and
whether the peer must present a certificate. The profile creates the
defaults (CellDefaultSSLSettings, NodeDefaultSSLSettings): they are modified,
never deleted, because every endpoint without its own configuration uses
them. Other configurations are created and deleted.

A SIGNER is the certificate of a peer's issuer, held in a trust store so a
connection to that peer is trusted - an LDAPS directory, a database over TLS,
an IBM MQ queue manager. It is retrieved from the peer's port with
retrieveSignerFromPort, by alias, and compared by alias: a replay does not
fetch it again. A peer that changed issuer is a signer declared absent, then
present.

KEY STORES ARE NOT CREATED HERE. A configuration naming a key or trust store
the scope does not have is refused, and names it: key stores come with the
profile, or with a certificate procedure this role does not stand in for.

Written with the AdminTask verbs of IBM's procedure - createSSLConfig,
modifySSLConfig, deleteSSLConfig, retrieveSignerFromPort,
deleteSignerCertificate - and read with AdminConfig, from security.xml, except
the signers, which live in the key store file and are listed with
listSignerCertificates.

Five callables, same contract as every other handler - see cluster.py.
"""

import re

_ALIAS = re.compile(r"\[alias ([^\]]+)\]")


def _ids(text):
    text = (text or "").strip()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    return [part for part in text.replace("\n", " ").split() if part]


def _scope_name(cell, scope):
    if scope["type"] == "node":
        return "(cell):%s:(node):%s" % (cell, scope["node"])
    return "(cell):%s" % cell


def _keystores(AdminConfig):
    """(name, scope name) of every key store of the cell."""
    found = []
    for config_id in _ids(AdminConfig.list("KeyStore")):
        scope = AdminConfig.showAttribute(config_id, "managementScope")
        found.append((AdminConfig.showAttribute(config_id, "name"),
                      AdminConfig.showAttribute(scope, "scopeName")))
    return found


def _configs(AdminConfig):
    """(alias, scope name) -> what the plan compares, for every SSL configuration."""
    found = {}
    for config_id in _ids(AdminConfig.list("SSLConfig")):
        scope = AdminConfig.showAttribute(config_id, "managementScope")
        setting = AdminConfig.showAttribute(config_id, "setting")
        key_store = AdminConfig.showAttribute(setting, "keyStore")
        trust_store = AdminConfig.showAttribute(setting, "trustStore")
        found[(AdminConfig.showAttribute(config_id, "alias"),
               AdminConfig.showAttribute(scope, "scopeName"))] = {
            "keystore": key_store and AdminConfig.showAttribute(key_store, "name") or "",
            "truststore": trust_store and AdminConfig.showAttribute(trust_store, "name") or "",
            "protocol": AdminConfig.showAttribute(setting, "sslProtocol"),
            "security_level": AdminConfig.showAttribute(setting, "securityLevel"),
            "client_auth": AdminConfig.showAttribute(setting, "clientAuthentication"),
            "client_auth_supported": AdminConfig.showAttribute(setting, "clientAuthenticationSupported"),
        }
    return found


def _signers(AdminTask, store, scope_name):
    listed = AdminTask.listSignerCertificates(["-keyStoreName", store, "-keyStoreScope", scope_name])
    return _ALIAS.findall(listed or "")


COMPARED = ("keystore", "truststore", "protocol", "security_level", "client_auth",
            "client_auth_supported")


def read(admin, params):
    AdminConfig = admin["AdminConfig"]
    cell = admin["AdminControl"].getCell()
    stores = _keystores(AdminConfig)
    configs = _configs(AdminConfig)

    before = {"exists": True, "cell": cell, "configs": [], "signers": [], "missing_stores": []}
    for wanted in params.get("configs") or []:
        scope_name = _scope_name(cell, wanted["scope"])
        current = configs.get((wanted["alias"], scope_name))
        if current is not None:
            entry = {"alias": wanted["alias"], "scope": scope_name}
            entry.update(current)
            before["configs"].append(entry)
        if wanted["state"] == "present":
            for store in (wanted["keystore"], wanted["truststore"]):
                if (store, scope_name) not in stores and (store, scope_name) not in before["missing_stores"]:
                    before["missing_stores"].append((store, scope_name))

    listed = {}
    for wanted in params.get("signers") or []:
        scope_name = _scope_name(cell, wanted["scope"])
        key = (wanted["truststore"], scope_name)
        if key not in stores:
            if key not in before["missing_stores"]:
                before["missing_stores"].append(key)
            continue
        if key not in listed:
            listed[key] = _signers(admin["AdminTask"], wanted["truststore"], scope_name)
        if wanted["alias"] in listed[key]:
            before["signers"].append({"alias": wanted["alias"], "truststore": wanted["truststore"],
                                      "scope": scope_name})

    security_id = _ids(AdminConfig.list("Security"))[0]
    before["dynamic_update"] = AdminConfig.showAttribute(security_id, "dynamicallyUpdateSSLConfig")
    before["missing_stores"] = ["%s at %s" % pair for pair in before["missing_stores"]]
    return before


def plan_present(admin, params, before):
    if before["missing_stores"]:
        raise ValueError(
            "no key store %s in this cell. Key stores come with the profile or with "
            "a certificate procedure; this role configures what uses them"
            % ", ".join(before["missing_stores"]))
    # before holds the declared configurations and signers the cell has, and
    # only those: what the plan expects afterwards is the declared present
    # ones, as declared.
    cell = before["cell"]
    after_configs = []
    for wanted in params.get("configs") or []:
        if wanted["state"] == "absent":
            continue
        entry = {"alias": wanted["alias"], "scope": _scope_name(cell, wanted["scope"])}
        entry.update(dict((k, wanted[k]) for k in COMPARED))
        after_configs.append(entry)

    after_signers = []
    for wanted in params.get("signers") or []:
        if wanted["state"] == "present":
            after_signers.append({"alias": wanted["alias"], "truststore": wanted["truststore"],
                                  "scope": _scope_name(cell, wanted["scope"])})

    def _sorted(items):
        return sorted(items, key=lambda i: (i["alias"], i["scope"]))

    after = {"exists": True, "cell": cell, "configs": _sorted(after_configs),
             "signers": _sorted(after_signers), "missing_stores": [],
             "dynamic_update": before["dynamic_update"]}
    changed = (after["configs"] != _sorted(before["configs"])
               or after["signers"] != _sorted(before["signers"]))
    return changed, after


def plan_absent(admin, params, before):
    raise ValueError(
        "ssl has no state absent of its own: declare state: absent on the "
        "configurations and signers to remove"
    )


FLAGS = (
    ("protocol", "-sslProtocol"),
    ("security_level", "-securityLevel"),
    ("client_auth", "-clientAuthentication"),
    ("client_auth_supported", "-clientAuthenticationSupported"),
)


def write_present(admin, params, before):
    AdminTask = admin["AdminTask"]
    cell = before["cell"]
    configs = dict(((c["alias"], c["scope"]), c) for c in before["configs"])

    for wanted in params.get("configs") or []:
        scope_name = _scope_name(cell, wanted["scope"])
        current = configs.get((wanted["alias"], scope_name))
        base = ["-alias", wanted["alias"], "-scopeName", scope_name]
        if wanted["state"] == "absent":
            if current is not None:
                AdminTask.deleteSSLConfig(base)
            continue
        if current is None:
            args = base + ["-type", "JSSE",
                           "-keyStoreName", wanted["keystore"], "-keyStoreScopeName", scope_name,
                           "-trustStoreName", wanted["truststore"], "-trustStoreScopeName", scope_name]
            for key, flag in FLAGS:
                args += [flag, wanted[key]]
            AdminTask.createSSLConfig(args)
            continue
        args = []
        for key, flag in FLAGS:
            if current[key] != wanted[key]:
                args += [flag, wanted[key]]
        for key, flag in (("keystore", "-keyStoreName"), ("truststore", "-trustStoreName")):
            if current[key] != wanted[key]:
                args += [flag, wanted[key], flag.replace("Name", "ScopeName"), scope_name]
        if args:
            AdminTask.modifySSLConfig(base + args)

    present = [(s["alias"], s["truststore"], s["scope"]) for s in before["signers"]]
    for wanted in params.get("signers") or []:
        scope_name = _scope_name(cell, wanted["scope"])
        held = (wanted["alias"], wanted["truststore"], scope_name) in present
        store = ["-keyStoreName", wanted["truststore"], "-keyStoreScope", scope_name,
                 "-certificateAlias", wanted["alias"]]
        if wanted["state"] == "present" and not held:
            AdminTask.retrieveSignerFromPort(store + ["-host", wanted["host"], "-port", wanted["port"]])
        elif wanted["state"] == "absent" and held:
            AdminTask.deleteSignerCertificate(store)


def write_absent(admin, params, before):
    plan_absent(admin, params, before)


def sync(admin, params):
    AdminControl = admin["AdminControl"]
    for mbean in AdminControl.queryNames("type=NodeSync,*").splitlines():
        mbean = mbean.strip()
        if mbean:
            AdminControl.invoke(mbean, "sync")
