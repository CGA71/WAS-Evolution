#!/usr/bin/env bash
# Declare, in AWX, the two application workflows of the AIX cell:
#
#   "WAS AIX - Application: deploy"         one node: the resources the
#                                           application declares, then its
#                                           archive, installed or reinstalled
#   "WAS AIX - Application: decommission"   one node per step, in order:
#
#        0. plan            what goes, what stays and why, the cluster and the
#                           node decisions - passed on with set_stats
#        -  approval        a person reads the plan and approves; nothing is
#                           removed before that
#        1. uninstall       stopped on its members, uninstalled
#        2. JMS  3. JDBC  4. J2C aliases  5. shared libraries  6. variables
#        7. cluster         only if asked, and only if nothing else is mapped
#                           to it
#        8. node            only if asked, the cluster removed, and the node
#                           has no application server and no resource left
#        9. inventory       the applications of the cell read again, for the
#                           application portal - also the last node of deploy
#
# And the application portal itself: the template "WAS AIX - Applications:
# inventory" with a daily schedule per environment named in
# AWX_APP_INVENTORY_ENVIRONMENTS, and the template "Applications - portal" that
# copies the page behind AWX's web front.
#
#   AWX_API=https://<awx>/api/v2 bash ci/awx/apply-application-workflows.sh
#   AWX_API=https://<awx>/api/v2 bash ci/awx/apply-application-workflows.sh --show
#
# Run after apply-cell-workflow.sh, which creates the inventory "WAS AIX".
# Re-runnable: every object is found by name and patched. The applications
# themselves are declared in the inventory (was_applications) - the survey
# only names one of them.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
API="${AWX_API:-https://awx.example.internal/api/v2}"
AWX_USER="${AWX_USER:-admin}"
PROJECT="${AWX_PROJECT:-WAS Evolution}"
INVENTORY="${AWX_CELL_INVENTORY:-WAS AIX}"
MACHINE_CRED="${AWX_MACHINE_CRED:-ServeurAIX (ansible)}"
WAS_CRED_TYPE="${AWX_WAS_CRED_TYPE:-WAS administrative user}"
DEPLOY_WF="${AWX_APP_DEPLOY_WORKFLOW:-WAS AIX - Application: deploy}"
DECOM_WF="${AWX_APP_DECOM_WORKFLOW:-WAS AIX - Application: decommission}"
COL=ansible_collections/wasevo/websphere/playbooks

say() { printf '\n== %s\n' "$*"; }
ok()  { printf '   ok    %s\n' "$*"; }
note(){ printf '   --    %s\n' "$*"; }
die() { printf '   FAIL  %s\n' "$*" >&2; exit 1; }

# Same credential handling as apply-survey.sh: the netrc and the request body
# live in a private temporary directory made by Python, removed on exit.
WORKDIR="$(python3 -c 'import tempfile; print(tempfile.mkdtemp(prefix="awx-"))')"
[ -d "$WORKDIR" ] || die "could not create the temporary directory"
trap 'rm -rf "$WORKDIR"' EXIT
NETRC="$WORKDIR/netrc"
BODY="$WORKDIR/body"

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
py() { python3 -c "$1" "${@:2}"; }
id_of() {
    api GET "/$1/?name=$(py 'import sys,urllib.parse;print(urllib.parse.quote(sys.argv[1]))' "$2")" \
      | py 'import sys,json
for r in json.load(sys.stdin).get("results", []):
    if r["name"] == sys.argv[1]:
        print(r["id"]); break' "$2"
}
# Create or patch an object by name; the body is read from $BODY so a secret
# in it never reaches a command line.
upsert() {
    local kind="$1" name="$2" id
    id="$(id_of "$kind" "$name")"
    if [ -n "$id" ]; then
        api PATCH "/$kind/$id/" --data-binary "@$BODY" >/dev/null || die "could not update $name"
        ok "updated  $name (id $id)" >&2
    else
        id="$(api POST "/$kind/" --data-binary "@$BODY" | py 'import sys,json
d = json.load(sys.stdin)
if "id" not in d:
    raise SystemExit("refused: " + json.dumps(d)[:400])
print(d["id"])')" || die "could not create $name"
        ok "created  $name (id $id)" >&2
    fi
    printf '%s' "$id"
}


