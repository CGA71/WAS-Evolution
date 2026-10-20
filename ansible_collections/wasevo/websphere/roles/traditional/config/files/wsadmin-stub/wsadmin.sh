#!/bin/sh
# wsadmin stand-in for the CI simulation.
#
# WAS ND cannot be shipped in a CI image - licensing, entitlement and several
# gigabytes. But almost everything that can go wrong in the traditional plane
# is NOT WAS behaviour, it is the plumbing around it:
#
#   argument validation -> payload file -> JVM launch -> driver dispatch ->
#   handler read/plan/write -> JSON answer -> changed / diff / failed
#
# This script stands in for wsadmin.sh so that whole chain runs for real, with
# a fake cell behind it. It accepts the same arguments the module builds and it
# prints the same banner noise around the output, so the module JSON sentinel
# parsing is exercised rather than bypassed.
#
# What it does NOT prove: that the wsadmin calls in the handlers are correct
# WAS API usage. Only a real cell proves that.

set -e

DRIVER=""
PAYLOAD=""
PROPS=""
LANG_OPT=""

while [ $# -gt 0 ]; do
    case "$1" in
        -lang)                 LANG_OPT="$2"; shift 2 ;;
        -wsadmin_properties)   PROPS="$2";    shift 2 ;;
        -f)                    DRIVER="$2";   shift 2 ;;
        -user|-username|-password)
            # The real wsadmin accepts these. The module must never use them:
            # anything here is visible in ps and in the Ansible log. Refuse
            # loudly so a regression that reintroduces them fails the pipeline.
            echo "WASX_STUB_FATAL: credentials passed on the command line" >&2
            echo "The module must use -wsadmin_properties with a 0600 file." >&2
            exit 93
            ;;
        *)                     PAYLOAD="$1";  shift ;;
    esac
done

if [ "$LANG_OPT" != "jython" ]; then
    echo "WASX_STUB_FATAL: expected -lang jython, got '$LANG_OPT'" >&2
    exit 94
fi

if [ -z "$DRIVER" ] || [ ! -f "$DRIVER" ]; then
    echo "WASX_STUB_FATAL: driver not found: '$DRIVER'" >&2
    exit 95
fi

if [ -z "$PAYLOAD" ] || [ ! -f "$PAYLOAD" ]; then
    echo "WASX_STUB_FATAL: payload not found: '$PAYLOAD'" >&2
    exit 96
fi

# The properties file carries the SOAP login. Check it is there and that its
# mode is 0600, because that is the whole reason it exists.
if [ -n "$PROPS" ]; then
    if [ ! -f "$PROPS" ]; then
        echo "WASX_STUB_FATAL: properties file not found: '$PROPS'" >&2
        exit 97
    fi
    MODE=$(stat -c "%a" "$PROPS")
    if [ "$MODE" != "600" ]; then
        echo "WASX_STUB_FATAL: properties file mode is $MODE, expected 600" >&2
        exit 98
    fi
fi

# Banner noise, as the real wsadmin emits around script output.
echo "WASX7209I: Connected to process \"dmgr\" on node CellManager using SOAP connector"
echo "WASX7031I: For help, enter: \"print Help.help()\""

STUB_DIR=$(dirname "$0")
PYTHONPATH="$STUB_DIR:${PYTHONPATH}" \
  python3 "$STUB_DIR/shim.py" "$DRIVER" "$PAYLOAD"
RC=$?

echo "WASX7341I: Stub run complete."
exit $RC
