#!/usr/bin/env bash
# Declare, in AWX, the fix packs of the site - three paths, in this order:
#
#   1. the deployment manager, FIRST, a job of its own:
#        WAS AIX - Fix pack: deployment manager    traditional_fixpack_dmgr.yml
#        stop the deployment manager -> WASDMR (WAS ND + Java SDK) -> start it
#
#   2. WAS on the nodes, a workflow - many JVMs to stop and start:
#        WAS AIX - Fix pack WAS by JVM batch
#        stop 512 -> 1024 -> 1536 -> 2048 -> stop the node agent
#          -> WAS AIX - 2. Fix packs: Installation Manager, component WAS
#             (WAS ND + Java SDK)
#          -> start the node agent -> start 512 -> 1024 -> 1536 -> 2048
#      its stop and start nodes being two job templates, launchable alone to
#      relaunch or restart one batch:
#        WAS AIX - JVM stop by batch     traditional_jvm_stop.yml   form: JVM batch
#        WAS AIX - JVM start by batch    traditional_jvm_start.yml  form: JVM batch
#
#   3. IBM HTTP Server and its plugin, a job:
#        WAS AIX - Fix pack: IHS and plugin        traditional_fixpack_ihs.yml
#        stop the Apache instances -> IHSPLG (IHS + plugin + Java SDK) -> start them
#
# The fix pack jobs and the workflow ask Environment and Server
# (surveys/fixpack-target.json); each stop and start node of the workflow
# carries its own batch.
#
#   AWX_API=https://<awx>/api/v2 bash ci/awx/apply-fixpack.sh          apply
#   AWX_API=https://<awx>/api/v2 bash ci/awx/apply-fixpack.sh --show   the workflow
#
# Run it after apply-cell-workflow.sh, which creates the inventory and the fix
# pack template. The batch names are JVM_BATCHES below, the same as
# jvm_batches in inventories/aix/group_vars/all/45_jvm_batches.yml: change both
# together. Re-runnable: the templates are patched by name, the workflow's
# nodes are rebuilt from this list each time.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
API="${AWX_API:-https://awx.example.internal/api/v2}"
AWX_USER="${AWX_USER:-admin}"
WORKFLOW="${AWX_BATCH_WORKFLOW:-WAS AIX - Fix pack WAS by JVM batch}"
PROJECT="${AWX_PROJECT:-WAS Evolution}"
INVENTORY="${AWX_CELL_INVENTORY:-WAS AIX}"
MACHINE_CRED="${AWX_MACHINE_CRED:-ServeurAIX (ansible)}"
WAS_CRED_TYPE="${AWX_WAS_CRED_TYPE:-WAS administrative user}"
VAULT_CRED="${AWX_VAULT_CRED:-WAS AIX vault}"
FIXPACK_JT="WAS AIX - 2. Fix packs: Installation Manager"
STOP_JT="WAS AIX - JVM stop by batch"
START_JT="WAS AIX - JVM start by batch"
DMGR_JT="WAS AIX - Fix pack: deployment manager"
IHS_JT="WAS AIX - Fix pack: IHS and plugin"
JVM_BATCHES=(512 1024 1536 2048)
COL=ansible_collections/wasevo/websphere/playbooks

say() { printf '\n== %s\n' "$*"; }
ok()  { printf '   ok    %s\n' "$*"; }
note(){ printf '   --    %s\n' "$*"; }
die() { printf '   FAIL  %s\n' "$*" >&2; exit 1; }

# The netrc and the request body live in a private temporary directory made
# by Python, removed on exit - as in apply-cell-workflow.sh.
WORKDIR="$(python3 -c 'import tempfile; print(tempfile.mkdtemp(prefix="awx-"))')"
[ -d "$WORKDIR" ] || die "could not create the temporary directory"
trap 'rm -rf "$WORKDIR"' EXIT
NETRC="$WORKDIR/netrc"
BODY="$WORKDIR/body"

# Authentication as apply-cell-workflow.sh: AWX_TOKEN_FILE, else
# AWX_NETRC_FILE, else AWX_USER's password typed at the prompt.
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
    _host="${API#*://}"; _host="${_host%%/*}"
    ( umask 077
      printf 'machine %s login %s password %s\n' \
          "$_host" "$AWX_USER" "$_awx_pw" > "$NETRC" )
    unset _awx_pw
    AUTH=(--netrc-file "$NETRC")
fi

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

if [ "${1:-}" = "--show" ]; then
    WF_ID="$(id_of workflow_job_templates "$WORKFLOW")"
    [ -n "$WF_ID" ] || die "no workflow named \"$WORKFLOW\" yet"
    api GET "/workflow_job_templates/$WF_ID/workflow_nodes/?page_size=200" | py 'import sys,json
