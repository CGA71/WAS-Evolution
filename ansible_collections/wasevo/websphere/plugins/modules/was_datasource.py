#!/usr/bin/python
# -*- coding: utf-8 -*-
# Copyright (c) 2026, neo
# GNU General Public License v3.0+

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r"""
---
module: was_datasource
short_description: Manage datasources, their connection pool and custom properties
version_added: "0.3.0"
description:
  - Creates, updates or removes datasources at one scope, through
    C(wsadmin), together with the connection pool settings and the custom
    properties the call declares.
  - Takes every datasource of a scope in one call, so one C(wsadmin) session
    serves them all.
notes:
  - Values arrive already rendered for WAS traditional. The role translates
    the shared model - the abstract vendor into a helper class, Liberty-style
    pool settings into WAS attribute names and seconds - so this module
    compares and writes, and does not translate.
  - Only what is declared is compared. A datasource carries dozens of pool
    settings and custom properties at their WAS defaults; reporting all of
    them would bury the one that changed, and resetting the undeclared ones
    would overwrite tuning done in the console on purpose.
  - WAS creates a datasource whose provider does not exist in that scope, or
    whose J2C alias does not exist, and the mistake surfaces as a connection
    failure at runtime. Both are refused here before anything is written,
    naming the step that creates the missing piece. In a check run they are a
    future, because that step ran in check mode as well.
options:
  scope:
    description: Where the datasources live. The roles default to the cluster.
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
  datasources:
    description: The datasources this call is about.
    type: list
    elements: dict
    required: true
    suboptions:
      name:
        description: Datasource name, unique within the scope.
        type: str
        required: true
      provider:
        description: Name of the JDBC provider of the same scope it is built on.
        type: str
        required: true
      jndi_name:
        description: JNDI name the applications look it up by.
        type: str
        required: true
      helper:
        description: Data store helper class.
        type: str
        required: true
      auth_alias:
        description: J2C authentication alias it presents. It must exist.
        type: str
        default: ""
      statement_cache_size:
        description: Prepared statement cache size.
        type: int
        default: 10
      properties:
        description: Custom properties, name to value. Only these are compared.
        type: dict
        default: {}
      pool:
        description:
          - Connection pool settings, by WAS attribute name - C(maxConnections),
            C(minConnections), C(connectionTimeout), C(reapTime),
            C(unusedTimeout), C(agedTimeout). Times in seconds.
          - Only these are compared.
        type: dict
        default: {}
  state:
    description:
      - C(present) creates the datasources that are missing and updates the
        ones that differ.
      - C(absent) removes exactly the datasources named.
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
- name: The extranet datasource
  wasevo.websphere.was_datasource:
    scope:
      type: cluster
      cluster: ClusterEXT01
    datasources:
      - name: as400Extranet
        provider: as400ExtranetProvider
        jndi_name: jdbc/as400/extranet
        helper: com.ibm.websphere.rsadapter.DB2AS400DataStoreHelper
        auth_alias: as400ExtranetAlias
        statement_cache_size: 20
        properties:
          databaseName: EXTRANET
          serverName: as400.example.internal
        pool:
          maxConnections: 30
          minConnections: 5
          connectionTimeout: 30
          unusedTimeout: 1800
    profile_path: /app/profiles/Dmgr01
    admin_user: "{{ was_admin_user }}"
    admin_password: "{{ was_admin_password }}"
"""

RETURN = r"""
datasources:
  description: The datasources named by the call, as the cell holds them afterwards - declared settings only.
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
        datasources=dict(
            type="list",
            elements="dict",
            required=True,
            options=dict(
                name=dict(type="str", required=True),
                provider=dict(type="str", required=True),
                jndi_name=dict(type="str", required=True),
                helper=dict(type="str", required=True),
                auth_alias=dict(type="str", default=""),
                statement_cache_size=dict(type="int", default=10),
                properties=dict(type="dict", default={}),
                pool=dict(type="dict", default={}),
            ),
        ),
        state=dict(type="str", default="present", choices=["present", "absent"]),
    )

    module = AnsibleModule(argument_spec=argument_spec, supports_check_mode=True)

    datasources = module.params["datasources"]
    if not datasources:
        module.fail_json(msg="datasources is empty; the role skips the task instead of sending it")
    names = [d["name"] for d in datasources]
    duplicates = sorted(set(n for n in names if names.count(n) > 1))
    if duplicates:
        module.fail_json(msg="datasource declared twice in one scope: %s" % ", ".join(duplicates))
    jndi = [d["jndi_name"] for d in datasources]
    clashes = sorted(set(j for j in jndi if jndi.count(j) > 1))
    if clashes:
        # Two datasources on one JNDI name: the lookup returns whichever the
        # server bound last, and the application talks to the wrong database.
        module.fail_json(msg="JNDI name used by two datasources: %s" % ", ".join(clashes))

    runner = WsadminRunner(module)
    try:
        answer = runner.run("datasource", module.params["state"], dict(
            scope=module.params["scope"],
            datasources=datasources,
        ))
    except WsadminFailure as exc:
        module.fail_json(msg=str(exc))

    after = answer.get("after") or {}
    module.exit_json(
        changed=answer["changed"],
        datasources=after.get("datasources") or [],
        diff=dict(before=answer.get("before") or {}, after=after),
    )


if __name__ == "__main__":
    main()
