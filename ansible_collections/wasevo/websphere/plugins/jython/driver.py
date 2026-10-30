# -*- coding: utf-8 -*-
"""Single wsadmin entry point for every traditional-plane module.

Invoked as::

    wsadmin.sh -lang jython -wsadmin_properties <0600 props> -f driver.py <payload.json>

It reads one payload, dispatches to one handler, and writes one JSON answer
between sentinels so the calling module can find it inside wsadmin's banners.

Jython notes, because this file does not run under CPython:

* wsadmin ships Jython 2.1 on older fixpacks and 2.7 on current ones. The
  ``json`` module only exists on 2.7, so a minimal encoder is bundled for 2.1.
* ``AdminConfig`` and friends are injected into the *main* script's globals.
  Imported handler modules do not see them, so they are passed explicitly.
* ``sys.argv[0]`` is the first script argument, not the script name.
"""

import sys
import os
import traceback

SENTINEL_OPEN = "<<<VSSP-JSON>>>"
SENTINEL_CLOSE = "<<<END-VSSP-JSON>>>"

# --------------------------------------------------------------------------
# JSON, with a fallback for Jython 2.1
# --------------------------------------------------------------------------

try:
    import json as _json

    def dumps(obj):
        return _json.dumps(obj)

    def loads(text):
        return _json.loads(text)

except ImportError:  # Jython 2.1

    def _esc(text):
        out = []
        for ch in text:
            if ch == '"':
                out.append('\\"')
            elif ch == "\\":
                out.append("\\\\")
            elif ch == "\n":
                out.append("\\n")
            elif ch == "\r":
                out.append("\\r")
            elif ch == "\t":
                out.append("\\t")
            elif ord(ch) < 0x20:
                out.append("\\u%04x" % ord(ch))
            else:
                out.append(ch)
        return "".join(out)

    def dumps(obj):
        if obj is None:
            return "null"
        if obj is True:
            return "true"
        if obj is False:
            return "false"
        if isinstance(obj, (int, long, float)):
            return str(obj)
        if isinstance(obj, (list, tuple)):
            return "[" + ",".join([dumps(i) for i in obj]) + "]"
        if isinstance(obj, dict):
            parts = []
            for key in obj.keys():
                parts.append('"%s":%s' % (_esc(str(key)), dumps(obj[key])))
            return "{" + ",".join(parts) + "}"
        return '"%s"' % _esc(str(obj))

    def loads(text):
        # The payload is written by our own module, 0600, on this host. A full
        # parser would be dead weight here; evaluating the JSON subset we emit
        # is sufficient and is never fed foreign input.
        safe = text.replace("null", "None").replace("true", "True").replace("false", "False")
        return eval(safe, {"__builtins__": {}}, {})


def emit(answer):
    sys.stdout.write("\n%s\n%s\n%s\n" % (SENTINEL_OPEN, dumps(answer), SENTINEL_CLOSE))


# --------------------------------------------------------------------------
# Dispatch
# --------------------------------------------------------------------------

def load_handler(name):
    """Import handlers/<name>.py from beside this driver."""
    here = os.path.dirname(os.path.abspath(__file__))
    handlers = os.path.join(here, "handlers")
    if handlers not in sys.path:
        sys.path.insert(0, handlers)
    if here not in sys.path:
        sys.path.insert(0, here)
    return __import__(name)


def main():
    if len(sys.argv) < 1:
        emit({"failed": True, "msg": "driver.py expects a payload path"})
        return 1

    payload_path = sys.argv[0].replace('"', "")
    handle = open(payload_path, "r")
    try:
        payload = loads(handle.read())
    finally:
        handle.close()

    resource = payload["resource"]
    state = payload["state"]
    params = payload["params"]
    check_mode = payload.get("check_mode", False)

    # The admin objects live in this script's globals. Hand them over
    # explicitly so handlers stay importable and unit-testable.
    admin = {
        "AdminConfig": AdminConfig,
        "AdminControl": AdminControl,
        "AdminApp": AdminApp,
        "AdminTask": AdminTask,
    }

    handler = load_handler(resource)

    if state not in ("present", "absent"):
        emit({"failed": True, "msg": "unknown state: %s" % state})
        return 1

    # A handler raises ValueError to REFUSE a request it understood perfectly
    # well - a cluster member asked for in a cell that has no such cluster.
    # That is an answer, not a crash, so it is reported as the message alone;
    # the module prints it and the operator reads a sentence. Anything else is
    # a defect and keeps its traceback, which is what the outer handler does.
    try:
        before = handler.read(admin, params)
        after = before
        changed = False

        if state == "present":
            changed, after = handler.plan_present(admin, params, before)
        else:
            changed, after = handler.plan_absent(admin, params, before)

        if changed and not check_mode:
            if state == "present":
                handler.write_present(admin, params, before)
            else:
                handler.write_absent(admin, params, before)

            if payload.get("save_config", True):
                AdminConfig.save()
            if payload.get("sync_nodes", True) and hasattr(handler, "sync"):
                handler.sync(admin, params)
            # Re-read so `after` describes reality rather than our intent.
            after = handler.read(admin, params)
    except ValueError as exc:
        emit({"failed": True, "msg": "%s refused: %s" % (resource, exc)})
        return 1

    emit({
        "changed": changed,
        "before": before,
        "after": after,
        "check_mode": check_mode,
    })
    return 0


try:
    main()
except Exception:
    emit({"failed": True, "msg": "driver exception: %s" % traceback.format_exc()})