for n in json.load(sys.stdin)["results"]:
    u = n.get("summary_fields", {}).get("unified_job_template") or {}
    print("   node %-5s %-10s %-44s %-22s success -> %s" % (n["id"], n.get("identifier"), u.get("name"),
          json.dumps(n.get("extra_data") or {}), n.get("success_nodes")))'
    exit 0
fi

# ---------------------------------------------------------------------------
say "AWX objects"
# ---------------------------------------------------------------------------
api GET /ping/ >/dev/null || die "cannot reach $API"
ORG_ID="$(api GET "/organizations/" | py 'import sys,json;print(json.load(sys.stdin)["results"][0]["id"])')"
PROJECT_ID="$(id_of projects "$PROJECT")"
[ -n "$PROJECT_ID" ] || die "no project \"$PROJECT\""
INV_ID="$(id_of inventories "$INVENTORY")"
[ -n "$INV_ID" ] || die "no inventory \"$INVENTORY\" - run apply-cell-workflow.sh first"
MACHINE_CRED_ID="$(id_of credentials "$MACHINE_CRED")"
[ -n "$MACHINE_CRED_ID" ] || die "no credential \"$MACHINE_CRED\""
FIXPACK_ID="$(id_of job_templates "$FIXPACK_JT")"
[ -n "$FIXPACK_ID" ] || die "no template \"$FIXPACK_JT\" - run apply-cell-workflow.sh first"
VAULT_CRED_ID="$(id_of credentials "$VAULT_CRED")"
[ -n "$VAULT_CRED_ID" ] || note "no credential \"$VAULT_CRED\" (docs/vault.md): needed only if sudo su - asks a password"
CT_ID="$(id_of credential_types "$WAS_CRED_TYPE")"
WAS_CRED_ID=""
if [ -n "$CT_ID" ]; then
    WAS_CRED_ID="$(api GET "/credentials/?credential_type=$CT_ID" | py 'import sys,json
d=json.load(sys.stdin)
print(d["results"][0]["id"] if d.get("count") else "")')"
fi
[ -n "$WAS_CRED_ID" ] || note "no \"$WAS_CRED_TYPE\" credential: stopServer.sh relies on soap.client.props"
EE_ID="$(api GET "/job_templates/$FIXPACK_ID/" | py 'import sys,json;print(json.load(sys.stdin).get("execution_environment") or "")')"

# The project first: a template naming a playbook pushed after the project's
# last update is refused as "Playbook not found".
UPDATE_ID="$(api POST "/projects/$PROJECT_ID/update/" | py 'import sys,json;print(json.load(sys.stdin).get("id",""))')"
for _ in $(seq 1 60); do
    st="$(api GET "/project_updates/$UPDATE_ID/" | py 'import sys,json;print(json.load(sys.stdin).get("status",""))')"
    case "$st" in successful) break ;; failed|error|canceled) die "project update $st" ;; *) sleep 2 ;; esac
done
ok "project updated"

# ---------------------------------------------------------------------------
say "Job templates"
# ---------------------------------------------------------------------------
attach_cred() {
    local jt="$1" cred="$2"
    if [ -n "$cred" ]; then
        api POST "/job_templates/$jt/credentials/" -d "{\"id\": $cred}" >/dev/null || true
    fi
}
form() {
    local path="$1" spec="$2" label="$3"
    api POST "/$path/survey_spec/" --data-binary "@$spec" >/dev/null || die "could not post the form to $label"
    api PATCH "/$path/" -d '{"survey_enabled": true}' >/dev/null || die "could not enable the form on $label"
    ok "$label: form $(basename "$spec")"
}

