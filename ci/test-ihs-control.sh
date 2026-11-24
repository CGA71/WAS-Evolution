#!/bin/sh
# The IHS control script, against fake Apache instances - no IHS, no server.
#
# Two instances: one that stops on apachectl -k stop, one that ignores both
# the stop and SIGTERM and must be killed. Checks: start, status, the stop,
# the kill.
#
#   sh ci/test-ihs-control.sh
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
H="$HERE/../ansible_collections/wasevo/websphere/roles/traditional/ihs_fixpack/files/ihs_control.sh"
T=$(mktemp -d)
# `|| true`: under set -e a kill of a process already gone - the normal case
# once the test has stopped everything - would end the script with status 1
# after every check had passed, and before the rm.
cleanup() {
    for f in "$T"/*/logs/httpd.pid; do [ -f "$f" ] && kill -9 "$(cat "$f")" 2>/dev/null || true; done
    rm -rf "$T"
}
trap cleanup 0
fail() { echo "FAIL: $*"; exit 1; }

for i in SITEA HANG; do mkdir -p "$T/$i/bin" "$T/$i/logs"; done
cat > "$T/SITEA/bin/apachectl" <<'SH'
#!/bin/sh
d=$(cd "$(dirname "$0")/.." && pwd)
case "$2" in
    start) sh -c 'sleep 600 & sleep 600 & wait' > /dev/null 2>&1 & echo $! > "$d/logs/httpd.pid" ;;
    stop)  kill "$(cat "$d/logs/httpd.pid")" ;;
esac
SH
cat > "$T/HANG/bin/apachectl" <<'SH'
#!/bin/sh
d=$(cd "$(dirname "$0")/.." && pwd)
case "$2" in
    start) sh -c 'trap "" TERM; while :; do sleep 1; done' > /dev/null 2>&1 & echo $! > "$d/logs/httpd.pid" ;;
    stop)  : ;;
esac
SH
chmod +x "$T"/*/bin/apachectl
export IHS_STOP_TIMEOUT=4 IHS_KILL_GRACE=2 IHS_START_TIMEOUT=6

out=$(sh "$H" start "$T/SITEA" "$T/HANG"); echo "$out"
echo "$out" | grep -q 'SITEA|started|' || fail "SITEA did not start"
echo "$out" | grep -q 'HANG|started|'   || fail "HANG did not start"
out=$(sh "$H" status "$T/SITEA"); echo "$out" | grep -q 'SITEA|running|' || fail "status"
out=$(sh "$H" stop "$T/SITEA" "$T/HANG"); echo "$out"
echo "$out" | grep -q 'SITEA|stopped|' || fail "SITEA was not stopped by apachectl"
echo "$out" | grep -q 'HANG|killed|'    || fail "HANG was not killed after the timeout"
out=$(sh "$H" status "$T/SITEA" "$T/HANG"); echo "$out"
echo "$out" | grep -q 'running' && fail "an instance is still running"
echo "ihs_control.sh: start, status, stop and kill behave"
