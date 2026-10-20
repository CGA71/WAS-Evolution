# -*- coding: utf-8 -*-
"""Run the real Jython driver under CPython with a fake cell behind it.

wsadmin injects AdminConfig, AdminControl, AdminTask and AdminApp into the main
script's globals. driver.py relies on exactly that, which is why handlers
receive them in an explicit dict rather than importing them. Here the same
injection is done with the fakes, and the driver is executed unmodified.

Running the driver unmodified is the whole value: the dispatch, the payload
parsing, the JSON encoding and the sentinel framing are the production code
paths, not a reimplementation of them.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fake_admin  # noqa: E402  (after the path insert, deliberately)


def main():
    if len(sys.argv) != 3:
        sys.stderr.write("usage: shim.py <driver.py> <payload.json>\n")
        return 2

    driver_path, payload_path = sys.argv[1], sys.argv[2]

    with open(driver_path) as handle:
        source = handle.read()

    # driver.py reads its payload from sys.argv[0], because that is where
    # wsadmin puts the first script argument. Reproduce that convention.
    saved_argv = sys.argv
    sys.argv = [payload_path]

    globals_for_driver = {
        "__name__": "__main__",
        "__file__": driver_path,
        "__builtins__": __builtins__,
    }
    globals_for_driver.update(fake_admin.build())

    try:
        exec(compile(source, driver_path, "exec"), globals_for_driver)
    finally:
        sys.argv = saved_argv

    return 0


if __name__ == "__main__":
    sys.exit(main())
