#!/usr/bin/python
# -*- coding: utf-8 -*-
# Copyright (c) 2026, CGA
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r"""
---
module: was_cluster_member
short_description: Manage the application servers that are members of a WAS ND cluster
version_added: "0.2.0"
description:
  - Creates, adjusts or removes the application servers that make up a server
    cluster in a WAS ND cell, through C(wsadmin).
  - A cluster member is an application server. The same object, owned by the
    cell and created on a federated node. C(manageprofiles) never creates
    one, because the managed template produces a node agent and nothing
    else, so this is
    what turns a federated node into a node that runs an application.
  - Takes the whole member list of a cluster in one call, because a C(wsadmin)
    JVM start costs 30 to 60 seconds. Eight members built one call at a time
    is eight starts.
notes:
  - Vertical and horizontal are not two modes. Several members on one node is
    vertical, one member on each of several nodes is horizontal, and both at
    once is the usual shape. The caller declares the list it wants; the shape
    is a consequence of the list, never a switch.
  - C(-firstMember) is handled by the module. The WAS API requires it exactly
    once per cluster, on the call that fixes the server template every later
    member is copied from, and the handler knows from what it read whether the
    cluster is still empty.
  - Runs against the deployment manager, which is where the master
    configuration repository lives. The nodes receive the members on the
    following node synchronisation, which is why I(sync_nodes) defaults to
    true.
  - The Jython driver must already be staged on the target. The
    C(wasevo.websphere.traditional.server_member) role does that itself rather
    than trusting an earlier job to have done it.
  - Members the cell holds and the call does not name are left alone. Removal
    is C(state=absent) on an explicit list, never a side effect of not
    naming something - a run limited to one node must not delete the members
    of every other node.
options:
  cluster_name:
    description: Cluster the members belong to. It must already exist.
    type: str
    required: true
  cell_name:
    description: Cell the cluster belongs to.
    type: str
    required: true
  members:
    description:
      - The members this call is about, one entry per application server JVM.
      - For C(state=present) the cell is made to match. For C(state=absent)
        exactly these are removed.
    type: list
    elements: dict
    required: true
    suboptions:
      name:
        description: Server name. Unique within the node.
        type: str
        required: true
      node:
        description: WAS node the server runs on - the node name, not the host.
        type: str
        required: true
      weight:
        description:
          - Routing weight. WAS defaults to 2; a member with weight 0 receives
            no new requests, which is how one is drained without deleting it.
        type: int
        default: 2
      gen_unique_ports:
        description:
          - Let WAS allocate free ports for this member instead of copying the
            template's.
          - Leave it true for a vertical cluster. Two JVMs on one node
            otherwise claim the same C(WC_defaulthost), SOAP and ORB ports,
            and the clash only surfaces when the second one is started.
        type: bool
        default: true
      ports:
        description:
          - Endpoints to pin after creation, keyed as C(serverindex.xml) names
            them - C(WC_defaulthost), C(BOOTSTRAP_ADDRESS), C(SOAP_CONNECTOR_ADDRESS).
          - Applied with C(modifyServerPort), because C(createClusterMember)
            has no argument for them. Only the endpoints named here are read
            back and compared, so a member that pins nothing costs no extra
            reads.
        type: dict
  template_name:
    description:
      - Server template the first member of the cluster is created from.
      - Used only on the call that creates the first member. Every later member
        is copied from that one, which is a WAS rule, not a choice this module
        makes.
    type: str
    default: default
  template_server_node:
    description:
      - Node of an existing server to use as the template instead of a named
        template. Requires I(template_server_name).
    type: str
  template_server_name:
    description: Existing server to use as the template. Requires I(template_server_node).
    type: str
  node_group:
    description: Node group for the first member. WAS defaults to C(DefaultNodeGroup).
    type: str
  core_group:
    description: Core group for the first member. WAS defaults to C(DefaultCoreGroup).
    type: str
  state:
    description:
      - C(present) creates the members that are missing and adjusts weight and
        pinned ports on the ones that exist.
      - C(absent) deletes exactly the members named, which deletes the
        application servers. Implemented deliberately, because
        decommissioning in wave 6 depends on it and the legacy repository
        left it out.
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
    description:
      - Synchronise the nodes after a change.
      - A member exists in the master repository as soon as it is saved, and on
        the node only after a sync. Without it the node agent is asked to start
        a server it has never heard of.
    type: bool
    default: true
author:
  - neo
"""

