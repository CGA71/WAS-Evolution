#!/usr/bin/python
# -*- coding: utf-8 -*-
# Copyright (c) 2026, neo
# GNU General Public License v3.0+

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r"""
---
module: was_server_settings
short_description: Set the settings every server of a target carries - transactions, EJB, JPA, cache, logging, PMI, JVM
version_added: "0.4.0"
description:
  - Sets attributes on the objects every application server carries - its
    transaction service, EJB container, EJB cache, EJB timer service, JPA
    service, dynamic cache, web container, logging and trace services in
    both modes, PMI service - and JVM custom properties, on every server of
    a target, in one C(wsadmin) session.
  - A cluster target means the members the cell holds now, read from the
    cell, so a member added since the last run is caught up by a replay.
  - Also sets cluster attributes, such as transaction peer recovery, and the
    JPA specification level of the target.
  - The transactions, EJB container, CDI, JPA, dynamic cache, logging and
    PMI roles drive it; each translates an intent into the WAS attributes
    this module applies.
notes:
  - Every declared attribute is checked against C(AdminConfig.attributes) for
    its type before anything is written; an unknown name is refused with the
    valid ones.
  - Refused before anything is written - persistent EJB timers on several
    servers with neither a shared datasource nor a custom scheduler, and a
    datasource named by the settings that the cell does not have.
  - Most of these settings take effect when a server restarts. The result
    lists the servers whose configuration changed, in C(restart_required),
    and the module warns about them; it restarts nothing.
  - There is no state absent. A setting is set back by declaring the WAS
    default.
options:
  target:
    description: The servers the settings apply to - a cluster, or one server.
    type: dict
    required: true
    suboptions:
      cluster:
        description: A cluster name; every member the cell holds.
        type: str
      node:
        description: Node of a single server.
        type: str
      server:
        description: A single server name.
        type: str
  components:
    description:
      - Configuration type to attributes. Types are C(TransactionService),
        C(EJBContainer), C(EJBCache), C(EJBTimer), C(JavaPersistenceAPIService),
        C(DynamicCache), C(WebContainer), C(RASLoggingService), C(TraceService),
        C(TraceLog), C(HighPerformanceExtensibleLogging), C(HPELLog),
        C(HPELTrace), C(HPELTextLog), C(PMIService).
      - Only the attributes named are compared and set.
    type: dict
    default: {}
  jvm_properties:
    description: JVM custom properties, name to value, on every server of the target.
    type: dict
    default: {}
  cluster_attributes:
    description: Attributes of the cluster object, for a cluster target.
    type: dict
    default: {}
  jpa_spec_level:
    description: The JPA specification level of the target, C(2.0) or C(2.1).
    type: str
    choices: ["2.0", "2.1"]
  requires_datasources:
    description: JNDI names of datasources the settings refer to, which must exist in the cell.
    type: list
    elements: str
    default: []
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
- name: Transaction timeouts and peer recovery on the cluster
  wasevo.websphere.was_server_settings:
    target:
      cluster: ClusterEXT01
    components:
      TransactionService:
        totalTranLifetimeTimeout: "300"
        transactionLogDirectory: /shared/tranlog/ClusterEXT01
    cluster_attributes:
      enableHA: "true"
    profile_path: /app/profiles/Dmgr01
    admin_user: "{{ was_admin_user }}"
    admin_password: "{{ was_admin_password }}"
"""

RETURN = r"""
settings:
  description: The declared settings, per server, as the cell holds them afterwards.
  returned: always
  type: dict
restart_required:
  description: The servers, as node/server, whose configuration changed and which need a restart to apply it.
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

TARGET_SPEC = dict(
    cluster=dict(type="str"),
    node=dict(type="str"),
    server=dict(type="str"),
)


def restart_list(before, after):
    """The servers whose settings differ between two reads.

    A cluster-wide change - peer recovery, the JPA level - concerns every
    member, since each reads it at startup.
    """
    old = (before or {}).get("servers") or {}
    new = (after or {}).get("servers") or {}
    cluster_wide = any(
        (before or {}).get(key) != (after or {}).get(key)
        for key in ("cluster_attributes", "jpa_spec_level")
    )
    return sorted(k for k in new if cluster_wide or old.get(k) != new.get(k))


def main():
    argument_spec = dict(WSADMIN_COMMON_ARGS)
    argument_spec.update(
        target=dict(type="dict", required=True, options=TARGET_SPEC),
        components=dict(type="dict", default={}),
        jvm_properties=dict(type="dict", default={}),
        cluster_attributes=dict(type="dict", default={}),
        jpa_spec_level=dict(type="str", choices=["2.0", "2.1"]),
        requires_datasources=dict(type="list", elements="str", default=[]),
    )

    module = AnsibleModule(argument_spec=argument_spec, supports_check_mode=True)

    target = module.params["target"]
    if not target.get("cluster") and not (target.get("node") and target.get("server")):
        module.fail_json(msg="target needs a cluster, or a node and a server")
    if target.get("cluster") and (target.get("node") or target.get("server")):
        module.fail_json(msg="target is a cluster or a server, not both")
    if module.params["cluster_attributes"] and not target.get("cluster"):
        module.fail_json(msg="cluster_attributes need a cluster target")
    if not (module.params["components"] or module.params["jvm_properties"]
            or module.params["cluster_attributes"] or module.params["jpa_spec_level"]):
        module.fail_json(msg="no setting in the call; the role skips the task instead of sending it")

    params = dict(
        (key, module.params[key]) for key in (
            "target", "components", "jvm_properties", "cluster_attributes",
            "jpa_spec_level", "requires_datasources",
        )
    )

    runner = WsadminRunner(module)
    try:
        answer = runner.run("server_settings", "present", params)
    except WsadminFailure as exc:
        module.fail_json(msg=str(exc))

    before = answer.get("before") or {}
    after = answer.get("after") or {}
    restart = restart_list(before, after) if answer["changed"] else []
    if restart:
        module.warn("restart needed to apply the change: %s" % ", ".join(restart))
    module.exit_json(
        changed=answer["changed"],
        settings=after,
        restart_required=restart,
        diff=dict(before=before, after=after),
    )


if __name__ == "__main__":
    main()
