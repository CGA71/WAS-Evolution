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
# Run it from any host that reaches AWX (AWX_API, user AWX_USER, admin by
# default). The password is typed at the prompt and never appears in an
# argument, an environment variable or this repository.
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
#
# The one question that is not a name is "Application servers per node", which
# is the VERTICAL axis of the cluster - how many application server JVMs each
# federated node carries. The horizontal axis is not asked and cannot be: a
# survey is flat, it has no repeating group, so the list of nodes comes from
# the inventory. It is an integer question with a default, so an unanswered one
# sends 1 rather than an empty string.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SPEC="${SURVEY_SPEC:-$HERE/surveys/was-build.json}"
API="${AWX_API:-https://awx.example.internal/api/v2}"
AWX_USER="${AWX_USER:-admin}"
WORKFLOW="${AWX_WORKFLOW:-WAS AIX - cell on ServeurAIX}"

say() { printf '\n== %s\n' "$*"; }
ok()  { printf '   ok    %s\n' "$*"; }
die() { printf '   FAIL  %s\n' "$*" >&2; exit 1; }

[ -f "$SPEC" ] || die "no survey spec at $SPEC"
python3 -c "import json,sys; json.load(open(sys.argv[1]))" "$SPEC" \
    || die "$SPEC is not valid JSON"

# The password is never passed as an argument: curl -u puts it in this host's
# process list, where any local account can read it. --netrc-file with a pipe
# is not portable, so a netrc file is used, in a private temporary directory
# (mode 0700, made by Python's tempfile.mkdtemp) removed on exit.
WORKDIR="$(python3 -c 'import tempfile; print(tempfile.mkdtemp(prefix="awx-"))')"
[ -d "$WORKDIR" ] || die "could not create the temporary directory"
trap 'rm -rf "$WORKDIR"' EXIT
NETRC="$WORKDIR/netrc"

# Typed at the prompt, without echo. printf is a builtin, so the password never
# reaches this host's process list either.
# AUTHENTICATION, in this order:
#   AWX_TOKEN_FILE   a file holding an AWX personal access token (OAuth2,
#                    User > Tokens in AWX). Preferred: revocable, scoped, no
#                    password typed. Sent as "Authorization: Bearer", from a
#                    0600 header file, so the token never reaches a command line.
#   AWX_NETRC_FILE   a netrc already written by a calling script
#                    (apply-cell-workflow.sh runs apply-survey.sh), reused so
#                    the password is typed once per run.
#   otherwise        AWX_USER's password, typed at the prompt.
if [ -n "${AWX_TOKEN_FILE:-}" ]; then
    [ -r "$AWX_TOKEN_FILE" ] || die "cannot read AWX_TOKEN_FILE ($AWX_TOKEN_FILE)"
    ( umask 077
      printf 'Authorization: Bearer %s\n' "$(tr -d ' \r\n' < "$AWX_TOKEN_FILE")" > "$WORKDIR/auth.header" )
    AUTH=(-H "@$WORKDIR/auth.header")
elif [ -n "${AWX_NETRC_FILE:-}" ] && [ -s "$AWX_NETRC_FILE" ]; then
    NETRC="$AWX_NETRC_FILE"
    AUTH=(--netrc-file "$NETRC")
else
    IFS= read -rsp "AWX password for $AWX_USER: " _awx_pw </dev/tty \
        || die "could not read the AWX password from the terminal"
    printf '\n' >&2
    [ -n "$_awx_pw" ] || die "empty AWX password"
    # The host part of AWX_API, by parameter expansion: AIX sed has no -E.
    _host="${API#*://}"; _host="${_host%%/*}"
    ( umask 077
      printf 'machine %s login %s password %s\n' \
          "$_host" "$AWX_USER" "$_awx_pw" > "$NETRC" )
    unset _awx_pw
    [ -s "$NETRC" ] || die "could not write the temporary credential file"
    AUTH=(--netrc-file "$NETRC")
fi

# --noproxy "*": AWX is reached directly, never through the HTTP proxy the
# environment may declare (http_proxy, https_proxy). Through that proxy the API
# answers 504 Gateway Timeout.
#
# TLS: AWX's certificate is usually signed by an internal authority. With
# AWX_CA_FILE pointing at that authority's certificate it is verified;
# without it, -k accepts it unverified.
if [ -n "${AWX_CA_FILE:-}" ]; then CURL_TLS=(--cacert "$AWX_CA_FILE"); else CURL_TLS=(-k); fi
api() {
    local method="$1" path="$2"
    shift 2
    curl -sS "${CURL_TLS[@]}" --noproxy '*' "${AUTH[@]}" -X "$method" \
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

# A job template whose form is its own, not the build's. The two fix pack
# jobs - one playbook, lab_apply_fixpacks.yml - ask the component, the
# version of each product and the homes (surveys/fixpack.json), nothing about
# the cell. In the build workflow they run with the form's defaults: job 2,
# before WAS is installed, finds nothing in the homes and changes nothing;
# job 4 updates what jobs 3 to 3c installed.
own_spec() {
    case "$1" in
        "WAS AIX - 2. Fix packs: Installation Manager"|"WAS AIX - 4. Fix packs: WAS")
            echo "$HERE/surveys/fixpack.json" ;;
        *) echo "$SPEC" ;;
    esac
}

attach() {
    local path="$1" label="$2" spec="${3:-$SPEC}"
    api POST "/$path/survey_spec/" --data-binary "@$spec" >/dev/null \
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
    attach "job_templates/$i" "$nm" "$(own_spec "$nm")"
    ask_job_type "$i" "$nm"
done

say "Done"
printf '   Check the form yourself at:\n\n     %s\n\n' \
    "$(printf '%s' "$API" | sed 's#/api/v2##')/#/templates/workflow_job_template/$WF_ID/survey"
printf '   Launching the workflow now asks for the environment, the channel and\n'
printf '   the object names. A name left blank is derived; a name filled in wins.\n'
