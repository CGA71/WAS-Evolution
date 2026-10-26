#!/usr/bin/env bash
# Configure what AWX asks at launch: the WAS build survey on the workflow and
# on every job template it runs, and the Job type prompt on the templates.
#
# WHY THE JOB TYPE PROMPT. Simulating a run is a check run - Job type: Check,
# which is ansible-playbook --check. The templates shipped with
# ask_job_type_on_launch false, so Check was not selectable and the only way to
# rehearse an install was to run it. The roles behave correctly under check
# mode; this makes that reachable from the launch dialog.
#
#   bash ci/awx/apply-survey.sh            apply
#   bash ci/awx/apply-survey.sh --show     print what is attached today
#
# Run it from the k3s node. The admin password is read from the Secret the
# operator generated and never appears in an argument, an environment variable
# or this repository.
#
# WHY THE SURVEY IS ON THE WORKFLOW AND ON THE TEMPLATES. The workflow is how
# the build is meant to be launched, and a survey there is answered once and
# propagates to every node. But a job template can be launched on its own -
# that is deliberate, the templates are separately runnable - and without its
# own survey such a launch falls back to a free-text extra-vars box, which is
# the thing the survey exists to replace.
#
# WHY NAMES ARE OPTIONAL. An unanswered optional question sends an empty
# string, and roles/model/tasks/naming.yml publishes every name with
# `| default(<pattern>, true)`. The `true` is what makes an empty answer fall
# back to the pattern rather than overriding it with "". Leave a name blank and
# it is derived; fill it in and it is imposed.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SPEC="${SURVEY_SPEC:-$HERE/surveys/was-build.json}"
API="${AWX_API:-http://awx.lab.example.com/api/v2}"
WORKFLOW="${AWX_WORKFLOW:-WAS lab - install WAS for Developers}"

export KUBECONFIG="${KUBECONFIG:-$HOME/.kube/config}"

say() { printf '\n== %s\n' "$*"; }
ok()  { printf '   ok    %s\n' "$*"; }
die() { printf '   FAIL  %s\n' "$*" >&2; exit 1; }

[ -f "$SPEC" ] || die "no survey spec at $SPEC"
python3 -c "import json,sys; json.load(open(sys.argv[1]))" "$SPEC" \
    || die "$SPEC is not valid JSON"

# The password is fetched per call and piped, never passed as an argument:
# curl -u puts it in this host's process list, where any local account can read
# it. --netrc-file with a pipe is not portable, so a temporary file with mode
# 0600 is used and removed on exit.
NETRC="$(mktemp)"
chmod 600 "$NETRC"
trap 'rm -f "$NETRC"' EXIT

# Read into a variable, not through `read` in a pipeline: base64 -d emits the
# password with no trailing newline, so `read` returns 1 on EOF and set -e
# kills the script before it has printed a single line. printf is a builtin,
# so the password never reaches this host's process list either.
_awx_pw="$(kubectl -n awx get secret awx-admin-password -o jsonpath='{.data.password}' | base64 -d)"
[ -n "$_awx_pw" ] || die "could not read the AWX admin password from the Secret"
printf 'machine %s login admin password %s\n' \
    "$(printf '%s' "$API" | sed -E 's#^https?://([^/]+).*#\1#')" "$_awx_pw" > "$NETRC"
unset _awx_pw
[ -s "$NETRC" ] || die "could not write the temporary credential file"

api() {
    local method="$1" path="$2"
    shift 2
    curl -sS --netrc-file "$NETRC" -X "$method" \
        -H "Content-Type: application/json" "$API$path" "$@"
}

jqp() { python3 -c "$1"; }

say "AWX"
api GET /ping/ >/dev/null || die "cannot reach $API"
ok "$API reachable"

# ---------------------------------------------------------------------------
# Find the workflow and the templates it runs
# ---------------------------------------------------------------------------
say "Targets"

