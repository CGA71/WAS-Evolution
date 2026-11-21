#!/bin/sh
# Stop or start WAS processes: application server JVMs a batch at a time, in
# parallel - and the node agent, and the deployment manager.
# Run as the account the JVMs run as (was) - never root: a kill reaches only
# that account's processes, which is exactly the set this script may touch.
#
#   jvm_batch.sh discover
#       one line per process of every profile under $WAS_PROFILES_DIR:
#       profile|cell|node|server|xmx_mb|state|pid|type
#       type: APPLICATION_SERVER, NODE_AGENT, DEPLOYMENT_MANAGER (xmx 0)
#   jvm_batch.sh stop  <profile>:<server> ...
#       the stop command of each, all at once - stopServer.sh <server>,
#       stopNode.sh for nodeagent, stopManager.sh for dmgr, the names WAS
#       itself gives those two; a process still alive after
#       $JVM_STOP_TIMEOUT seconds gets SIGTERM, then SIGKILL after
#       $JVM_KILL_GRACE seconds.  One line each:  server|stopped|killed|...
#   jvm_batch.sh start <profile>:<server> ...
#       startServer.sh for each, all at once, waiting at most
#       $JVM_START_TIMEOUT seconds each.  One line each:  server|started|...
#
# Environment: WAS_PROFILES_DIR, WAS_LOG_ROOT (optional, a moved LOG_ROOT),
# JVM_XMX_UNSET_MB, JVM_STOP_TIMEOUT, JVM_KILL_GRACE, JVM_START_TIMEOUT,
# WAS_STOP_USER / WAS_STOP_PASSWORD (optional, for stopServer.sh when
# administrative security is on and soap.client.props holds no credentials).
#
# POSIX sh only: /bin/sh is ksh on AIX, bash is not in the base system.

WORK="${TMPDIR:-/tmp}/jvm_batch.$$"
mkdir -p "$WORK" && chmod 700 "$WORK"
trap 'rm -rf "$WORK"' 0

# The live pid of a server, or nothing. The pid file first - under the
# profile's logs/, or under a moved LOG_ROOT - and only if the pid inside is
# alive: a JVM that died leaves its file behind.
pid_of() {
    files="$1/logs/$2/$2.pid"
    [ -n "$WAS_LOG_ROOT" ] && files="$WAS_LOG_ROOT/$2/$2.pid $files"
    for f in $files; do
        if [ -f "$f" ]; then
            p=$(cat "$f" 2>/dev/null)
            if [ -n "$p" ] && kill -0 "$p" 2>/dev/null; then echo "$p"; return; fi
        fi
    done
}

# The maximum heap of a server, in MB: -Xmx in its generic JVM arguments
# wins, as it does at run time; else maximumHeapSize; else the unset value.
xmx_of() {
    sx="$1"
    gen=$(sed -n 's/.*genericJvmArguments="\([^"]*\)".*/\1/p' "$sx" | head -1)
    x=$(printf '%s\n' "$gen" | sed -n 's/.*-Xmx\([0-9][0-9]*\)\([kKmMgG]\{0,1\}\).*/\1 \2/p' | head -1)
    if [ -n "$x" ]; then
        set -- $x
        case "$2" in
            g|G) echo $(( $1 * 1024 )) ;;
            k|K) echo $(( $1 / 1024 )) ;;
            m|M) echo "$1" ;;
            *)   echo $(( $1 / 1048576 )) ;;
        esac
        return
    fi
    m=$(sed -n 's/.*maximumHeapSize="\([0-9][0-9]*\)".*/\1/p' "$sx" | head -1)
    echo "${m:-${JVM_XMX_UNSET_MB:-256}}"
}