EXAMPLES = r"""
- name: Two members on one node - a vertical cluster
  wasevo.websphere.was_cluster_member:
    cluster_name: ClusterEXT01
    cell_name: Extranet_PREPROD_Cell
    members:
      - { node: PREPRODNode01, name: ClusterEXT01_PREPRODNode01_01 }
      - { node: PREPRODNode01, name: ClusterEXT01_PREPRODNode01_02 }
    profile_path: /app/profiles/Dmgr01
    admin_user: "{{ was_admin_user }}"
    admin_password: "{{ was_admin_password }}"

- name: One member on each of two nodes - a horizontal cluster
  wasevo.websphere.was_cluster_member:
    cluster_name: ClusterEXT01
    cell_name: Extranet_PREPROD_Cell
    members:
      - { node: PREPRODNode01, name: ClusterEXT01_PREPRODNode01_01 }
      - { node: PREPRODNode02, name: ClusterEXT01_PREPRODNode02_01 }
    profile_path: /app/profiles/Dmgr01
    admin_user: "{{ was_admin_user }}"
    admin_password: "{{ was_admin_password }}"

- name: Pin the HTTP port the IHS plugin is configured for
  wasevo.websphere.was_cluster_member:
    cluster_name: ClusterEXT01
    cell_name: Extranet_PREPROD_Cell
    members:
      - node: PREPRODNode01
        name: ClusterEXT01_PREPRODNode01_02
        weight: 2
        ports:
          WC_defaulthost: 9082
    profile_path: /app/profiles/Dmgr01
    admin_user: "{{ was_admin_user }}"
    admin_password: "{{ was_admin_password }}"

- name: Show what would change without touching the cell
  wasevo.websphere.was_cluster_member:
    cluster_name: ClusterEXT01
    cell_name: Extranet_PREPROD_Cell
    members: "{{ was_cluster_member_spec }}"
    profile_path: /app/profiles/Dmgr01
    admin_user: "{{ was_admin_user }}"
    admin_password: "{{ was_admin_password }}"
  check_mode: true
  diff: true

- name: Drain a member before removing it
  wasevo.websphere.was_cluster_member:
    cluster_name: ClusterEXT01
    cell_name: Extranet_PREPROD_Cell
    members:
      - { node: PREPRODNode02, name: ClusterEXT01_PREPRODNode02_01, weight: 0 }
    profile_path: /app/profiles/Dmgr01
    admin_user: "{{ was_admin_user }}"
    admin_password: "{{ was_admin_password }}"

- name: Remove it - this deletes the application server
  wasevo.websphere.was_cluster_member:
    cluster_name: ClusterEXT01
    cell_name: Extranet_PREPROD_Cell
    state: absent
    members:
      - { node: PREPRODNode02, name: ClusterEXT01_PREPRODNode02_01 }
    profile_path: /app/profiles/Dmgr01
    admin_user: "{{ was_admin_user }}"
    admin_password: "{{ was_admin_password }}"
"""

RETURN = r"""
cluster:
  description: The cluster and its members after the task, as read back from the cell.
  returned: always
  type: dict
  sample:
    exists: true
    cluster: ClusterEXT01
    members:
      - name: ClusterEXT01_PREPRODNode01_01
        node: PREPRODNode01
        weight: 2
      - name: ClusterEXT01_PREPRODNode01_02
        node: PREPRODNode01
        weight: 2
members:
  description: Just the member list, for a task that only needs that.
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
        cluster_name=dict(type="str", required=True),
        cell_name=dict(type="str", required=True),
        members=dict(
            type="list",
            elements="dict",
            required=True,
            options=dict(
                name=dict(type="str", required=True),
                node=dict(type="str", required=True),
                weight=dict(type="int", default=2),
                gen_unique_ports=dict(type="bool", default=True),
                ports=dict(type="dict"),
            ),
        ),
        template_name=dict(type="str", default="default"),
        template_server_node=dict(type="str"),
        template_server_name=dict(type="str"),
        node_group=dict(type="str"),
        core_group=dict(type="str"),
        state=dict(type="str", default="present", choices=["present", "absent"]),
    )

    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
        required_together=[["template_server_node", "template_server_name"]],
    )

    members = module.params["members"]
    if not members:
        module.fail_json(
            msg="members is empty. A call that names no member has nothing to "
                "do; the role skips the task instead of sending it."
        )

    # Two members with the same name on the same node is a cell that WAS
    # accepts at creation and that every later lookup by name reads wrong.
    # Caught here rather than in Jython: the operator is holding the list.
    seen = {}
    for member in members:
        key = (member["node"], member["name"])
        if key in seen:
            module.fail_json(
                msg="member %s is declared twice on node %s" % (
                    member["name"], member["node"],
                )
            )
        seen[key] = True
        if not member["name"].strip() or " " in member["name"]:
            module.fail_json(
                msg="%r is not a usable server name: a WAS server name cannot "
                    "be empty or contain whitespace" % member["name"]
            )

    resource_params = dict(
        cluster_name=module.params["cluster_name"],
        cell_name=module.params["cell_name"],
        members=members,
        template_name=module.params["template_name"],
        template_server_node=module.params["template_server_node"],
        template_server_name=module.params["template_server_name"],
        node_group=module.params["node_group"],
        core_group=module.params["core_group"],
    )

    runner = WsadminRunner(module)
    try:
        answer = runner.run("cluster_member", module.params["state"], resource_params)
    except WsadminFailure as exc:
        module.fail_json(msg=str(exc))

    after = answer.get("after") or {}
    module.exit_json(
        changed=answer["changed"],
        cluster=after,
        members=after.get("members") or [],
        diff=dict(
            before=answer.get("before") or {},
            after=after,
        ),
    )


if __name__ == "__main__":
    main()