WF_ID="$(api GET "/workflow_job_templates/?name=$(printf '%s' "$WORKFLOW" | sed 's/ /%20/g')" \
    | jqp 'import sys,json
d=json.load(sys.stdin)
print(d["results"][0]["id"] if d["count"] else "")')"
[ -n "$WF_ID" ] || die "no workflow named \"$WORKFLOW\" in AWX"
ok "workflow \"$WORKFLOW\" is id $WF_ID"

# Every job template reached by a node of that workflow, deduplicated. Taken
# from the graph rather than from a hardcoded list, so a node added in AWX is
# picked up here without editing this script.
JT_IDS="$(api GET "/workflow_job_templates/$WF_ID/workflow_nodes/?page_size=200" \
    | jqp 'import sys,json
seen=[]
for n in json.load(sys.stdin)["results"]:
    u=n.get("summary_fields",{}).get("unified_job_template") or {}
    if u.get("unified_job_type")=="job" and u["id"] not in seen:
        seen.append(u["id"])
print(" ".join(str(i) for i in seen))')"
ok "job templates in the graph: ${JT_IDS:-(none)}"

if [ "${1:-}" = "--show" ]; then
    say "Attached today"
    for kind_id in "workflow_job_templates/$WF_ID" $(for i in $JT_IDS; do echo "job_templates/$i"; done); do
        name="$(api GET "/${kind_id}/" | jqp 'import sys,json;d=json.load(sys.stdin);print(d["name"],"| survey_enabled:",d["survey_enabled"])')"
        printf '   %s\n' "$name"
        api GET "/${kind_id}/survey_spec/" | jqp 'import sys,json
d=json.load(sys.stdin)
s=d.get("spec") or []
if not s:
    print("        (no survey)")
for q in s:
    print("        {:<28} {:<22} {}".format(
        q["variable"], q["type"] + ("/required" if q["required"] else "/optional"),
        q["question_name"]))'
    done
    exit 0
fi

# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------
say "Apply"

attach() {
    local path="$1" label="$2"
    api POST "/$path/survey_spec/" --data-binary "@$SPEC" >/dev/null \
        || die "could not post the survey to $label"
    api PATCH "/$path/" -d '{"survey_enabled": true}' >/dev/null \
        || die "could not enable the survey on $label"
    local n
    n="$(api GET "/$path/survey_spec/" | jqp 'import sys,json;print(len(json.load(sys.stdin).get("spec") or []))')"
    [ "$n" -gt 0 ] || die "$label reports an empty survey after the post"
    ok "$label: $n questions, survey enabled"
}

# Only a job template has a job type; a workflow has none - its nodes carry it.
# Simulating a run is Job type: Check, which is ansible-playbook --check.
ask_job_type() {
    local id="$1" label="$2"
    api PATCH "/job_templates/$id/" -d '{"ask_job_type_on_launch": true}' >/dev/null         || die "could not enable the Job type prompt on $label"
    api GET "/job_templates/$id/"         | jqp 'import sys,json;d=json.load(sys.stdin);sys.exit(0 if d["ask_job_type_on_launch"] else 1)'         || die "$label still does not ask for the Job type"
    ok "$label: Job type selectable at launch (Run or Check)"
}

attach "workflow_job_templates/$WF_ID" "workflow \"$WORKFLOW\""
for i in $JT_IDS; do
    nm="$(api GET "/job_templates/$i/" | jqp 'import sys,json;print(json.load(sys.stdin)["name"])')"
    attach "job_templates/$i" "$nm"
    ask_job_type "$i" "$nm"
done

say "Done"
printf '   Check the form yourself at:\n\n     %s\n\n' \
    "$(printf '%s' "$API" | sed 's#/api/v2##')/#/templates/workflow_job_template/$WF_ID/survey"
printf '   Launching the workflow now asks for the environment, the channel and\n'
printf '   the object names. A name left blank is derived; a name filled in wins.\n'
