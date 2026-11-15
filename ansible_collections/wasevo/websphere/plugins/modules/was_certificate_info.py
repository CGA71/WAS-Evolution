#!/usr/bin/python
# -*- coding: utf-8 -*-
# Copyright (c) 2026, CGA
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r"""
---
module: was_certificate_info
short_description: List every certificate a WAS cell holds, with its expiry and how to renew it
version_added: "0.6.0"
description:
  - Reads every key store of the cell - the profile's own and those created
    for applications - and every personal and signer certificate in it, in
    one C(wsadmin) session. Changes nothing.
  - Each certificate comes back with its expiry, the days left, a status, the
    SSL configurations that present it, and the one way it can be renewed -
    C(renew), C(request), C(refresh_signer) or C(manual). See
    M(wasevo.websphere.was_certificate).
  - Key sets (LTPA) and the deleted store are skipped; they hold nothing to
    renew.
notes:
  - A validity WAS printed in a shape the module cannot read is reported with
    status C(unknown), never C(ok).
options:
  renew_within_days:
    description: Certificates expiring within this many days are C(warning); within 30, C(critical).
    type: int
    default: 90
  profile_path:
    description: Path to the deployment manager profile.
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
    description: Unused - this module never changes the cell.
    type: bool
    default: true
  sync_nodes:
    description: Unused - this module never changes the cell.
    type: bool
    default: true
author:
  - neo
"""

EXAMPLES = r"""
- name: What expires in the next three months
  wasevo.websphere.was_certificate_info:
    renew_within_days: 90
    profile_path: /app/profiles/Dmgr01
    admin_user: "{{ was_admin_user }}"
    admin_password: "{{ was_admin_password }}"
  register: certs
"""

RETURN = r"""
cell:
  description: The cell read.
  returned: always
  type: str
certificates:
  description: Every certificate, soonest expiry first.
  returned: always
  type: list
  elements: dict
  sample:
    - id: "personal|(cell):MyCell|ExtranetKeyStore|extranet-web"
      kind: personal
      domain: application
      scope: "(cell):MyCell"
      keystore: ExtranetKeyStore
      alias: extranet-web
      subject: "CN=extranet.example.com, O=Example"
      issuer: "CN=Corp Issuing CA, O=Example"
      not_after: "2027-01-31"
      days_left: 45
      status: warning
      method: request
      used_by: [ExtranetSSLSettings]
summary:
  description: How many certificates are in each status.
  returned: always
  type: dict
unreadable:
  description: Key stores a listing verb refused, with the reason.
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
    argument_spec.update(renew_within_days=dict(type="int", default=90))
    module = AnsibleModule(argument_spec=argument_spec, supports_check_mode=True)

    runner = WsadminRunner(module)
    try:
        answer = runner.run("certificates", "present", dict(
            action="inventory", renew_within_days=module.params["renew_within_days"]))
    except WsadminFailure as exc:
        module.fail_json(msg=str(exc))

    found = answer.get("before") or {}
    module.exit_json(
        changed=False,
        cell=found.get("cell", ""),
        today=found.get("today", ""),
        renew_within_days=found.get("renew_within_days", module.params["renew_within_days"]),
        certificates=found.get("certificates", []),
        summary=found.get("summary", {}),
        unreadable=found.get("unreadable", []),
    )


if __name__ == "__main__":
    main()