show() {
    local wf_id
    wf_id="$(id_of workflow_job_templates "$1")"
    [ -n "$wf_id" ] || { note "no workflow named \"$1\" yet"; return 0; }
    say "$1"
    api GET "/workflow_job_templates/$wf_id/workflow_nodes/?page_size=200" | py 'import sys,json
for n in json.load(sys.stdin)["results"]:
    u = n.get("summary_fields", {}).get("unified_job_template") or {}
    print("   node %-5s %-60s success -> %s" % (n["id"], u.get("name"), n.get("success_nodes")))'
}

if [ "${1:-}" = "--show" ]; then
    show "$DEPLOY_WF"
    show "$DECOM_WF"
    exit 0
fi

# ---------------------------------------------------------------------------
say "AWX objects"
# ---------------------------------------------------------------------------
api GET /ping/ >/dev/null || die "cannot reach $API"
ORG_ID="$(api GET "/organizations/" | py 'import sys,json;print(json.load(sys.stdin)["results"][0]["id"])')"
PROJECT_ID="$(id_of projects "$PROJECT")"
[ -n "$PROJECT_ID" ] || die "no project named \"$PROJECT\""
INV_ID="$(id_of inventories "$INVENTORY")"
[ -n "$INV_ID" ] || die "no inventory named \"$INVENTORY\" - run apply-cell-workflow.sh first"
MACHINE_CRED_ID="$(id_of credentials "$MACHINE_CRED")"
[ -n "$MACHINE_CRED_ID" ] || die "no credential named \"$MACHINE_CRED\""
CT_ID="$(id_of credential_types "$WAS_CRED_TYPE")"
WAS_CRED_ID=""
if [ -n "$CT_ID" ]; then
    WAS_CRED_ID="$(api GET "/credentials/?credential_type=$CT_ID" | py 'import sys,json
d=json.load(sys.stdin)
print(d["results"][0]["id"] if d.get("count") else "")')"
fi
[ -n "$WAS_CRED_ID" ] || note "no \"$WAS_CRED_TYPE\" credential yet - every template will ask for one at launch"
EE_ID="$(api GET "/job_templates/?page_size=200" | py 'import sys,json
for t in json.load(sys.stdin)["results"]:
    if t.get("execution_environment"):
        print(t["execution_environment"]); break')"
[ -n "$EE_ID" ] || die "could not work out which Execution Environment to use"

# The project first: a template naming a playbook pushed after the project's
# last update is refused as "Playbook not found".
UPDATE_ID="$(api POST "/projects/$PROJECT_ID/update/" | py 'import sys,json;print(json.load(sys.stdin).get("id",""))')"
for _ in $(seq 1 60); do
    st="$(api GET "/project_updates/$UPDATE_ID/" | py 'import sys,json;print(json.load(sys.stdin).get("status",""))')"
    case "$st" in successful) break ;; failed|error|canceled) die "project update $st" ;; *) sleep 2 ;; esac
done
ok "project updated"

# One job template: the machine credential, the WAS credential when it exists,
# Job type selectable - a check run is how a step is rehearsed.
template() {
    local name="$1" playbook="$2" extra="$3" jt
    py 'import json,sys
name, playbook, extra, inv, proj, ee, ask = sys.argv[1:8]
b = {"name": name, "job_type": "run", "inventory": int(inv), "project": int(proj),
     "playbook": playbook, "execution_environment": int(ee),
     "become_enabled": False, "verbosity": 1, "timeout": 5400,
     "ask_job_type_on_launch": True, "ask_variables_on_launch": True,
     "ask_credential_on_launch": ask == "true"}
b["extra_vars"] = ("---\n%s\n" % extra.strip()) if extra.strip() else ""
print(json.dumps(b))' "$name" "$playbook" "$extra" "$INV_ID" "$PROJECT_ID" "$EE_ID" \
        "$([ -z "$WAS_CRED_ID" ] && echo true || echo false)" > "$BODY"
    jt="$(upsert job_templates "$name")"
    api POST "/job_templates/$jt/credentials/" -d "{\"id\": $MACHINE_CRED_ID}" >/dev/null || true
    [ -z "$WAS_CRED_ID" ] || api POST "/job_templates/$jt/credentials/" -d "{\"id\": $WAS_CRED_ID}" >/dev/null || true
    printf '%s' "$jt"
}

