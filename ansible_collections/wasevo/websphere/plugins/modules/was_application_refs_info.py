#!/usr/bin/python
# -*- coding: utf-8 -*-
# Copyright (c) 2026, CGA
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r"""
---
module: was_application_refs_info
short_description: What the installed applications of a WAS ND cell still use
version_added: "0.4.0"
description:
  - Reads, in one C(wsadmin) session, the JNDI names and shared libraries every
    installed application - except the excluded ones - is bound to, and which
    datasources and J2C connection factories present each J2C alias.
  - The C(traditional.application) role reads it before a decommissioning, to
    keep the resources another application still uses. Read-only.
options:
  exclude:
    description: Applications to leave out - the one being decommissioned.
    type: list
    elements: str
    default: []
  cluster:
    description:
      - The cluster the application ran on. Every node hosting one of its
        members is inspected - its application servers, clustered or not, and
        the resources scoped to it or to its servers - for the node removal
        decision.
    type: str
  profile_path:
    description: Path to the deployment manager profile whose C(bin/wsadmin.sh) is used.
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
    description: Unused - nothing is written.
    type: bool
    default: false
  sync_nodes:
    description: Unused - nothing is written.
    type: bool
    default: false
author:
  - neo
"""

EXAMPLES = r"""
- name: What the other applications still use
  wasevo.websphere.was_application_refs_info:
    exclude: [OrdersApp]
    profile_path: /app/profiles/Dmgr01
    admin_user: "{{ was_admin_user }}"
    admin_password: "{{ was_admin_password }}"
  register: refs
"""

RETURN = r"""
applications:
  description: Per application, the JNDI names and the shared libraries it is bound to, and its targets.
  returned: always
  type: dict
jndi:
  description: Every JNDI name an application left in the cell is bound to.
  returned: always
  type: list
  elements: str
libraries:
  description: Every shared library an application left in the cell is bound to.
  returned: always
  type: list
  elements: str
auth_aliases:
  description: Per J2C alias, the datasources and J2C connection factories that present it.
  returned: always
  type: dict
cluster_members:
  description: Per cluster, its members as node/server.
  returned: always
  type: dict
nodes:
  description: Per node hosting a member of I(cluster), its application servers and the resources scoped to it or to them.
  returned: when I(cluster) is given
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
        exclude=dict(type="list", elements="str", default=[]),
        cluster=dict(type="str"),
        save_config=dict(type="bool", default=False),
        sync_nodes=dict(type="bool", default=False),
    )
    module = AnsibleModule(argument_spec=argument_spec, supports_check_mode=True)

    runner = WsadminRunner(module)
    try:
        answer = runner.run("application_refs", "present", dict(
            exclude=module.params["exclude"], cluster=module.params["cluster"]))
    except WsadminFailure as exc:
        module.fail_json(msg=str(exc))

    refs = answer.get("before") or {}
    module.exit_json(
        changed=False,
        applications=refs.get("applications") or {},
        jndi=refs.get("jndi") or [],
        libraries=refs.get("libraries") or [],
        auth_aliases=refs.get("auth_aliases") or {},
        cluster_members=refs.get("cluster_members") or {},
        nodes=refs.get("nodes") or {},
    )


if __name__ == "__main__":
    main()