discover() {
    for prof in "$WAS_PROFILES_DIR"/*; do
        setup="$prof/bin/setupCmdLine.sh"
        [ -f "$setup" ] || continue
        cell=$(sed -n 's/^WAS_CELL=\(.*\)$/\1/p' "$setup" | head -1)
        node=$(sed -n 's/^WAS_NODE=\(.*\)$/\1/p' "$setup" | head -1)
        idx="$prof/config/cells/$cell/nodes/$node/serverindex.xml"
        [ -f "$idx" ] || continue
        # serverEntries are one line each; their attributes in any order.
        grep '<serverEntries' "$idx" | while read -r entry; do
            srv=$(printf '%s\n' "$entry" | sed -n 's/.*serverName="\([^"]*\)".*/\1/p')
            typ=$(printf '%s\n' "$entry" | sed -n 's/.*serverType="\([^"]*\)".*/\1/p')
            case "$typ" in
                APPLICATION_SERVER|NODE_AGENT|DEPLOYMENT_MANAGER) ;;
                *) continue ;;
            esac
            xmx=0
            if [ "$typ" = APPLICATION_SERVER ]; then
                sx="$prof/config/cells/$cell/nodes/$node/servers/$srv/server.xml"
                [ -f "$sx" ] || continue
                xmx=$(xmx_of "$sx")
            fi
            pid=$(pid_of "$prof" "$srv")
            state=stopped; [ -n "$pid" ] && state=running
            echo "$prof|$cell|$node|$srv|$xmx|$state|$pid|$typ"
        done
    done
}

# The command that stops or starts a process: the node agent and the
# deployment manager have their own, under the names WAS gives them.
control() {
    case "$2" in
        nodeagent) echo "$1/bin/${3}Node.sh" ;;
        dmgr)      echo "$1/bin/${3}Manager.sh" ;;
        *)         echo "$1/bin/${3}Server.sh $2" ;;
    esac
}

stop_one() {
    prof="$1"; srv="$2"
    pid=$(pid_of "$prof" "$srv")
    if [ -z "$pid" ]; then echo "$srv|already-stopped|"; return; fi
    cmd=$(control "$prof" "$srv" stop)
    if [ -n "$WAS_STOP_USER" ]; then
        $cmd -username "$WAS_STOP_USER" -password "$WAS_STOP_PASSWORD" > "$WORK/$srv.stop.log" 2>&1 &
    else
        $cmd > "$WORK/$srv.stop.log" 2>&1 &
    fi
    client=$!
    t=0
    while kill -0 "$pid" 2>/dev/null && [ "$t" -lt "${JVM_STOP_TIMEOUT:-300}" ]; do
        sleep 5; t=$((t + 5))
    done
    if ! kill -0 "$pid" 2>/dev/null; then
        wait "$client" 2>/dev/null
        echo "$srv|stopped|$pid|${t}s"
        return
    fi
    # Too long: the stop command gave up or hangs. The JVM is killed - TERM
    # first, so it can still write its last logs, then KILL.
    kill "$client" 2>/dev/null
    kill -15 "$pid" 2>/dev/null
    g=0
    while kill -0 "$pid" 2>/dev/null && [ "$g" -lt "${JVM_KILL_GRACE:-30}" ]; do
        sleep 2; g=$((g + 2))
    done
    if kill -0 "$pid" 2>/dev/null; then
        kill -9 "$pid" 2>/dev/null
        sleep 2
    fi
    if kill -0 "$pid" 2>/dev/null; then
        echo "$srv|STILL-RUNNING|$pid|stop and kill both failed"
    else
        echo "$srv|killed|$pid|stop exceeded ${JVM_STOP_TIMEOUT:-300}s"
    fi
}

start_one() {
    prof="$1"; srv="$2"
    pid=$(pid_of "$prof" "$srv")
    if [ -n "$pid" ]; then echo "$srv|already-running|$pid"; return; fi
    $(control "$prof" "$srv" start) -timeout "${JVM_START_TIMEOUT:-600}" > "$WORK/$srv.start.log" 2>&1
    rc=$?
    pid=$(pid_of "$prof" "$srv")
    if [ "$rc" -eq 0 ] && [ -n "$pid" ]; then
        echo "$srv|started|$pid"
    else
        echo "$srv|FAILED|rc=$rc|$(tail -3 "$WORK/$srv.start.log" 2>/dev/null | tr '\n' ' ')"
    fi
}

mode="$1"; shift
case "$mode" in
    discover) discover ;;
    stop|start)
        n=0
        for ps in "$@"; do
            n=$((n + 1))
            # <profile>:<server>, cut at the LAST colon: a server name has
            # none, a path might.
            ( "${mode}_one" "${ps%:*}" "${ps##*:}" > "$WORK/result.$n" ) &
        done
        wait
        cat "$WORK"/result.* 2>/dev/null
        ;;
    *) echo "usage: $0 discover | stop <profile>:<server>... | start <profile>:<server>..." >&2; exit 2 ;;
esac
