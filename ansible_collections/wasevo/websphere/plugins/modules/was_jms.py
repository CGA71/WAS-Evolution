#!/usr/bin/python
# -*- coding: utf-8 -*-
# Copyright (c) 2026, neo
# GNU General Public License v3.0+

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r"""
---
module: was_jms
short_description: Manage JMS connection factories, queues, topics and activation specifications
version_added: "0.3.0"
description:
  - Creates, updates or removes the JMS resources of one messaging provider at
    one scope - connection factories, queues, topics, activation
    specifications - in one C(wsadmin) session.
  - The provider is the default messaging provider, C(sib), whose resources
    run on a service integration bus, or IBM MQ, C(mq), whose resources name a
    queue manager.
notes:
  - Refused before anything is written, because WAS accepts them and the
    application meets the mistake at runtime - a JMS queue whose bus
    destination does not exist or is a topic space; a JMS topic whose topic
    space is not one; an activation specification listening on a JNDI name no
    queue or topic carries, or carrying the wrong type; a J2C alias that does
    not exist; two resources on one JNDI name; on IBM MQ, a CLIENT transport
    with neither a host nor a connection name list.
  - In a check run the bus and its destinations may not exist yet - the bus
    step of the same run created nothing either - and those checks stand down.
  - Only the fields a resource declares are compared. A connection factory's
    C(type) is applied at creation only, as WAS does not change it in place.
options:
  scope:
    description: Where the resources live. The roles default to the cluster.
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
  provider:
    description: The messaging provider.
    type: str
    choices: [sib, mq]
    default: sib
  connection_factories:
    description:
      - Connection factories - C(name), C(jndi_name), C(auth_alias), C(type), C(description).
      - On C(sib), C(bus); C(type) is queue, topic, or unified when omitted.
      - On C(mq), C(qmgr), C(transport) (BINDINGS, CLIENT, BINDINGS_THEN_CLIENT),
        C(host), C(port), C(channel), C(connection_list); C(type) is CF, QCF or TCF.
    type: list
    elements: dict
    default: []
  queues:
    description:
      - JMS queues - C(name), C(jndi_name), C(queue), C(description).
      - On C(sib), C(queue) is the bus queue destination, with C(bus) and C(delivery_mode).
      - On C(mq), C(queue) is the queue on the queue manager, with C(qmgr) and C(persistence).
    type: list
    elements: dict
    default: []
  topics:
    description:
      - JMS topics - C(name), C(jndi_name), C(topic_name), C(description).
      - On C(sib), C(topic_space), C(bus) and C(delivery_mode).
      - On C(mq), C(persistence).
    type: list
    elements: dict
    default: []
  activation_specs:
    description:
      - Activation specifications - C(name), C(jndi_name), C(destination_jndi),
        C(destination_type) (javax.jms.Queue or javax.jms.Topic),
        C(max_concurrency), C(auth_alias), C(description).
      - On C(sib), C(bus). On C(mq), the connection keys of a connection
        factory, and C(max_concurrency) is the server session pool size.
    type: list
    elements: dict
    default: []
  known_destinations:
    description:
      - JMS queues and topics declared at other scopes, JNDI name to type.
        An activation specification may listen on one of them, since WAS
        resolves a JNDI name through the scopes. The role fills it.
    type: dict
    default: {}
  state:
    description:
      - C(present) creates the resources that are missing and updates the ones
        that differ - destinations before what refers to them.
      - C(absent) removes exactly the resources named - what listens before
        what it listens on.
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
- name: The orders JMS resources, on the orders bus
  wasevo.websphere.was_jms:
    scope:
      type: cluster
      cluster: ClusterEXT01
    provider: sib
    connection_factories:
      - { name: OrdersCF, jndi_name: jms/ordersCF, bus: OrdersBus }
    queues:
      - { name: OrdersQueue, jndi_name: jms/orders, queue: OrdersQueue, bus: OrdersBus }
    activation_specs:
      - { name: OrdersAS, jndi_name: jms/ordersAS, destination_jndi: jms/orders, bus: OrdersBus }
    profile_path: /app/profiles/Dmgr01
    admin_user: "{{ was_admin_user }}"
    admin_password: "{{ was_admin_password }}"
"""

RETURN = r"""
jms:
  description: The resources named by the call, as the cell holds them afterwards - declared fields only.
  returned: always
  type: dict
"""

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.wasevo.websphere.plugins.module_utils.wsadmin import (
    WSADMIN_COMMON_ARGS,
    WsadminFailure,
    WsadminRunner,
)

KINDS = ("connection_factories", "queues", "topics", "activation_specs")
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
        provider=dict(type="str", default="sib", choices=["sib", "mq"]),
        connection_factories=dict(type="list", elements="dict", default=[]),
        queues=dict(type="list", elements="dict", default=[]),
        topics=dict(type="list", elements="dict", default=[]),
        activation_specs=dict(type="list", elements="dict", default=[]),
        known_destinations=dict(type="dict", default={}),
        state=dict(type="str", default="present", choices=["present", "absent"]),
    )

    module = AnsibleModule(argument_spec=argument_spec, supports_check_mode=True)

    if not any(module.params[kind] for kind in KINDS):
        module.fail_json(msg="no JMS resource in the call; the role skips the task instead of sending it")
    for kind in KINDS:
        for resource in module.params[kind]:
            if not resource.get("name") or not resource.get("jndi_name"):
                module.fail_json(msg="every %s entry needs a name and a jndi_name: %r" % (kind, resource))

    params = dict((kind, module.params[kind]) for kind in KINDS)
    params.update(
        scope=module.params["scope"],
        provider=module.params["provider"],
        known_destinations=module.params["known_destinations"],
    )

    runner = WsadminRunner(module)
    try:
        answer = runner.run("jms", module.params["state"], params)
    except WsadminFailure as exc:
        module.fail_json(msg=str(exc))

    after = answer.get("after") or {}
    module.exit_json(
        changed=answer["changed"],
        jms=after,
        diff=dict(before=answer.get("before") or {}, after=after),
    )


if __name__ == "__main__":
    main()
