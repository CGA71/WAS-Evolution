#!/usr/bin/python
# -*- coding: utf-8 -*-
# Copyright (c) 2026, CGA
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r"""
---
module: was_application
short_description: Install, reinstall or uninstall an application in a WAS ND cell
version_added: "0.4.0"
description:
  - Installs an EAR, a WAR or an EJB JAR on a cluster or on one application
    server, binds it to shared libraries, and starts it on every running
    member once the nodes have synchronised - through C(wsadmin), in one session.
  - An installed application is B(uninstalled then installed again) when
    I(reinstall) is true, or when it is mapped to another target than the one
    declared. A difference in shared libraries alone is an edit.
  - C(state=absent) stops the application where it runs and uninstalls it. The
    resources it used are not touched here; the C(traditional.application) role
    removes the ones the application declared.
notes:
  - The archive is read by C(wsadmin) on the deployment manager host, so
    I(archive) is a path on that host.
  - Whether the archive changed is the caller's decision. The role compares
    the checksum of the archive with the copy the cell stores in its
    configuration repository and passes I(reinstall).
options:
  name:
    description: The application name (C(-appname)).
    type: str
    required: true
  archive:
    description: Path of the EAR, WAR or JAR on the deployment manager host. Required when I(state=present).
    type: path
  target:
    description: Where the application runs. Required when I(state=present).
    type: dict
    suboptions:
      type:
        description: A cluster, or one server.
        type: str
        required: true
        choices: [cluster, server]
      cluster:
        description: Cluster name.
        type: str
      node:
        description: Node name, for a server target.
        type: str
      server:
        description: Server name, for a server target.
        type: str
  context_root:
    description: Context root of a standalone WAR (C(-contextroot)).
    type: str
  virtual_host:
    description: Virtual host the web modules are mapped to.
    type: str
    default: default_host
  map_web_modules:
    description: Map the web modules to I(virtual_host). False for an archive that has none, an EJB JAR.
    type: bool
    default: true
  shared_libraries:
    description: Shared libraries bound to every module (C(-MapSharedLibForMod)). They must exist.
    type: list
    elements: str
    default: []
  install_options:
    description: Further C(AdminApp.install) options, as tokens, appended as given.
    type: list
    elements: str
    default: []
  reinstall:
    description: The archive changed - uninstall and install again.
    type: bool
    default: false
  start:
    description: Start the application on the running members after the install.
    type: bool
    default: true
  ready_timeout:
    description: Seconds to wait for the nodes to expand the application before starting it.
    type: int
    default: 300
  state:
    description: C(present) installs, or reinstalls; C(absent) uninstalls.
    type: str
    choices: [present, absent]
    default: present
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
    description: Save the configuration after a change.
    type: bool
    default: true
  sync_nodes:
    description: Synchronise the nodes after a change, and start the application.
    type: bool
    default: true
author:
  - neo
"""

EXAMPLES = r"""
- name: The orders application, on the cluster
  wasevo.websphere.was_application:
    name: OrdersApp
    archive: /mnt/binaries/applications/orders/OrdersApp-1.4.2.ear
    target: {type: cluster, cluster: ClusterEXT01}
    shared_libraries: [ordersCommonLibrary]
    profile_path: /app/profiles/Dmgr01
    admin_user: "{{ was_admin_user }}"
    admin_password: "{{ was_admin_password }}"

- name: Decommissioned
  wasevo.websphere.was_application:
    name: OrdersApp
    state: absent
    profile_path: /app/profiles/Dmgr01
    admin_user: "{{ was_admin_user }}"
    admin_password: "{{ was_admin_password }}"
"""

RETURN = r"""
application:
  description: The application as the cell holds it afterwards - empty once uninstalled.
  returned: always
  type: dict
action:
  description: What was done, or would be - install, reinstall and why, shared libraries rebound, uninstall, none.
  returned: always
  type: str
"""

import os

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
        archive=dict(type="path"),
        target=dict(type="dict", options=dict(
            type=dict(type="str", required=True, choices=["cluster", "server"]),
            cluster=dict(type="str"),
            node=dict(type="str"),
            server=dict(type="str"),
        )),
        context_root=dict(type="str"),
        virtual_host=dict(type="str", default="default_host"),
        map_web_modules=dict(type="bool", default=True),
        shared_libraries=dict(type="list", elements="str", default=[]),
        install_options=dict(type="list", elements="str", default=[]),
        reinstall=dict(type="bool", default=False),
        start=dict(type="bool", default=True),
        ready_timeout=dict(type="int", default=300),
        state=dict(type="str", default="present", choices=["present", "absent"]),
    )

    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
        required_if=[("state", "present", ("archive", "target"))],
    )
    p = module.params

    if p["state"] == "present":
        target = p["target"]
        if target["type"] == "cluster" and not target.get("cluster"):
            module.fail_json(msg="a cluster target needs target.cluster")
        if target["type"] == "server" and not (target.get("node") and target.get("server")):
            module.fail_json(msg="a server target needs target.node and target.server")
        if not os.path.isfile(p["archive"]):
            module.fail_json(
                msg="%s is not a file on %s. wsadmin reads the archive on the deployment "
                    "manager host: is the application share mounted there?" % (p["archive"], os.uname()[1])
            )
        lowered = p["archive"].lower()
        if not (lowered.endswith(".ear") or lowered.endswith(".war") or lowered.endswith(".jar")):
            module.fail_json(msg="%s is not an .ear, a .war or a .jar" % p["archive"])
        if p["context_root"] and not lowered.endswith(".war"):
            module.fail_json(msg="context_root applies to a standalone WAR; an EAR declares "
                                 "its context roots in application.xml")

    params = dict(
        name=p["name"],
        archive=p["archive"],
        target=p["target"],
        context_root=p["context_root"],
        virtual_host=p["virtual_host"],
        map_web_modules=p["map_web_modules"],
        shared_libraries=p["shared_libraries"],
        install_options=p["install_options"],
        reinstall=p["reinstall"],
        start=p["start"],
        ready_timeout=p["ready_timeout"],
    )

    runner = WsadminRunner(module)
    try:
        answer = runner.run("application", p["state"], params)
    except WsadminFailure as exc:
        module.fail_json(msg=str(exc))

    before = answer.get("before") or {}
    after = answer.get("after") or {}
    module.exit_json(
        changed=answer["changed"],
        application=after if after.get("installed") else {},
        action=after.get("action") or ("none" if answer["changed"] is False else ""),
        diff=dict(before=before, after=after),
    )


if __name__ == "__main__":
    main()
