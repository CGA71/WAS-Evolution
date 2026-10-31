#!/usr/bin/python
# -*- coding: utf-8 -*-
# Copyright (c) 2026, neo
# GNU General Public License v3.0+

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r"""
---
module: was_sibus
short_description: Manage a service integration bus, its members and its destinations
version_added: "0.3.0"
description:
  - Creates, updates or deletes a service integration bus - the embedded
    messaging of WAS traditional, which JMS on the default messaging provider
    runs on - together with the members that host its messaging engines and
    the destinations it carries.
  - The whole bus is reconciled in one C(wsadmin) session, in the order its
    parts depend on each other.
notes:
  - There is no Liberty equivalent. Moving to Liberty means an external
    broker; see the repository README, section 10.
  - A member's message store and engine policy are fixed when its engine is
    created. Changing either recreates the engine and discards every message
    it holds, so a declared store that differs from the live one is reported
    as a warning and never changed by a run.
  - The engine policy is applied when a cluster member is added and is not
    read back; it lives in the core group's HA policies, not on the member.
  - A member the cell has and the call does not name is left alone.
  - An exception destination that is neither a destination of the bus nor a
    system one is refused, because WAS accepts any string there and failed
    messages then have nowhere to go.
options:
  bus:
    description: Bus name.
    type: str
    required: true
  description:
    description: Free text shown in the administrative console.
    type: str
    default: ""
  security:
    description: Enable bus security. Applied when the bus is created.
    type: bool
    default: false
  members:
    description: The bus members - clusters or servers that host its messaging engines.
    type: list
    elements: dict
    default: []
    suboptions:
      cluster:
        description: A cluster bus member.
        type: str
      node:
        description: Node of a server bus member.
        type: str
      server:
        description: A server bus member.
        type: str
      store:
        description: Message store of the member's engine.
        type: str
        choices: [file, data]
        default: file
      policy:
        description:
          - Engine policy of a cluster member. C(HA) is one engine that fails
            over between members; C(SCALABILITY) is one engine per member.
        type: str
        choices: [HA, SCALABILITY, SCALABILITY_HA]
        default: HA
      file_store:
        description: Directories of a file store - C(log_dir), C(permanent_dir), C(temporary_dir).
        type: dict
      data_store:
        description: A data store - C(datasource_jndi), C(auth_alias), C(schema), C(create_tables).
        type: dict
  destinations:
    description: The destinations the bus carries.
    type: list
    elements: dict
    default: []
    suboptions:
      name:
        description: Destination name.
        type: str
        required: true
      type:
        description: Destination kind.
        type: str
        choices: [queue, topic_space]
        default: queue
      reliability:
        description: Default reliability of the messages it carries.
        type: str
        choices: [BEST_EFFORT_NONPERSISTENT, EXPRESS_NONPERSISTENT, RELIABLE_NONPERSISTENT, RELIABLE_PERSISTENT, ASSURED_PERSISTENT]
        default: ASSURED_PERSISTENT
      max_failed_deliveries:
        description: Deliveries attempted before a message goes to the exception destination.
        type: int
        default: 5
      exception_destination:
        description: Where failed messages go. Empty means the system default.
        type: str
        default: ""
      description:
        description: Free text shown in the administrative console.
        type: str
        default: ""
      member:
        description: The bus member a queue is localised on. Defaults to the first member.
        type: dict
  state:
    description:
      - C(present) creates or updates the bus, adds missing members, creates
        and updates destinations.
      - C(absent) deletes the bus, and with it its members, their engines,
        every message they hold, and its destinations.
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
- name: The orders bus, on the cluster
  wasevo.websphere.was_sibus:
    bus: OrdersBus
    members:
      - cluster: ClusterEXT01
        store: file
        policy: HA
    destinations:
      - name: OrdersQueue
        exception_destination: OrdersDeadLetters
      - name: OrdersDeadLetters
      - name: PricesTopic
        type: topic_space
        reliability: RELIABLE_NONPERSISTENT
    profile_path: /app/profiles/Dmgr01
    admin_user: "{{ was_admin_user }}"
    admin_password: "{{ was_admin_password }}"
"""

RETURN = r"""
bus:
  description: The bus as the cell holds it afterwards - members and destinations named by the call.
  returned: always
  type: dict
drifts:
  description: Declared message stores that differ from the live ones, which no run changes.
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


def main():
    argument_spec = dict(WSADMIN_COMMON_ARGS)
    argument_spec.update(
        bus=dict(type="str", required=True),
        description=dict(type="str", default=""),
        security=dict(type="bool", default=False),
        members=dict(
            type="list", elements="dict", default=[],
            options=dict(
                cluster=dict(type="str"),
                node=dict(type="str"),
                server=dict(type="str"),
                store=dict(type="str", default="file", choices=["file", "data"]),
                policy=dict(type="str", default="HA", choices=["HA", "SCALABILITY", "SCALABILITY_HA"]),
                file_store=dict(type="dict"),
                data_store=dict(type="dict"),
            ),
        ),
        destinations=dict(
            type="list", elements="dict", default=[],
            options=dict(
                name=dict(type="str", required=True),
                type=dict(type="str", default="queue", choices=["queue", "topic_space"]),
                reliability=dict(
                    type="str", default="ASSURED_PERSISTENT",
                    choices=["BEST_EFFORT_NONPERSISTENT", "EXPRESS_NONPERSISTENT",
                             "RELIABLE_NONPERSISTENT", "RELIABLE_PERSISTENT", "ASSURED_PERSISTENT"],
                ),
                max_failed_deliveries=dict(type="int", default=5),
                exception_destination=dict(type="str", default=""),
                description=dict(type="str", default=""),
                member=dict(type="dict"),
            ),
        ),
        state=dict(type="str", default="present", choices=["present", "absent"]),
    )

    module = AnsibleModule(argument_spec=argument_spec, supports_check_mode=True)

    if module.params["state"] == "present":
        if not module.params["members"]:
            module.fail_json(
                msg="bus %s has no member. A bus with no member has no messaging "
                    "engine, so no queue point and nothing to carry a message."
                    % module.params["bus"]
            )
        for member in module.params["members"]:
            if not member.get("cluster") and not (member.get("node") and member.get("server")):
                module.fail_json(msg="a bus member is a cluster, or a node and a server")

    runner = WsadminRunner(module)
    try:
        answer = runner.run("sibus", module.params["state"], dict(
            bus=module.params["bus"],
            description=module.params["description"],
            security=module.params["security"],
            members=module.params["members"],
            destinations=module.params["destinations"],
        ))
    except WsadminFailure as exc:
        module.fail_json(msg=str(exc))

    after = answer.get("after") or {}
    drifts = after.pop("drifts", []) if isinstance(after, dict) else []
    # A warning, not a failure: the run did what it can, and what it cannot
    # do safely has to be seen - it is the one thing a green run hides.
    for drift in drifts:
        module.warn(drift)

    module.exit_json(
        changed=answer["changed"],
        bus=after,
        drifts=drifts,
        diff=dict(before=answer.get("before") or {}, after=after),
    )


if __name__ == "__main__":
    main()
