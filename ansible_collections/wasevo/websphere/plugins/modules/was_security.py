#!/usr/bin/python
# -*- coding: utf-8 -*-
# Copyright (c) 2026, CGA
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r"""
---
module: was_security
short_description: Configure global security and the active user registry of a WAS cell
version_added: "0.5.0"
description:
  - Configures one of the four user registries WAS offers - federated
    repositories, a standalone LDAP, the local operating system, a custom
    registry - makes it the active one, and sets administrative,
    application and Java 2 security, in one C(wsadmin) session.
  - Written with C(configureAdmin<type>UserRegistry) and
    C(setAdminActiveSecuritySettings), read back from C(security.xml).
  - The security role drives it, from the shared model, through the
    C(security_settings) filter.
notes:
  - The bind password of an LDAP registry cannot be read back. With
    I(password_policy=on_create) it is written whenever the LDAP
    configuration is; with C(always) on every run, and every run reports
    changed.
  - Refused before anything is written - the local operating system
    registry on a cell whose nodes run on more than one host.
  - Every change applies when the deployment manager, the node agents and
    the servers restart. The module warns, and restarts nothing.
  - There is no state absent.
options:
  admin_security:
    description: Administrative security. Always on; the role refuses to turn it off.
    type: str
    choices: ["true"]
    default: "true"
  app_security:
    description: Application security.
    type: bool
  java2_security:
    description: Java 2 security enforcement.
    type: bool
  registry:
    description:
      - The registry to configure and make active, as the C(security_settings)
        filter renders it - C(type), its C(attributes) as C(security.xml)
        spells them, C(hosts) for an LDAP, C(properties) for a custom registry.
    type: dict
    required: true
  bind_password:
    description: The LDAP bind password. From a credential, never from a versioned file.
    type: str
  password_policy:
    description: When the bind password is written.
    type: str
    choices: [on_create, always]
    default: on_create
  verify_registry:
    description: Have WAS check that the primary administrator exists in the registry before saving.
    type: bool
    default: true
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
- name: An LDAP over TLS, made active, with application security
  wasevo.websphere.was_security:
    app_security: true
    registry:
      type: LDAPUserRegistry
      attributes:
        primaryAdminId: wasadm
        type: ACTIVE_DIRECTORY
        baseDN: dc=example,dc=com
        bindDN: cn=was-bind,ou=services,dc=example,dc=com
        sslEnabled: "true"
      hosts:
        - {host: ad1.example.com, port: "636"}
        - {host: ad2.example.com, port: "636"}
    bind_password: "{{ lookup('ansible.builtin.env', 'LDAP_BIND_PASSWORD') }}"
    profile_path: /app/profiles/Dmgr01
    admin_user: "{{ was_admin_user }}"
    admin_password: "{{ was_admin_password }}"
"""

RETURN = r"""
security:
  description: The security settings and the registry, as the cell holds them afterwards. Never the bind password.
  returned: always
  type: dict
restart_required:
  description: What must restart for the change to apply - the whole cell, or nothing.
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

REGISTRY_TYPES = ("WIMUserRegistry", "LDAPUserRegistry", "LocalOSUserRegistry", "CustomUserRegistry")


def main():
    argument_spec = dict(WSADMIN_COMMON_ARGS)
    argument_spec.update(
        admin_security=dict(type="str", default="true", choices=["true"]),
        app_security=dict(type="bool"),
        java2_security=dict(type="bool"),
        registry=dict(type="dict", required=True),
        bind_password=dict(type="str", no_log=True),
        password_policy=dict(type="str", default="on_create", choices=["on_create", "always"], no_log=False),
        verify_registry=dict(type="bool", default=True),
    )
    module = AnsibleModule(argument_spec=argument_spec, supports_check_mode=True)

    registry = module.params["registry"]
    if registry.get("type") not in REGISTRY_TYPES:
        module.fail_json(msg="registry.type is one of %s" % ", ".join(REGISTRY_TYPES))
    if not (registry.get("attributes") or {}).get("primaryAdminId"):
        module.fail_json(msg="registry.attributes.primaryAdminId is required: a registry "
                             "without its administrator locks everyone out")
    if registry["type"] == "LDAPUserRegistry" and not registry.get("hosts"):
        module.fail_json(msg="an LDAP registry needs at least one host")

    params = dict(
        admin_security="true",
        registry=registry,
        password_policy=module.params["password_policy"],
        verify_registry=module.params["verify_registry"],
    )
    for key in ("app_security", "java2_security"):
        if module.params[key] is not None:
            params[key] = module.params[key] and "true" or "false"
    if module.params["bind_password"]:
        params["bind_password"] = module.params["bind_password"]

    runner = WsadminRunner(module)
    try:
        answer = runner.run("security", "present", params)
    except WsadminFailure as exc:
        module.fail_json(msg=str(exc))

    after = answer.get("after") or {}
    restart = []
    if answer["changed"]:
        restart = ["the deployment manager, every node agent and every server"]
        module.warn("security changes apply at restart: restart %s" % restart[0])
    module.exit_json(
        changed=answer["changed"],
        security=after,
        restart_required=restart,
        diff=dict(before=answer.get("before") or {}, after=after),
    )


if __name__ == "__main__":
    main()
