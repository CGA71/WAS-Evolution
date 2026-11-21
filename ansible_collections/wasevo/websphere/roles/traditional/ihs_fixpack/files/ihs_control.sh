#!/bin/sh
# Stop or start IBM HTTP Server instances - every instance at once. An IHS
# profile is an Apache instance: its own directory, its own bin/apachectl, its
# own httpd.pid.
#
#   ihs_control.sh status <instance dir> ...    dir|running|pid  or  dir|stopped|
#   ihs_control.sh stop   <instance dir> ...
#       apachectl -k stop; an instance still alive after $IHS_STOP_TIMEOUT
#       seconds is killed - its children first, then the parent: SIGTERM,
#       then SIGKILL after $IHS_KILL_GRACE seconds.
#   ihs_control.sh start  <instance dir> ...
#       apachectl -k start, then waits $IHS_START_TIMEOUT seconds at most for
#       a live pid.
#
# One line per instance:  dir|stopped|killed|started|already-...|FAILED|...
# IHS_PID_FILE is the pid file relative to the instance (logs/httpd.pid).
# POSIX sh only: /bin/sh is ksh on AIX.

PIDREL="${IHS_PID_FILE:-logs/httpd.pid}"

pid_of() {
    f="$1/$PIDREL"
    if [ -f "$f" ]; then
        p=$(cat "$f" 2>/dev/null)
        if [ -n "$p" ] && kill -0 "$p" 2>/dev/null; then echo "$p"; fi
    fi
}

# The children of a process: Apache's workers. ps -e -o pid,ppid works on AIX
# and Linux alike.
children_of() {
    ps -e -o pid= -o ppid= 2>/dev/null | awk -v p="$1" '$2 == p { print $1 }'
}

stop_one() {
    d="$1"
    pid=$(pid_of "$d")
    if [ -z "$pid" ]; then echo "$d|already-stopped|"; return; fi
    "$d/bin/apachectl" -k stop > /dev/null 2>&1
    t=0
    while kill -0 "$pid" 2>/dev/null && [ "$t" -lt "${IHS_STOP_TIMEOUT:-60}" ]; do
        sleep 2; t=$((t + 2))
    done
    if ! kill -0 "$pid" 2>/dev/null; then echo "$d|stopped|$pid|${t}s"; return; fi
    kids=$(children_of "$pid")
    kill -15 $kids "$pid" 2>/dev/null
    g=0
    while kill -0 "$pid" 2>/dev/null && [ "$g" -lt "${IHS_KILL_GRACE:-15}" ]; do
        sleep 1; g=$((g + 1))
    done
    kill -9 $kids "$pid" 2>/dev/null
    sleep 1
    if kill -0 "$pid" 2>/dev/null; then
        echo "$d|STILL-RUNNING|$pid|stop and kill both failed"
    else
        echo "$d|killed|$pid|stop exceeded ${IHS_STOP_TIMEOUT:-60}s"
    fi
}

start_one() {
    d="$1"
    pid=$(pid_of "$d")
    if [ -n "$pid" ]; then echo "$d|already-running|$pid"; return; fi
    out=$("$d/bin/apachectl" -k start 2>&1)
    rc=$?
    t=0
    while [ -z "$(pid_of "$d")" ] && [ "$t" -lt "${IHS_START_TIMEOUT:-60}" ]; do
        sleep 2; t=$((t + 2))
    done
    pid=$(pid_of "$d")
    if [ -n "$pid" ]; then
        echo "$d|started|$pid"
    else
        echo "$d|FAILED|rc=$rc|$(printf '%s' "$out" | tail -3 | tr '\n' ' ')"
    fi
}

status_one() {
    pid=$(pid_of "$1")
    if [ -n "$pid" ]; then echo "$1|running|$pid"; else echo "$1|stopped|"; fi
}

mode="$1"; shift
WORK="${TMPDIR:-/tmp}/ihs_control.$$"
mkdir -p "$WORK" && chmod 700 "$WORK"
trap 'rm -rf "$WORK"' 0
case "$mode" in
    status|stop|start)
        n=0
        for d in "$@"; do
            n=$((n + 1))
            ( "${mode}_one" "$d" > "$WORK/result.$n" ) &
        done
        wait
        cat "$WORK"/result.* 2>/dev/null
        ;;
    *) echo "usage: $0 status|stop|start <instance dir>..." >&2; exit 2 ;;
esac
