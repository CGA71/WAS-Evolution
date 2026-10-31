#!/usr/bin/python
# -*- coding: utf-8 -*-
# Copyright (c) 2026, neo
# GNU General Public License v3.0+

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r"""
---
module: was_policy_set
short_description: Manage the web services policy sets of a WAS cell
version_added: "0.5.0"
description:
  - Imports product default policy sets, copies a set and adjusts the copy's
    policy types, and deletes sets, in one C(wsadmin) session.
  - A default is imported as it is and never adjusted in place; the next
    import would put the product's version back. Adjustments go on a copy.
  - Attaching a set to an application's services is part of the application
    deployment. A set still attached is refused deletion.
  - The policy_sets role drives it, through the C(policy_set_settings) filter.
notes:
  - Only the policy type attributes declared are compared and set.
options:
  policy_sets:
    description:
      - The sets, as the C(policy_set_settings) filter renders them - C(name),
        C(state), and for a present set C(from_default) or C(copy_of),
        C(description), C(policies).
    type: list
    elements: dict
    required: true
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
- name: HTTPS imported, and a corporate copy that also requires WS-Addressing
  wasevo.websphere.was_policy_set:
    policy_sets:
      - name: WSHTTPS default
        state: present
        from_default: WSHTTPS default
        policies: {}
      - name: Corporate HTTPS
        state: present
        copy_of: WSHTTPS default
        description: HTTPS for every partner service
        policies:
          WSAddressing: {enabled: "true"}
    profile_path: /app/profiles/Dmgr01
    admin_user: "{{ was_admin_user }}"
    admin_password: "{{ was_admin_password }}"
"""

RETURN = r"""
policy_sets:
  description: The declared present sets, as the cell holds them afterwards.
  returned: always
  type: list
  elements: dict
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
        policy_sets=dict(type="list", elements="dict", required=True),
    )
    module = AnsibleModule(argument_spec=argument_spec, supports_check_mode=True)
    sets = module.params["policy_sets"]
    if not sets:
        module.fail_json(msg="policy_sets is empty; the role skips the task instead of sending it")
    for entry in sets:
        if entry.get("state") not in ("present", "absent") or not entry.get("name"):
            module.fail_json(msg="every policy set needs a name and a state, present or absent")

    runner = WsadminRunner(module)
    try:
        answer = runner.run("policy_set", "present", dict(policy_sets=sets))
    except WsadminFailure as exc:
        module.fail_json(msg=str(exc))

    after = answer.get("after") or {}
    module.exit_json(
        changed=answer["changed"],
        policy_sets=after.get("policy_sets") or [],
        diff=dict(before=answer.get("before") or {}, after=after),
    )


if __name__ == "__main__":
    main()
