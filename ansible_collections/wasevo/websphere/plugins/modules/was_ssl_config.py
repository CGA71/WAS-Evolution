#!/usr/bin/python
# -*- coding: utf-8 -*-
# Copyright (c) 2026, CGA
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r"""
---
module: was_ssl_config
short_description: Manage the SSL configurations of a WAS cell and the signers their trust stores need
version_added: "0.5.0"
description:
  - Creates, modifies and deletes SSL configurations at the cell or a node
    scope - key store, trust store, protocol, security level, client
    authentication - and retrieves or deletes signer certificates, in one
    C(wsadmin) session.
  - The profile's defaults (C(CellDefaultSSLSettings),
    C(NodeDefaultSSLSettings)) are modified, never deleted.
  - Key stores are not created here. A configuration or signer naming a key
    store the scope does not have is refused.
  - The ssl role drives it, through the C(ssl_settings) filter, which refuses
    protocols below TLS 1.2 and weak cipher levels.
notes:
  - A signer is compared by alias. A peer whose issuer changed is a signer
    declared absent, then present.
  - When the cell's security has I(dynamicallyUpdateSSLConfig) off, the
    module lists the cell to restart; otherwise new connections use the new
    configuration once the nodes are synchronised.
options:
  configs:
    description: SSL configurations, as the C(ssl_settings) filter renders them.
    type: list
    elements: dict
    default: []
  signers:
    description: Signer certificates, as the C(ssl_settings) filter renders them.
    type: list
    elements: dict
    default: []
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
- name: The cell default on TLS 1.2, and the directory's issuer trusted
  wasevo.websphere.was_ssl_config:
    configs:
      - alias: CellDefaultSSLSettings
        scope: {type: cell}
        state: present
        keystore: CellDefaultKeyStore
        truststore: CellDefaultTrustStore
        protocol: TLSv1.2
        security_level: HIGH
        client_auth: "false"
        client_auth_supported: "false"
    signers:
      - alias: corp-ldap-ca
        scope: {type: cell}
        state: present
        truststore: CellDefaultTrustStore
        host: ad1.example.com
        port: "636"
    profile_path: /app/profiles/Dmgr01
    admin_user: "{{ was_admin_user }}"
    admin_password: "{{ was_admin_password }}"
"""

RETURN = r"""
ssl:
  description: The declared configurations and signers, as the cell holds them afterwards.
  returned: always
  type: dict
restart_required:
  description: What must restart for the change to apply.
  returned: always
  type: list
  elements: str
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
        configs=dict(type="list", elements="dict", default=[]),
        signers=dict(type="list", elements="dict", default=[]),
    )
    module = AnsibleModule(argument_spec=argument_spec, supports_check_mode=True)
    if not module.params["configs"] and not module.params["signers"]:
        module.fail_json(msg="no configuration and no signer; the role skips the task instead of sending it")

    runner = WsadminRunner(module)
    try:
        answer = runner.run("ssl_config", "present", dict(
            configs=module.params["configs"], signers=module.params["signers"]))
    except WsadminFailure as exc:
        module.fail_json(msg=str(exc))

    after = answer.get("after") or {}
    restart = []
    if answer["changed"] and after.get("dynamic_update") == "false":
        restart = ["the deployment manager, every node agent and every server"]
        module.warn("dynamic SSL configuration updates are off in this cell: restart %s" % restart[0])
    module.exit_json(
        changed=answer["changed"],
        ssl=after,
        restart_required=restart,
        diff=dict(before=answer.get("before") or {}, after=after),
    )


if __name__ == "__main__":
    main()
