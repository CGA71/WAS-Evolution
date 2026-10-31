#!/usr/bin/python
# -*- coding: utf-8 -*-
# Copyright (c) 2026, neo
# GNU General Public License v3.0+

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r"""
---
module: was_j2c_alias
short_description: Manage J2C authentication aliases in a WAS ND cell
version_added: "0.3.0"
description:
  - Creates, updates or removes J2C authentication aliases - the credentials a
    datasource, a JMS connection factory or a bus member presents to what it
    connects to.
  - Takes every alias of a run in one call, so one C(wsadmin) session serves
    them all.
notes:
  - An alias is cell-wide. It lives in the security configuration of the
    cell, not in a cluster or a server, so this module takes no scope.
  - The password cannot be compared - WAS stores it encoded and returns
    nothing a plan could compare against. I(password_policy) says what to do
    about that, and C(changed) reports only what the module can know.
  - The password never appears in the module result, in a diff or in a log.
    It travels in the 0600 payload file the module removes.
options:
  aliases:
    description: The aliases this call is about.
    type: list
    elements: dict
    required: true
    suboptions:
      name:
        description: Alias name, as a datasource refers to it.
        type: str
        required: true
      user:
        description: User the alias presents.
        type: str
        required: true
      password:
        description:
          - Password the alias presents.
          - Required to create an alias. Optional for C(state=absent).
        type: str
      description:
        description: Free text shown in the administrative console.
        type: str
        default: ""
  password_policy:
    description:
      - C(on_create) sets the password when the alias is created and leaves it
        alone afterwards. Replays report changed only for the user and the
        description, which can be compared.
      - C(always) writes the password on every run, and every run reports
        changed, because it might have. This is how a database password is
        rotated - one replay of this module, nothing else.
    type: str
    choices: [on_create, always]
    default: on_create
  state:
    description:
      - C(present) creates the aliases that are missing and updates the ones
        that differ.
      - C(absent) removes exactly the aliases named.
    type: str
    choices: [present, absent]
    default: present
  profile_path:
    description: Path to the WAS profile whose C(bin/wsadmin.sh) is used - the deployment manager's.
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
- name: The alias the extranet datasource presents
  wasevo.websphere.was_j2c_alias:
    aliases:
      - name: as400ExtranetAlias
        user: wsextranet
        password: "{{ lookup('env', 'AS400_EXTRANET_PASSWORD') }}"
        description: AS/400 extranet database
    profile_path: /app/profiles/Dmgr01
    admin_user: "{{ was_admin_user }}"
    admin_password: "{{ was_admin_password }}"

- name: Rotate that password - the only change this run makes
  wasevo.websphere.was_j2c_alias:
    aliases:
      - name: as400ExtranetAlias
        user: wsextranet
        password: "{{ lookup('env', 'AS400_EXTRANET_PASSWORD') }}"
    password_policy: always
    profile_path: /app/profiles/Dmgr01
    admin_user: "{{ was_admin_user }}"
    admin_password: "{{ was_admin_password }}"
"""

RETURN = r"""
aliases:
  description: The aliases named by the call, as the cell holds them afterwards. Never the password.
  returned: always
  type: list
  elements: dict
  sample:
    - name: as400ExtranetAlias
      user: wsextranet
      description: AS/400 extranet database
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
        aliases=dict(
            type="list",
            elements="dict",
            required=True,
            options=dict(
                name=dict(type="str", required=True),
                user=dict(type="str", required=True),
                password=dict(type="str", no_log=True),
                description=dict(type="str", default=""),
            ),
        ),
        # Not a secret, despite its name - stated, so Ansible does not warn on
        # every run that it might be one.
        password_policy=dict(type="str", default="on_create", choices=["on_create", "always"], no_log=False),
        state=dict(type="str", default="present", choices=["present", "absent"]),
    )

    module = AnsibleModule(argument_spec=argument_spec, supports_check_mode=True)

    aliases = module.params["aliases"]
    if not aliases:
        module.fail_json(msg="aliases is empty; the role skips the task instead of sending it")

    seen = set()
    for alias in aliases:
        if alias["name"] in seen:
            module.fail_json(msg="alias %s is declared twice" % alias["name"])
        seen.add(alias["name"])
        if module.params["state"] == "present" and not alias.get("password"):
            # Refused here, before wsadmin, and by name: an alias created with
            # an empty password authenticates nowhere, and the failure would
            # surface later as a database refusing a connection.
            module.fail_json(
                msg="alias %s has no password. It is required to create an "
                    "alias, and comes from a credential - never from a versioned "
                    "file." % alias["name"]
            )

    runner = WsadminRunner(module)
    try:
        answer = runner.run("j2c_alias", module.params["state"], dict(
            aliases=aliases,
            password_policy=module.params["password_policy"],
        ))
    except WsadminFailure as exc:
        module.fail_json(msg=str(exc))

    after = answer.get("after") or {}
    module.exit_json(
        changed=answer["changed"],
        aliases=after.get("aliases") or [],
        diff=dict(before=answer.get("before") or {}, after=after),
    )


if __name__ == "__main__":
    main()
