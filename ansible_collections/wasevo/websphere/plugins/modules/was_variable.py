#!/usr/bin/python
# -*- coding: utf-8 -*-
# Copyright (c) 2026, CGA
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r"""
---
module: was_variable
short_description: Manage WebSphere variables in a WAS ND cell
version_added: "0.4.0"
description:
  - Creates, updates or removes WebSphere variables - the C(${NAME})
    substitutions of a scope, stored in its C(variables.xml) - through C(wsadmin).
  - Takes every variable of a scope in one call, so one C(wsadmin) session
    serves them all.
options:
  scope:
    description: Where the variables live. The roles default to the cluster.
    type: dict
    required: true
    suboptions:
      type:
        description: Scope kind.
        type: str
        required: true
        choices: [cluster, node, server, cell]
      cluster:
        description: Cluster name, for a cluster scope.
        type: str
      node:
        description: Node name, for a node or a server scope.
        type: str
      server:
        description: Server name, for a server scope.
        type: str
      cell:
        description: Cell name, for a cell scope.
        type: str
  variables:
    description: The variables this call is about.
    type: list
    elements: dict
    required: true
    suboptions:
      name:
        description: Symbolic name, unique within the scope.
        type: str
        required: true
      value:
        description: The value. Ignored when I(state=absent).
        type: str
        default: ""
      description:
        description: Free text shown in the administrative console.
        type: str
        default: ""
  state:
    description:
      - C(present) creates the variables that are missing and updates the ones that differ.
      - C(absent) removes exactly the variables named.
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
- name: The variables the orders application reads
  wasevo.websphere.was_variable:
    scope:
      type: cluster
      cluster: ClusterEXT01
    variables:
      - name: ORDERS_HOME
        value: /app/data/orders
    profile_path: /app/profiles/Dmgr01
    admin_user: "{{ was_admin_user }}"
    admin_password: "{{ was_admin_password }}"
"""

RETURN = r"""
variables:
  description: The variables named by the call, as the cell holds them afterwards.
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

SCOPE_SPEC = dict(
    type=dict(type="str", required=True, choices=["cluster", "node", "server", "cell"]),
    cluster=dict(type="str"),
    node=dict(type="str"),
    server=dict(type="str"),
    cell=dict(type="str"),
)


def main():
    argument_spec = dict(WSADMIN_COMMON_ARGS)
    argument_spec.update(
        scope=dict(type="dict", required=True, options=SCOPE_SPEC),
        variables=dict(
            type="list",
            elements="dict",
            required=True,
            options=dict(
                name=dict(type="str", required=True),
                value=dict(type="str", default=""),
                description=dict(type="str", default=""),
            ),
        ),
        state=dict(type="str", default="present", choices=["present", "absent"]),
    )

    module = AnsibleModule(argument_spec=argument_spec, supports_check_mode=True)

    variables = module.params["variables"]
    if not variables:
        module.fail_json(msg="variables is empty; the role skips the task instead of sending it")
    names = [v["name"] for v in variables]
    duplicates = sorted(set(n for n in names if names.count(n) > 1))
    if duplicates:
        module.fail_json(msg="variable declared twice in one scope: %s" % ", ".join(duplicates))

    runner = WsadminRunner(module)
    try:
        answer = runner.run("variable", module.params["state"], dict(
            scope=module.params["scope"],
            variables=variables,
        ))
    except WsadminFailure as exc:
        module.fail_json(msg=str(exc))

    after = answer.get("after") or {}
    module.exit_json(
        changed=answer["changed"],
        variables=after.get("variables") or [],
        diff=dict(before=answer.get("before") or {}, after=after),
    )


if __name__ == "__main__":
    main()