# The node of a workflow that runs a given template id, or carries a given
# (approval) name, or "".
node_of() {
    api GET "/workflow_job_templates/$1/workflow_nodes/?page_size=200" | py 'import sys,json
for n in json.load(sys.stdin)["results"]:
    u = n.get("summary_fields", {}).get("unified_job_template") or {}
    if str(u.get("id")) == sys.argv[1] or u.get("name") == sys.argv[2]:
        print(n["id"]); break' "$2" "${3:-}"
}

# Chain templates - or "approval:<name>" - into a workflow, each on the
# success of the one before.
chain() {
    local wf="$1" prev="" node item; shift
    for item in "$@"; do
        if [ "${item#approval:}" != "$item" ]; then
            node="$(node_of "$wf" "-" "${item#approval:}")"
            if [ -z "$node" ]; then
                node="$(api POST "/workflow_job_templates/$wf/workflow_nodes/" -d '{}' \
                        | py 'import sys,json;print(json.load(sys.stdin).get("id",""))')"
                [ -n "$node" ] || die "could not add an approval node"
                py 'import json,sys
print(json.dumps({"name": sys.argv[1], "timeout": 0,
  "description": "Read the plan node output before approving: what is removed, what is kept and why."}))' \
                    "${item#approval:}" > "$BODY"
                api POST "/workflow_job_template_nodes/$node/create_approval_template/" \
                    --data-binary "@$BODY" >/dev/null || die "could not make node $node an approval"
                ok "approval node $node"
            fi
        else
            node="$(node_of "$wf" "$item")"
            if [ -z "$node" ]; then
                node="$(api POST "/workflow_job_templates/$wf/workflow_nodes/" -d "{\"unified_job_template\": $item}" \
                        | py 'import sys,json;print(json.load(sys.stdin).get("id",""))')"
                [ -n "$node" ] || die "could not add template $item"
                ok "node $node for template $item"
            fi
        fi
        [ -z "$prev" ] || api POST "/workflow_job_template_nodes/$prev/success_nodes/" -d "{\"id\": $node}" >/dev/null || true
        prev="$node"
    done
}

# A workflow, with the survey given as a JSON file.
workflow() {
    local name="$1" description="$2" survey="$3" wf
    py 'import json,sys
print(json.dumps({"name": sys.argv[1], "organization": int(sys.argv[2]), "inventory": int(sys.argv[3]),
  "description": sys.argv[4], "ask_variables_on_launch": False, "survey_enabled": True}))' \
      "$name" "$ORG_ID" "$INV_ID" "$description" > "$BODY"
    wf="$(upsert workflow_job_templates "$name")"
    api POST "/workflow_job_templates/$wf/survey_spec/" --data-binary "@$survey" >/dev/null \
        || die "could not attach the survey to \"$name\""
    printf '%s' "$wf"
}

# ---------------------------------------------------------------------------
say "Applications inventory"
# ---------------------------------------------------------------------------
# Read only: the applications of the cell, published as job artifacts for the
# application portal. The last node of both workflows, so the portal shows the
# cell as the last change left it.
JT_INV="$(template "WAS AIX - Applications: inventory" "$COL/traditional_applications.yml" \
    "config_dmgr_hosts: dmgr")"

# ---------------------------------------------------------------------------
say "Deploy"
# ---------------------------------------------------------------------------
JT_DEPLOY="$(template "WAS AIX - Application: deploy" "$COL/traditional_application_deploy.yml" \
    "config_dmgr_hosts: dmgr")"
WF="$(workflow "$DEPLOY_WF" \
    "The resources the application declares, then its archive from the applications share - installed, or uninstalled and installed again when it changed." \
    "$HERE/surveys/application-deploy.json")"
chain "$WF" "$JT_DEPLOY" "$JT_INV"

# ---------------------------------------------------------------------------
say "Decommission"
# ---------------------------------------------------------------------------
STEPS=(
  "0. plan|plan"
  "1. uninstall|uninstall"
  "2. JMS resources|jms"
  "3. JDBC providers and datasources|jdbc"
  "4. J2C aliases|j2c"
  "5. shared libraries|libraries"
  "6. WebSphere variables|variables"
  "7. cluster|cluster"
)
IDS=()
for step in "${STEPS[@]}"; do
    label="${step%%|*}"; key="${step#*|}"
    IDS+=("$(template "WAS AIX - Application: decommission - $label" \
        "$COL/traditional_application_decommission.yml" \
        "config_dmgr_hosts: dmgr
application_step: $key")")
done
JT_NODE="$(template "WAS AIX - Application: decommission - 8. node agent and node" \
    "$COL/traditional_application_remove_node.yml" "config_dmgr_hosts: dmgr")"

WF="$(workflow "$DECOM_WF" \
    "The plan, an approval, then the application and the resources it declared, step by step - and, if asked and nothing else needs them, its cluster and its node." \
    "$HERE/surveys/application-decommission.json")"
chain "$WF" "${IDS[0]}" "approval:Approve the decommissioning plan" "${IDS[@]:1}" "$JT_NODE" "$JT_INV"

# ---------------------------------------------------------------------------
say "Daily reading of each cell"
# ---------------------------------------------------------------------------
# One schedule per environment the portal should show, so a change made by
# hand in the console appears on the page the next morning at the latest.
#   AWX_APP_INVENTORY_ENVIRONMENTS="<code> <code>"
SCHED_RRULE="${AWX_APP_INVENTORY_RRULE:-DTSTART;TZID=Europe/Paris:20261118T063000 RRULE:FREQ=DAILY;INTERVAL=1}"
if [ -z "${AWX_APP_INVENTORY_ENVIRONMENTS:-}" ]; then
    note "AWX_APP_INVENTORY_ENVIRONMENTS is empty - no daily reading scheduled"
fi
for env_code in ${AWX_APP_INVENTORY_ENVIRONMENTS:-}; do
    sched_name="Applications inventory - $env_code"
    py 'import json,sys
print(json.dumps({"name": sys.argv[1], "rrule": sys.argv[2], "enabled": True,
                  "extra_data": {"was_environment": sys.argv[3]}}))' "$sched_name" "$SCHED_RRULE" "$env_code" > "$BODY"
    sched_id="$(api GET "/job_templates/$JT_INV/schedules/?name=$(py 'import sys,urllib.parse;print(urllib.parse.quote(sys.argv[1]))' "$sched_name")" \
        | py 'import sys,json
d=json.load(sys.stdin)
print(d["results"][0]["id"] if d.get("count") else "")')"
    if [ -n "$sched_id" ]; then
        api PATCH "/schedules/$sched_id/" --data-binary "@$BODY" >/dev/null || die "could not update $sched_name"
        ok "updated  $sched_name"
    else
        api POST "/job_templates/$JT_INV/schedules/" --data-binary "@$BODY" >/dev/null || die "could not create $sched_name"
        ok "created  $sched_name"
    fi
done

# ---------------------------------------------------------------------------
say "Portal template"
# ---------------------------------------------------------------------------
# The page itself, copied behind AWX's web front - the awx_web group of the
# inventory, reached with that host's own machine credential.
WEB_CRED="${AWX_WEB_MACHINE_CRED:-AWX web front (ansible)}"
py 'import json,sys
inv, proj, ee, playbook = sys.argv[1:5]
print(json.dumps({"name": "Applications - portal", "job_type": "run", "inventory": int(inv),
  "project": int(proj), "playbook": playbook, "execution_environment": int(ee),
  "become_enabled": False, "verbosity": 1, "ask_variables_on_launch": False}))' \
    "$INV_ID" "$PROJECT_ID" "$EE_ID" "$COL/platform_application_portal.yml" > "$BODY"
JT_PORTAL="$(upsert job_templates "Applications - portal")"
WEB_CRED_ID="$(id_of credentials "$WEB_CRED")"
if [ -n "$WEB_CRED_ID" ]; then
    api POST "/job_templates/$JT_PORTAL/credentials/" -d "{\"id\": $WEB_CRED_ID}" >/dev/null || true
else
    note "no credential named \"$WEB_CRED\" - attach the web front's machine credential to template $JT_PORTAL"
fi
note "launch \"Applications - portal\" once (id $JT_PORTAL), then open $(printf '%s' "$API" | sed 's#/api/v2##')/wasevo/applications/"


say "Done"
printf '   %s/#/templates/workflow_job_template/%s/visualizer\n' "$(printf '%s' "$API" | sed 's#/api/v2##')" "$WF"
