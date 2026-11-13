#!/usr/bin/python
# -*- coding: utf-8 -*-
# Copyright (c) 2026, CGA
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r"""
---
module: was_cluster
short_description: Manage a WebSphere Application Server ND server cluster
version_added: "0.1.0"
description:
  - Creates, updates or removes a server cluster in a WAS ND cell through
    C(wsadmin).
  - Pilot module for the traditional plane. It validates the whole chain --
    module to Jython driver to wsadmin -- including real C(check_mode) and
    C(diff) support, before the remaining resource types are ported.
  - Reads and writes within a single C(wsadmin) session, so one JVM start per
    call instead of the two the legacy Exist/Add script pair required.
notes:
  - The Jython driver must already be staged on the target. Run the
    C(wasevo.websphere.traditional.config) role first; it copies
    C(plugins/jython/) to I(jython_dir).
  - The administrative password is never placed on a command line. It is
    written to a 0600 properties file passed with C(-wsadmin_properties) and
    removed afterwards.
  - Applies only to WAS traditional. Liberty has no C(wsadmin); its clustering
    model is Deployment replicas, handled by the C(liberty/*) roles.
options:
  name:
    description: Cluster name.
    type: str
    required: true
  cell_name:
    description: Cell the cluster belongs to.
    type: str
    required: true
  prefer_local:
    description:
      - Whether to route EJB requests to a local cluster member when one is
        available.
      - Declared as a string because WAS expects the literal C("true") or
        C("false"); YAML would otherwise hand over a Python boolean, which
        renders as C(True) and is silently rejected.
    type: str
    choices: ["true", "false"]
    default: "true"
  state:
    description:
      - C(present) creates or updates the cluster.
      - C(absent) deletes it, implemented deliberately, because the legacy
        code advertises C(absent) on 34 resource types and implements it on
        5 while decommissioning depends on it.
    type: str
    choices: [present, absent]
    default: present
  profile_path:
    description: Path to the WAS profile whose C(bin/wsadmin.sh) is used.
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
    description:
      - Synchronise the nodes after a change.
      - Only ever triggered when something actually changed, which is why a
        truthful C(changed) matters.
    type: bool
    default: true
author:
  - neo
"""

EXAMPLES = r"""
- name: Declare the extranet cluster
  wasevo.websphere.was_cluster:
    name: "{{ was_cluster_name }}"
    cell_name: "{{ was_cell_name }}"
    prefer_local: "true"
    state: present
    profile_path: "{{ was_profile_path }}"
    admin_user: "{{ was_admin_user }}"
    admin_password: "{{ was_admin_password }}"

- name: Show what would change without touching the cell
  wasevo.websphere.was_cluster:
    name: "{{ was_cluster_name }}"
    cell_name: "{{ was_cell_name }}"
    prefer_local: "false"
    profile_path: "{{ was_profile_path }}"
    admin_user: "{{ was_admin_user }}"
    admin_password: "{{ was_admin_password }}"
  check_mode: true
  diff: true

- name: Remove a cluster during decommissioning
  wasevo.websphere.was_cluster:
    name: ClusterLegacy
    cell_name: "{{ was_cell_name }}"
    state: absent
    profile_path: "{{ was_profile_path }}"
    admin_user: "{{ was_admin_user }}"
    admin_password: "{{ was_admin_password }}"
"""

RETURN = r"""
cluster:
  description: Cluster state after the task, as read back from the cell.
  returned: always
  type: dict
  sample:
    exists: true
    name: ClusterEXT
    prefer_local: "true"
    members:
      - name: ClusterEXT_PREPRODNode01_01
        node: PREPRODNode01
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
        name=dict(type="str", required=True),
        cell_name=dict(type="str", required=True),
        prefer_local=dict(type="str", default="true", choices=["true", "false"]),
        state=dict(type="str", default="present", choices=["present", "absent"]),
    )

    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
    )

    resource_params = dict(
        name=module.params["name"],
        cell_name=module.params["cell_name"],
        prefer_local=module.params["prefer_local"],
    )

    runner = WsadminRunner(module)
    try:
        answer = runner.run("cluster", module.params["state"], resource_params)
    except WsadminFailure as exc:
        module.fail_json(msg=str(exc))

    module.exit_json(
        changed=answer["changed"],
        cluster=answer.get("after") or {},
        diff=dict(
            before=answer.get("before") or {},
            after=answer.get("after") or {},
        ),
    )


if __name__ == "__main__":
    main()
