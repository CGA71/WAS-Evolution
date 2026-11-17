#!/usr/bin/env bash
# Assert that an ansible-playbook log ends with changed=0 on every host.
#
#   bash ci/assert-idempotent.sh run2.log
#
# The replay of a job is the only real proof of idempotency: the legacy
# marker files reported "nothing to do" whether or not the server still
# matched. Colour codes are stripped first - ANSIBLE_FORCE_COLOR splits the
# recap line into coloured segments - and localhost is ignored: its plays are
# the guards, which change nothing by construction.

set -euo pipefail

log="${1:?usage: assert-idempotent.sh <ansible log>}"
[ -s "$log" ] || { echo "no log at $log"; exit 1; }

recap="$(sed 's/\x1b\[[0-9;]*m//g' "$log" | awk '/^PLAY RECAP/ { on = 1; next } on && /changed=/')"
[ -n "$recap" ] || { echo "no PLAY RECAP in $log - the run did not finish"; exit 1; }

bad="$(printf '%s\n' "$recap" | grep -v '^localhost ' | grep -v 'changed=0' || true)"
if [ -n "$bad" ]; then
    echo "IDEMPOTENCY FAILURE - the replay changed something:"
    printf '%s\n' "$bad"
    exit 1
fi
echo "the replay reported changed=0 on every host:"
printf '%s\n' "$recap" | grep -v '^localhost ' | sed 's/^/  /'
