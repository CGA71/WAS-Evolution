#!/usr/bin/python
# -*- coding: utf-8 -*-
# Copyright (c) 2026, CGA
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r"""
---
module: was_certificate
short_description: Renew one certificate of a WAS cell, the way its issuer allows
version_added: "0.6.0"
description:
  - Acts on one certificate, named by its key store, management scope and
    alias exactly as M(wasevo.websphere.was_certificate_info) lists them, in
    one C(wsadmin) session.
  - C(renew) issues again a certificate the cell signed - chained to the
    cell's root, or self-signed - under the same alias.
  - C(request) generates a certificate request for a certificate a CA outside
    the cell signed, and writes it to I(request_file) for that CA.
  - C(receive) takes the CA's answer in, then moves every SSL configuration
    from the old certificate to the new one and deletes the old one.
  - C(refresh_signer) deletes a peer's signer and retrieves it again from the
    peer's port, once the peer has renewed its certificate.
  - Nothing is done to a certificate further than I(renew_within_days) from
    its expiry unless I(force) is set, so a replay changes nothing.
notes:
  - The cell's root certificate is refused, and so is C(renew) on a
    certificate a CA outside the cell signed - the cell would replace it with
    one no client trusts.
options:
  action:
    description: What to do with the certificate.
    type: str
    required: true
    choices: [renew, request, receive, refresh_signer]
  keystore:
    description: The key store holding the certificate.
    type: str
    required: true
  scope:
    description: The key store's management scope name, as listed - C((cell):MyCell) or C((cell):MyCell:(node):MyNode).
    type: str
    required: true
  alias:
    description: The certificate's alias.
    type: str
    required: true
  renew_within_days:
    description: Act only on a certificate expiring within this many days.
    type: int
    default: 90
  force:
    description: Act whatever the expiry.
    type: bool
    default: false
  request_alias:
    description:
      - The alias the new certificate takes with C(request) and C(receive).
      - Defaults, for C(request), to the alias stripped of an earlier date
        suffix, followed by the old certificate's expiry. Required for
        C(receive); the C(request) run reports it.
    type: str
  request_file:
    description: Where C(request) writes the certificate request, on the deployment manager.
    type: path
  subject_dn:
    description: Subject of the request. Defaults to the current certificate's.
    type: str
  key_size:
    description: Key size of the request.
    type: int
    default: 2048
  signature_algorithm:
    description: Signature algorithm of the request.
    type: str
    default: SHA256withRSA
  certificate_file:
    description: The signed certificate C(receive) takes in, base64, on the deployment manager.
    type: path
  ca_file:
    description: The issuing CA's certificate, added as a signer of the key store before C(receive).
    type: path
  peer_host:
    description: The peer C(refresh_signer) retrieves the signer from.
    type: str
  peer_port:
    description: The peer's TLS port.
    type: int
  profile_path:
    description: Path to the deployment manager profile.
    type: path
    required: true
  admin_user:
    description: Administrative user for C(wsadmin).
    type: str
    required: true
  admin_password:
    description: Password for I(admin_user).
    type: str
    required: true
  conntype:
    description: C(wsadmin) connection type.
    type: str
    choices: [SOAP, RMI, JSR160RMI, IPC, NONE]
    default: SOAP
  host:
    description: Deployment manager host. Defaults to the profile setting.
    type: str
  port:
    description: Deployment manager SOAP port. Defaults to the profile setting.
    type: int
  jython_dir:
    description: Directory on the target holding the staged Jython driver.
    type: path
    default: /opt/exploit/scripts/jython-ansible
  save_config:
    description: Save the configuration after a change.
    type: bool
    default: true
  sync_nodes:
    description: Synchronise the nodes after a change.
    type: bool
    default: true
author:
  - neo
"""

EXAMPLES = r"""
- name: Renew the cell's own certificate
  wasevo.websphere.was_certificate:
    action: renew
    keystore: CellDefaultKeyStore
    scope: "(cell):MyCell"
    alias: default
    profile_path: /app/profiles/Dmgr01
    admin_user: "{{ was_admin_user }}"
    admin_password: "{{ was_admin_password }}"

- name: A CA-signed certificate, first half - the request for the CA
  wasevo.websphere.was_certificate:
    action: request
    keystore: ExtranetKeyStore
    scope: "(cell):MyCell"
    alias: extranet-web
    request_file: /tmp/extranet-web.csr
    profile_path: /app/profiles/Dmgr01
    admin_user: "{{ was_admin_user }}"
    admin_password: "{{ was_admin_password }}"
  register: req
"""

RETURN = r"""
certificate:
  description: The certificate as the cell holds it afterwards, or null once replaced.
  returned: always
  type: dict
request_alias:
  description: The alias of the request and of the certificate that replaces the old one.
  returned: when action is request or receive
  type: str
pending:
  description: Certificate requests waiting in the key store.
  returned: when action is request or receive
  type: list
  elements: str
replacement:
  description: The certificate that replaced the old one.
  returned: when action is receive
  type: dict
"""

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.wasevo.websphere.plugins.module_utils.wsadmin import (
    WSADMIN_COMMON_ARGS,
    WsadminFailure,
    WsadminRunner,
)


def main():
    argument_spec = dict(WSADMIN_COMMON_ARGS)
    argument_spec.update(
        action=dict(type="str", required=True, choices=["renew", "request", "receive", "refresh_signer"]),
        keystore=dict(type="str", required=True),
        scope=dict(type="str", required=True),
        alias=dict(type="str", required=True),
        renew_within_days=dict(type="int", default=90),
        force=dict(type="bool", default=False),
        request_alias=dict(type="str"),
        request_file=dict(type="path"),
        subject_dn=dict(type="str"),
        key_size=dict(type="int", default=2048),
        signature_algorithm=dict(type="str", default="SHA256withRSA"),
        certificate_file=dict(type="path"),
        ca_file=dict(type="path"),
        peer_host=dict(type="str"),
        peer_port=dict(type="int"),
    )
    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
        required_if=[
            ("action", "request", ["request_file"]),
            ("action", "receive", ["request_alias", "certificate_file"]),
            ("action", "refresh_signer", ["peer_host", "peer_port"]),
        ],
    )

    params = dict((key, module.params[key]) for key in (
        "action", "keystore", "scope", "alias", "renew_within_days", "force", "request_alias",
        "request_file", "subject_dn", "key_size", "signature_algorithm", "certificate_file",
        "ca_file") if module.params[key] is not None)
    if module.params["peer_host"]:
        params["host"] = module.params["peer_host"]
        params["port"] = module.params["peer_port"]

    runner = WsadminRunner(module)
    try:
        answer = runner.run("certificates", "present", params)
    except WsadminFailure as exc:
        module.fail_json(msg=str(exc))

    after = answer.get("after") or {}
    result = dict(
        changed=answer["changed"],
        certificate=after.get("certificate"),
        diff=dict(before=answer.get("before") or {}, after=after),
    )
    if module.params["action"] in ("request", "receive"):
        result.update(request_alias=after.get("request_alias"), pending=after.get("pending", []),
                      replacement=after.get("replacement"))
    module.exit_json(**result)


if __name__ == "__main__":
    main()