# name, playbook, form, extra vars
make_jt() {
    local name="$1" playbook="$2" spec="$3" extra="$4" id
    py 'import json,sys
name, playbook, inv, proj, ee, extra = sys.argv[1:7]
b = {"name": name, "job_type": "run", "inventory": int(inv), "project": int(proj),
     "playbook": playbook, "become_enabled": True, "verbosity": 1, "timeout": 7200,
     "ask_job_type_on_launch": True, "ask_variables_on_launch": True,
     "extra_vars": "---\n%s\n" % extra}
if ee:
    b["execution_environment"] = int(ee)
print(json.dumps(b))' "$name" "$COL/$playbook" "$INV_ID" "$PROJECT_ID" "$EE_ID" "$extra" > "$BODY"
    id="$(upsert job_templates "$name")"
    attach_cred "$id" "$MACHINE_CRED_ID"
    attach_cred "$id" "$VAULT_CRED_ID"
    attach_cred "$id" "$WAS_CRED_ID"
    form "job_templates/$id" "$HERE/surveys/$spec" "$name" >&2
    printf '%s' "$id"
}
STOP_ID="$(make_jt "$STOP_JT" traditional_jvm_stop.yml jvm-batch.json "jvm_hosts: nodeagents")"
START_ID="$(make_jt "$START_JT" traditional_jvm_start.yml jvm-batch.json "jvm_hosts: nodeagents")"
make_jt "$DMGR_JT" traditional_fixpack_dmgr.yml fixpack-target.json "fixpack_dmgr_hosts: dmgr" >/dev/null
make_jt "$IHS_JT" traditional_fixpack_ihs.yml fixpack-target.json "fixpack_ihs_hosts: was_install" >/dev/null
attach_cred "$FIXPACK_ID" "$VAULT_CRED_ID"

# ---------------------------------------------------------------------------
say "Workflow"
# ---------------------------------------------------------------------------
py 'import json,sys
print(json.dumps({"name": sys.argv[1], "organization": int(sys.argv[2]), "inventory": int(sys.argv[3]),
  "description": "WAS on the nodes: stop the JVMs batch by batch and the node agent, apply the WAS "
                 "fix pack (WAS ND and its Java SDK) from the environment configuration, start the node "
                 "agent and the JVMs batch by batch.",
  "ask_variables_on_launch": True}))' "$WORKFLOW" "$ORG_ID" "$INV_ID" > "$BODY"
WF_ID="$(upsert workflow_job_templates "$WORKFLOW")"
form "workflow_job_templates/$WF_ID" "$HERE/surveys/fixpack-target.json" "workflow \"$WORKFLOW\""

# The nodes are rebuilt from the list below every time: the same template
# appears once per batch, so a node cannot be found by its template alone, and
# a rebuild is the one way an earlier version of the list leaves nothing
# behind.
for n in $(api GET "/workflow_job_templates/$WF_ID/workflow_nodes/?page_size=200" \
           | py 'import sys,json;print(" ".join(str(n["id"]) for n in json.load(sys.stdin)["results"]))'); do
    api DELETE "/workflow_job_template_nodes/$n/" >/dev/null || die "could not remove node $n"
done

# extra: the node's own variables, as JSON
add_node() {
    local jt="$1" ident="$2" extra="$3"
    py 'import json,sys
jt, ident, extra = sys.argv[1:4]
b = {"unified_job_template": int(jt), "identifier": ident}
if extra:
    b["extra_data"] = json.loads(extra)
print(json.dumps(b))' "$jt" "$ident" "$extra" > "$BODY"
    api POST "/workflow_job_templates/$WF_ID/workflow_nodes/" --data-binary "@$BODY" \
        | py 'import sys,json
d = json.load(sys.stdin)
if "id" not in d:
    raise SystemExit("refused: " + json.dumps(d)[:300])
print(d["id"])'
}

# The application servers batch by batch, then the node agent: a WAS fix pack
# needs every process of the node stopped. Started again in the reverse
# order: the node agent first, so each JVM finds it.
CHAIN=()
for b in "${JVM_BATCHES[@]}"; do
    CHAIN+=("$(add_node "$STOP_ID" "stop-$b" "{\"jvm_batch\": \"$b\"}")")
done
CHAIN+=("$(add_node "$STOP_ID" "stop-nodeagent" '{"jvm_batch": "NODEAGENT"}')")
CHAIN+=("$(add_node "$FIXPACK_ID" "fixpack-was" '{"imcl_selected_components": ["WAS"]}')")
CHAIN+=("$(add_node "$START_ID" "start-nodeagent" '{"jvm_batch": "NODEAGENT"}')")
for b in "${JVM_BATCHES[@]}"; do
    CHAIN+=("$(add_node "$START_ID" "start-$b" "{\"jvm_batch\": \"$b\"}")")
done
prev=""
for node in "${CHAIN[@]}"; do
    if [ -n "$prev" ]; then
        api POST "/workflow_job_template_nodes/$prev/success_nodes/" -d "{\"id\": $node}" >/dev/null \
            || die "could not chain $prev -> $node"
    fi
    prev="$node"
done
ok "${#CHAIN[@]} nodes: stop ${JVM_BATCHES[*]} NODEAGENT -> fix pack WAS -> start NODEAGENT ${JVM_BATCHES[*]}"

say "Done"
printf '   Launch it in AWX:\n     %s\n' \
    "$(printf '%s' "$API" | sed 's#/api/v2##')/#/templates/workflow_job_template/$WF_ID/details"
