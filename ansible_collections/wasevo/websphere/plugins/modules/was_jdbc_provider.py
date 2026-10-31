#!/usr/bin/python
# -*- coding: utf-8 -*-
# Copyright (c) 2026, neo
# GNU General Public License v3.0+

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r"""
---
module: was_jdbc_provider
short_description: Manage JDBC providers in a WAS ND cell
version_added: "0.3.0"
description:
  - Creates, updates or removes JDBC providers - the driver a datasource is
    built on - at one scope, through C(wsadmin).
  - Takes every provider of a scope in one call, so one C(wsadmin) session
    serves them all.
notes:
  - The provider type is checked against the JDBC provider templates the cell
    offers before a provider is created. One the cell does not offer is
    refused with the list of those it does, rather than left to fail inside
    C(createJDBCProvider) with an exception that names neither.
  - The classpath is a list attribute, and C(AdminConfig.modify) appends to a
    list rather than replacing it. A changed classpath is therefore unset and
    rewritten, so the old jar cannot stay ahead of the new one.
  - In a check run, a scope that does not exist yet is a future - an earlier
    step of the same run creates it - and every provider is planned as new.
    In a real run it is refused, naming the step that creates it.
options:
  scope:
    description: Where the providers live. The roles default to the cluster.
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
  providers:
    description: The providers this call is about.
    type: list
    elements: dict
    required: true
    suboptions:
      name:
        description: Provider name, unique within the scope.
        type: str
        required: true
      database_type:
        description: C(createJDBCProvider -databaseType), for instance C(DB2).
        type: str
        required: true
      provider_type:
        description: C(createJDBCProvider -providerType) - a template name the cell offers.
        type: str
        required: true
      implementation_type:
        description: C(createJDBCProvider -implementationType), for instance C(Connection pool data source).
        type: str
        required: true
      classpath:
        description: Driver jars, separated by C(;).
        type: str
        default: ""
      native_path:
        description: Native libraries, separated by C(;).
        type: str
        default: ""
      description:
        description: Free text shown in the administrative console.
        type: str
        default: ""
  state:
    description:
      - C(present) creates the providers that are missing and updates the ones
        that differ.
      - C(absent) removes exactly the providers named - and with them every
        datasource built on them, which is how WAS removes a provider.
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
- name: The driver the extranet datasource is built on
  wasevo.websphere.was_jdbc_provider:
    scope:
      type: cluster
      cluster: ClusterEXT01
    providers:
      - name: as400ExtranetProvider
        database_type: DB2
        provider_type: DB2 UDB for iSeries (Toolbox)
        implementation_type: Connection pool data source
        classpath: /app/binaries/was90/jdbcprovider/jt400.jar
    profile_path: /app/profiles/Dmgr01
    admin_user: "{{ was_admin_user }}"
    admin_password: "{{ was_admin_password }}"
"""

RETURN = r"""
providers:
  description: The providers named by the call, as the cell holds them afterwards.
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
        providers=dict(
            type="list",
            elements="dict",
            required=True,
            options=dict(
                name=dict(type="str", required=True),
                database_type=dict(type="str", required=True),
                provider_type=dict(type="str", required=True),
                implementation_type=dict(type="str", required=True),
                classpath=dict(type="str", default=""),
                native_path=dict(type="str", default=""),
                description=dict(type="str", default=""),
            ),
        ),
        state=dict(type="str", default="present", choices=["present", "absent"]),
    )

    module = AnsibleModule(argument_spec=argument_spec, supports_check_mode=True)

    providers = module.params["providers"]
    if not providers:
        module.fail_json(msg="providers is empty; the role skips the task instead of sending it")
    names = [p["name"] for p in providers]
    duplicates = sorted(set(n for n in names if names.count(n) > 1))
    if duplicates:
        module.fail_json(msg="provider declared twice in one scope: %s" % ", ".join(duplicates))

    runner = WsadminRunner(module)
    try:
        answer = runner.run("jdbc_provider", module.params["state"], dict(
            scope=module.params["scope"],
            providers=providers,
        ))
    except WsadminFailure as exc:
        module.fail_json(msg=str(exc))

    after = answer.get("after") or {}
    module.exit_json(
        changed=answer["changed"],
        providers=after.get("providers") or [],
        diff=dict(before=answer.get("before") or {}, after=after),
    )


if __name__ == "__main__":
    main()
