#!/usr/bin/python
# -*- coding: utf-8 -*-
# Copyright (c) 2026, neo
# GNU General Public License v3.0+

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r"""
---
module: was_shared_library
short_description: Manage shared libraries in a WAS ND cell
version_added: "0.3.0"
description:
  - Creates, updates or removes shared libraries - jars several applications
    load from one place - at one scope, through C(wsadmin).
  - Takes every library of a scope in one call, so one C(wsadmin) session
    serves them all.
notes:
  - The class path is an explicit, ordered list. WAS traditional has no
    wildcard in a library class path, so the role expands the shared model's
    C(dir) and C(includes) on the deployment manager and hands over the exact
    jars; a jar added to the directory then shows up as a difference.
  - The class path is a list attribute, and C(AdminConfig.modify) appends to a
    list. A changed class path is unset and rewritten.
  - Associating a library with an application or a server class loader is not
    done here. It belongs to the application deployment.
options:
  scope:
    description: Where the libraries live. The roles default to the cluster.
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
  libraries:
    description: The libraries this call is about.
    type: list
    elements: dict
    required: true
    suboptions:
      name:
        description: Library name, unique within the scope.
        type: str
        required: true
      class_path:
        description: Jars, in order.
        type: list
        elements: str
        required: true
      native_path:
        description: Native libraries, in order.
        type: list
        elements: str
        default: []
      description:
        description: Free text shown in the administrative console.
        type: str
        default: ""
      isolated:
        description: Give the library its own class loader, shared by the applications that use it.
        type: bool
        default: false
  state:
    description:
      - C(present) creates the libraries that are missing and updates the ones
        that differ.
      - C(absent) removes exactly the libraries named.
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
- name: The library the extranet applications share
  wasevo.websphere.was_shared_library:
    scope:
      type: cluster
      cluster: ClusterEXT01
    libraries:
      - name: appCommonLibrary
        class_path:
          - /app/binaries/shared/commons-lang3.jar
          - /app/binaries/shared/commons-text.jar
    profile_path: /app/profiles/Dmgr01
    admin_user: "{{ was_admin_user }}"
    admin_password: "{{ was_admin_password }}"
"""

RETURN = r"""
libraries:
  description: The libraries named by the call, as the cell holds them afterwards.
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
        libraries=dict(
            type="list",
            elements="dict",
            required=True,
            options=dict(
                name=dict(type="str", required=True),
                class_path=dict(type="list", elements="str", required=True),
                native_path=dict(type="list", elements="str", default=[]),
                description=dict(type="str", default=""),
                isolated=dict(type="bool", default=False),
            ),
        ),
        state=dict(type="str", default="present", choices=["present", "absent"]),
    )

    module = AnsibleModule(argument_spec=argument_spec, supports_check_mode=True)

    libraries = module.params["libraries"]
    if not libraries:
        module.fail_json(msg="libraries is empty; the role skips the task instead of sending it")
    names = [lib["name"] for lib in libraries]
    duplicates = sorted(set(n for n in names if names.count(n) > 1))
    if duplicates:
        module.fail_json(msg="library declared twice in one scope: %s" % ", ".join(duplicates))
    if module.params["state"] == "present":
        empty = [lib["name"] for lib in libraries if not lib["class_path"]]
        if empty:
            module.fail_json(
                msg="library with an empty class path: %s. It would provide "
                    "nothing, and the applications using it would fail on their "
                    "first class load." % ", ".join(empty)
            )

    runner = WsadminRunner(module)
    try:
        answer = runner.run("shared_library", module.params["state"], dict(
            scope=module.params["scope"],
            libraries=libraries,
        ))
    except WsadminFailure as exc:
        module.fail_json(msg=str(exc))

    after = answer.get("after") or {}
    module.exit_json(
        changed=answer["changed"],
        libraries=after.get("libraries") or [],
        diff=dict(before=answer.get("before") or {}, after=after),
    )


if __name__ == "__main__":
    main()
