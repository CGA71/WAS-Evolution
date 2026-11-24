#!/bin/sh
# The JVM batch script, against a fake WAS profile - no WAS, no server.
#
# A profile with five servers: a node agent (stopNode.sh / startNode.sh), a JVM that stops
# when asked, one that ignores both the stop command and SIGTERM (it must be
# killed), one already stopped, and one whose -Xmx is in its generic JVM
# arguments. Checks: discovery and -Xmx reading, the stop / kill path, the
# start, and that a second start leaves a running JVM alone.
#
#   sh ci/test-jvm-batch.sh
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
J="$HERE/../ansible_collections/wasevo/websphere/roles/traditional/jvm_batch/files/jvm_batch.sh"
T=$(mktemp -d)
P="$T/profiles/Node1Test"
C="$P/config/cells/TEST90Cell/nodes/Node1Test"
# `|| true`: under set -e a kill of a process already gone would end the
# script with status 1 after every check had passed, and before the rm.
cleanup() {
    for f in "$P"/logs/*/*.pid; do [ -f "$f" ] && kill -9 "$(cat "$f")" 2>/dev/null || true; done
    rm -rf "$T"
}
trap cleanup 0
fail() { echo "FAIL: $*"; exit 1; }

mkdir -p "$P/bin" "$C/servers"
printf 'WAS_CELL=TEST90Cell\nWAS_NODE=Node1Test\n' > "$P/bin/setupCmdLine.sh"
cat > "$C/serverindex.xml" <<'EOF'
<serverindex:ServerIndex xmi:version="2.0">
  <serverEntries xmi:id="ServerEntry_1" serverName="nodeagent" serverType="NODE_AGENT">
  <serverEntries xmi:id="ServerEntry_2" serverDisplayName="APP512" serverName="APP512" serverType="APPLICATION_SERVER">
  <serverEntries xmi:id="ServerEntry_3" serverName="APP1024" serverType="APPLICATION_SERVER" serverUniqueId="y">
  <serverEntries xmi:id="ServerEntry_4" serverName="APPXMX" serverType="APPLICATION_SERVER">
  <serverEntries xmi:id="ServerEntry_5" serverName="APPHANG" serverType="APPLICATION_SERVER">
</serverindex:ServerIndex>
EOF
for s in APP512 APP1024 APPXMX APPHANG; do mkdir -p "$C/servers/$s" "$P/logs/$s"; done
mkdir -p "$P/logs/nodeagent"
echo '<jvmEntries xmi:id="J" initialHeapSize="256" maximumHeapSize="512" genericJvmArguments="">' > "$C/servers/APP512/server.xml"
echo '<jvmEntries xmi:id="J" maximumHeapSize="1024">' > "$C/servers/APP1024/server.xml"
echo '<jvmEntries xmi:id="J" maximumHeapSize="512" genericJvmArguments="-Xms1g -Xmx2g -Dx=y">' > "$C/servers/APPXMX/server.xml"
echo '<jvmEntries xmi:id="J">' > "$C/servers/APPHANG/server.xml"

# Fake JVMs: APP512 stops on request; APPHANG ignores the stop and SIGTERM.
#
# Not children of this script, as a real JVM is not: a child killed while
# this script waits in a $(...) stays a zombie until reaped, and kill -0 -
# what jvm_batch.sh asks - answers "alive" for a zombie. A wrapper shell
# starts each one, waits for it, reaps it when it dies.
spawn() { # spawn <pid file> <command...>
    f="$1"; shift
    sh -c '"$@" & echo $! > "$0"; wait' "$f" "$@" > /dev/null 2>&1 &
    while [ ! -s "$f" ]; do sleep 1; done
}
spawn "$P/logs/APP512/APP512.pid" sleep 600
spawn "$P/logs/nodeagent/nodeagent.pid" sleep 600
spawn "$P/logs/APPHANG/APPHANG.pid" sh -c 'trap "" TERM; while :; do sleep 1; done'
cat > "$P/bin/stopServer.sh" <<'EOF'
#!/bin/sh
[ "$1" = APPHANG ] && { sleep 600; exit 1; }
kill "$(cat "$(dirname "$0")/../logs/$1/$1.pid")"
EOF
cat > "$P/bin/startServer.sh" <<'EOF'
#!/bin/sh
sleep 600 > /dev/null 2>&1 &
echo $! > "$(dirname "$0")/../logs/$1/$1.pid"
EOF
cat > "$P/bin/stopNode.sh" <<'EOF'
#!/bin/sh
kill "$(cat "$(dirname "$0")/../logs/nodeagent/nodeagent.pid")"
EOF
cat > "$P/bin/startNode.sh" <<'EOF'
#!/bin/sh
sleep 600 > /dev/null 2>&1 &
echo $! > "$(dirname "$0")/../logs/nodeagent/nodeagent.pid"
EOF
chmod +x "$P/bin/"*.sh

export WAS_PROFILES_DIR="$T/profiles" JVM_STOP_TIMEOUT=6 JVM_KILL_GRACE=4 JVM_START_TIMEOUT=10

echo "== discover"
out=$(sh "$J" discover | cut -d'|' -f4-6,8 | sort)
echo "$out"
echo "$out" | grep -qx 'APP512|512|running|APPLICATION_SERVER'   || fail "APP512 not read as 512 MB, running"
echo "$out" | grep -qx 'APP1024|1024|stopped|APPLICATION_SERVER' || fail "APP1024 not read as 1024 MB, stopped"
echo "$out" | grep -qx 'APPXMX|2048|stopped|APPLICATION_SERVER'  || fail "-Xmx2g in the generic arguments is not 2048 MB"
echo "$out" | grep -qx 'APPHANG|256|running|APPLICATION_SERVER'  || fail "an unset maximum heap is not counted at 256 MB"
echo "$out" | grep -qx 'nodeagent|0|running|NODE_AGENT'          || fail "the node agent was not read as a node agent"

echo "== stop"
out=$(sh "$J" stop "$P:APP512" "$P:APPHANG" "$P:APP1024")
echo "$out"
echo "$out" | grep -q '^APP512|stopped|'         || fail "APP512 was not stopped by its stop command"
echo "$out" | grep -q '^APPHANG|killed|'         || fail "APPHANG was not killed after the timeout"
echo "$out" | grep -q '^APP1024|already-stopped' || fail "APP1024 was not left alone"

echo "== start"
out=$(sh "$J" start "$P:APP512" "$P:APP1024")
echo "$out"
echo "$out" | grep -q '^APP512|started|'  || fail "APP512 did not start"
echo "$out" | grep -q '^APP1024|started|' || fail "APP1024 did not start"
out=$(sh "$J" start "$P:APP512")
echo "$out" | grep -q '^APP512|already-running|' || fail "a running JVM was started again"

echo "== node agent"
out=$(sh "$J" stop "$P:nodeagent")
echo "$out"; echo "$out" | grep -q '^nodeagent|stopped|' || fail "stopNode.sh was not used for the node agent"
out=$(sh "$J" start "$P:nodeagent")
echo "$out"; echo "$out" | grep -q '^nodeagent|started|' || fail "startNode.sh was not used for the node agent"

echo "jvm_batch.sh: discover, stop, kill and start behave"
