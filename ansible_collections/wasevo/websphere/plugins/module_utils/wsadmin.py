# -*- coding: utf-8 -*-
# Copyright (c) 2026, neo
# GNU General Public License v3.0+
"""Shared plumbing for every module that reaches a WAS cell through wsadmin.

Design constraints this file exists to absorb:

* wsadmin runs Jython inside WAS's own JVM. An Ansible module runs under the
  target's Python 3. The two cannot share a process, so the module writes a
  payload, launches wsadmin **once**, and reads a JSON document back.
* A wsadmin JVM start costs 30-60 seconds. Everything a call needs is therefore
  batched into a single payload: read, compare and write happen inside one
  session, which is also what makes `changed` and `--diff` truthful.
* No secret ever reaches a command line. The SOAP login lands in a 0600
  properties file passed with `-wsadmin_properties`, because anything on the
  command line is visible in `ps` and in the Ansible log.
"""

from __future__ import absolute_import, division, print_function

__metaclass__ = type

import json
import os
import tempfile

DEFAULT_JYTHON_DIR = "/opt/exploit/scripts/jython-ansible"
DRIVER_NAME = "driver.py"

#: Arguments every traditional-plane module accepts. Modules extend this.
WSADMIN_COMMON_ARGS = dict(
    profile_path=dict(type="path", required=True),
    admin_user=dict(type="str", required=True),
    admin_password=dict(type="str", required=True, no_log=True),
    conntype=dict(type="str", default="SOAP", choices=["SOAP", "RMI", "JSR160RMI", "IPC", "NONE"]),
    host=dict(type="str"),
    port=dict(type="int"),
    jython_dir=dict(type="path", default=DEFAULT_JYTHON_DIR),
    save_config=dict(type="bool", default=True),
    sync_nodes=dict(type="bool", default=True),
)


class WsadminFailure(Exception):
    """Raised when wsadmin could not be run, or did not answer usefully."""


class WsadminRunner(object):
    """One wsadmin invocation, one JSON answer."""

    def __init__(self, module):
        self.module = module
        p = module.params
        self.profile_path = p["profile_path"]
        self.jython_dir = p["jython_dir"]
        self.driver = os.path.join(self.jython_dir, DRIVER_NAME)
        self.wsadmin = os.path.join(self.profile_path, "bin", "wsadmin.sh")

    # -- preflight ---------------------------------------------------------

    def preflight(self):
        """Fail early and clearly rather than on a cryptic shell error.

        The Jython tree is staged by ``wasevo.websphere.traditional.config``;
        a module invoked without that role having run is a setup mistake, and
        saying so is more useful than a wsadmin stack trace.
        """
        if not os.path.isfile(self.wsadmin):
            raise WsadminFailure(
                "wsadmin not found at %s - check profile_path" % self.wsadmin
            )
        if not os.path.isfile(self.driver):
            raise WsadminFailure(
                "Jython driver not found at %s - run the "
                "wasevo.websphere.traditional.config role first, it stages "
                "plugins/jython/ onto the target" % self.driver
            )

    # -- secret handling ---------------------------------------------------

    def _write_properties(self):
        """A 0600 properties file carrying the SOAP login.

        Returns the path. The caller is responsible for removing it, which
        ``run()`` does in a finally block.
        """
        p = self.module.params
        lines = [
            "com.ibm.ws.scripting.connectionType=%s" % p["conntype"],
        ]
        if p.get("host"):
            lines.append("com.ibm.ws.scripting.host=%s" % p["host"])
        if p.get("port"):
            lines.append("com.ibm.ws.scripting.port=%s" % p["port"])
        lines.append("com.ibm.SOAP.securityEnabled=true")
        lines.append("com.ibm.SOAP.loginUserid=%s" % p["admin_user"])
        lines.append("com.ibm.SOAP.loginPassword=%s" % p["admin_password"])

        fd, path = tempfile.mkstemp(prefix=".wsadmin-", suffix=".props", dir=self.jython_dir)
        try:
            os.fchmod(fd, 0o600)
            os.write(fd, ("\n".join(lines) + "\n").encode("utf-8"))
        finally:
            os.close(fd)
        return path

    def _write_payload(self, payload):
        fd, path = tempfile.mkstemp(prefix=".wsadmin-", suffix=".json", dir=self.jython_dir)
        try:
            os.fchmod(fd, 0o600)
            os.write(fd, json.dumps(payload).encode("utf-8"))
        finally:
            os.close(fd)
        return path

    # -- the call ----------------------------------------------------------

    def run(self, resource, state, params, extra=None):
        """Run one resource operation and return the driver's answer.

        :param resource: handler name, e.g. ``"cluster"``
        :param state: ``"present"`` or ``"absent"``
        :param params: dict of resource attributes, already validated
        :returns: dict with at least ``changed``; usually ``before``/``after``
        """
        self.preflight()

        payload = {
            "resource": resource,
            "state": state,
            "params": params,
            "check_mode": bool(self.module.check_mode),
            "save_config": bool(self.module.params["save_config"]),
            "sync_nodes": bool(self.module.params["sync_nodes"]),
        }
        if extra:
            payload.update(extra)

        props = None
        payload_path = None
        try:
            props = self._write_properties()
            payload_path = self._write_payload(payload)

            cmd = [
                self.wsadmin,
                "-lang", "jython",
                "-wsadmin_properties", props,
                "-f", self.driver,
                payload_path,
            ]
            # check_mode is honoured inside the driver, not here: the read half
            # must still run so that --diff has something to show.
            rc, stdout, stderr = self.module.run_command(cmd, check_rc=False)
            return self._parse(rc, stdout, stderr)
        finally:
            for path in (props, payload_path):
                if path:
                    try:
                        os.unlink(path)
                    except OSError:
                        pass

    @staticmethod
    def _parse(rc, stdout, stderr):
        """Pull the driver's JSON out of wsadmin's chatty stdout.

        wsadmin prints banners (WASX7209I and friends) around our output, so the
        driver wraps its answer in sentinels rather than us hoping stdout is
        clean JSON.
        """
        start = stdout.find("<<<VSSP-JSON>>>")
        end = stdout.find("<<<END-VSSP-JSON>>>")
        if start == -1 or end == -1 or end < start:
            raise WsadminFailure(
                "wsadmin returned no parsable answer (rc=%s). "
                "stdout: %s | stderr: %s" % (rc, stdout[-2000:], stderr[-2000:])
            )
        blob = stdout[start + len("<<<VSSP-JSON>>>"):end].strip()
        try:
            answer = json.loads(blob)
        except ValueError as exc:
            raise WsadminFailure("driver answer was not valid JSON: %s" % exc)

        if answer.get("failed"):
            raise WsadminFailure(answer.get("msg") or "wsadmin handler failed")
        return answer
