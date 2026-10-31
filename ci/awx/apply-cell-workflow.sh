#!/usr/bin/env bash
# Declare, in AWX, the workflow that builds a WAS cell on the k3s cluster from
# nothing: three virtual machines, the media, Installation Manager and WAS, a
# deployment manager and two federated nodes, a cluster of two members, all
# started, and the console published on the node's address.
#
#   bash ci/awx/apply-cell-workflow.sh            apply
#   bash ci/awx/apply-cell-workflow.sh --show     print the workflow graph
#
# Run it from the k3s node, like apply-templates.sh. It is re-runnable: every
# object is found by name and patched.
#
# A WORKFLOW OF ITS OWN. The install lab workflow builds a cell on one machine
# and then configures it, resource by resource. This one builds a cell across
# three machines and stops at the cluster: no JDBC, no JMS, no security
# change. Separate, so launching one never runs the other's jobs.
#
# WHAT IT HOLDS AND WHERE IT COMES FROM
#
#   Kubernetes credential   the token of ServiceAccount awx-cell-platform,
#                           read from the cluster once the operator has applied
#                           ci/k3s/30-awx-cell-platform.yml - this script never
#                           grants rights on the cluster itself.
#   WAS administrator       user wasadmin, its password generated once into the
#                           Secret awx/was-cell-admin and injected by an AWX
#                           credential. Read it with:
#                             kubectl -n awx get secret was-cell-admin \
#                               -o jsonpath='{.data.password}' | base64 -d
#   Inventory               "WAS cell", sourced from inventories/cell/hosts.yml.
#   Survey                  the same as the lab workflow's (environment,
#                           channel, topology, names), by apply-survey.sh.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
API="${AWX_API:-http://awx.lab.example.com/api/v2}"
WORKFLOW="${AWX_CELL_WORKFLOW:-WAS cell - deployment manager and two federated nodes}"
PROJECT="${AWX_PROJECT:-WAS Evolution}"
INVENTORY="${AWX_CELL_INVENTORY:-WAS cell}"
INVENTORY_FILE="inventories/cell/hosts.yml"
MACHINE_CRED="${AWX_MACHINE_CRED:-WAS lab VM (ansible)}"
WAS_CRED_TYPE="${AWX_WAS_CRED_TYPE:-WAS administrative user}"
WAS_CRED="${AWX_CELL_WAS_CRED:-WAS cell administrator}"
K8S_CRED="${AWX_CELL_K8S_CRED:-k3s API - cell platform}"
WAS_ADMIN_USER="${CELL_WAS_ADMIN_USER:-wasadmin}"
COL=ansible_collections/wasevo/websphere/playbooks

export KUBECONFIG="${KUBECONFIG:-$HOME/.kube/config}"

say() { printf '\n== %s\n' "$*"; }
ok()  { printf '   ok    %s\n' "$*"; }
note(){ printf '   --    %s\n' "$*"; }
die() { printf '   FAIL  %s\n' "$*" >&2; exit 1; }

NETRC="$(mktemp)"
BODY="$(mktemp)"
chmod 600 "$NETRC" "$BODY"
trap 'rm -f "$NETRC" "$BODY"' EXIT

_awx_pw="$(kubectl -n awx get secret awx-admin-password -o jsonpath='{.data.password}' | base64 -d)"
[ -n "$_awx_pw" ] || die "could not read the AWX admin password from the Secret"
printf 'machine %s login admin password %s\n' \
    "$(printf '%s' "$API" | sed -E 's#^https?://([^/]+).*#\1#')" "$_awx_pw" > "$NETRC"
unset _awx_pw

api() {
    local method="$1" path="$2"
    shift 2
    curl -sS --netrc-file "$NETRC" -X "$method" \
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

if [ "${1:-}" = "--show" ]; then
    WF_ID="$(id_of workflow_job_templates "$WORKFLOW")"
    [ -n "$WF_ID" ] || die "no workflow named \"$WORKFLOW\" yet"
    api GET "/workflow_job_templates/$WF_ID/workflow_nodes/?page_size=200" | py 'import sys,json
for n in json.load(sys.stdin)["results"]:
    u = n.get("summary_fields", {}).get("unified_job_template") or {}
    print("   node %-5s %-50s success -> %s" % (n["id"], u.get("name"), n.get("success_nodes")))'
    exit 0
fi

# ---------------------------------------------------------------------------
say "Cluster access for the platform jobs"
# ---------------------------------------------------------------------------
# Granting the jobs rights on the cluster is the operator's act, not this
# script's: kubectl apply -f ci/k3s/30-awx-cell-platform.yml. Without it the
# workflow is declared all the same; the Kubernetes credential is added on the
# next run, once the token exists.
TOKEN="$(kubectl -n awx get secret awx-cell-platform-token -o jsonpath='{.data.token}' 2>/dev/null | base64 -d || true)"
if [ -n "$TOKEN" ]; then
    CA="$(kubectl -n awx get secret awx-cell-platform-token -o jsonpath='{.data.ca\.crt}' | base64 -d)"
    ok "ServiceAccount awx-cell-platform and its token"
else
    note "no token yet: kubectl apply -f ci/k3s/30-awx-cell-platform.yml, then run this again"
    note "jobs 1, 2 and 9 cannot reach the cluster until then"
fi

# ---------------------------------------------------------------------------
say "The WAS administrator"
# ---------------------------------------------------------------------------
if ! kubectl -n awx get secret was-cell-admin >/dev/null 2>&1; then
    kubectl -n awx create secret generic was-cell-admin \
        --from-literal=user="$WAS_ADMIN_USER" \
        --from-literal=password="$(head -c 48 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 20)" >/dev/null
    ok "password generated into Secret awx/was-cell-admin"
else
    ok "Secret awx/was-cell-admin already holds the password - kept"
fi
WAS_PW="$(kubectl -n awx get secret was-cell-admin -o jsonpath='{.data.password}' | base64 -d)"
WAS_USER="$(kubectl -n awx get secret was-cell-admin -o jsonpath='{.data.user}' | base64 -d)"

# ---------------------------------------------------------------------------
say "AWX objects"
# ---------------------------------------------------------------------------
api GET /ping/ >/dev/null || die "cannot reach $API"
ORG_ID="$(api GET "/organizations/" | py 'import sys,json;print(json.load(sys.stdin)["results"][0]["id"])')"
PROJECT_ID="$(id_of projects "$PROJECT")"
[ -n "$PROJECT_ID" ] || die "no project named \"$PROJECT\""
MACHINE_CRED_ID="$(id_of credentials "$MACHINE_CRED")"
[ -n "$MACHINE_CRED_ID" ] || die "no credential named \"$MACHINE_CRED\""
WAS_CT_ID="$(id_of credential_types "$WAS_CRED_TYPE")"
[ -n "$WAS_CT_ID" ] || die "no credential type \"$WAS_CRED_TYPE\" - run apply-templates.sh first"
K8S_CT_ID="$(api GET "/credential_types/?kind=kubernetes" | py 'import sys,json
for c in json.load(sys.stdin)["results"]:
    if c["namespace"] == "kubernetes_bearer_token":
        print(c["id"]); break')"
[ -n "$K8S_CT_ID" ] || die "AWX has no Kubernetes bearer token credential type"
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

py 'import json,sys
print(json.dumps({"name": sys.argv[1], "organization": int(sys.argv[2]),
  "credential_type": int(sys.argv[3]),
  "description": "Token of ServiceAccount awx/awx-cell-platform - ci/k3s/30-awx-cell-platform.yml",
  "inputs": {"host": "https://kubernetes.default.svc", "bearer_token": sys.argv[4],
             "verify_ssl": True, "ssl_ca_cert": sys.argv[5]}}))' \
  "$K8S_CRED" "$ORG_ID" "$K8S_CT_ID" "$TOKEN" "${CA:-}" > "$BODY"
K8S_CRED_ID=""
[ -z "$TOKEN" ] || K8S_CRED_ID="$(upsert credentials "$K8S_CRED")"

py 'import json,sys
print(json.dumps({"name": sys.argv[1], "organization": int(sys.argv[2]),
  "credential_type": int(sys.argv[3]),
  "description": "From Secret awx/was-cell-admin",
  "inputs": {"was_admin_user": sys.argv[4], "was_admin_password": sys.argv[5]}}))' \
  "$WAS_CRED" "$ORG_ID" "$WAS_CT_ID" "$WAS_USER" "$WAS_PW" > "$BODY"
WAS_CRED_ID="$(upsert credentials "$WAS_CRED")"
unset WAS_PW TOKEN

py 'import json,sys
print(json.dumps({"name": sys.argv[1], "organization": int(sys.argv[2]),
  "description": "A deployment manager and two federated nodes on k3s - inventories/cell"}))' \
  "$INVENTORY" "$ORG_ID" > "$BODY"
INV_ID="$(upsert inventories "$INVENTORY")"

py 'import json,sys
print(json.dumps({"name": sys.argv[1] + " from project", "inventory": int(sys.argv[2]),
  "source": "scm", "source_project": int(sys.argv[3]), "source_path": sys.argv[4],
  "overwrite": True, "update_on_launch": True, "execution_environment": int(sys.argv[5])}))' \
  "$INVENTORY" "$INV_ID" "$PROJECT_ID" "$INVENTORY_FILE" "$EE_ID" > "$BODY"
SRC_ID="$(upsert inventory_sources "$INVENTORY from project")"

# ---------------------------------------------------------------------------
say "Job templates"
# ---------------------------------------------------------------------------
# name | playbook | become | kubernetes credential | extra vars
#
# become is off on the jobs that run plays on the controller - the job pod has
# no sudo - and their roles ask for root task by task where the machine needs
# it. lab_hosts and profile_hosts point the reused install and profile
# playbooks at this inventory's machines, and away from the media source.
STEPS=(
  "WAS cell - 1. Machines|$COL/cell_machines.yml|false|k8s|"
  "WAS cell - 2. Media|$COL/cell_media.yml|false|k8s|"
  "WAS cell - 3. Installation Manager|$COL/lab_install_im.yml|true||lab_hosts: was_install"
  "WAS cell - 4. WAS|$COL/lab_install_was.yml|true||lab_hosts: was_install"
  "WAS cell - 5. Profiles: deployment manager, federated nodes|$COL/lab_create_profiles.yml|true||profile_hosts: was_install"
  "WAS cell - 6. Cluster|$COL/traditional_cluster.yml|true||config_dmgr_hosts: dmgr"
  "WAS cell - 7. Cluster members|$COL/traditional_cluster_members.yml|true||config_dmgr_hosts: dmgr"
  "WAS cell - 8. Start|$COL/traditional_start.yml|true||"
  "WAS cell - 9. Console|$COL/cell_console.yml|false|k8s|"
)

JT_IDS=()
for step in "${STEPS[@]}"; do
    IFS='|' read -r name playbook become k8s extra <<<"$step"
    py 'import json,sys
name, playbook, become, extra, inv, proj, ee = sys.argv[1:8]
b = {"name": name, "job_type": "run", "inventory": int(inv), "project": int(proj),
     "playbook": playbook, "execution_environment": int(ee),
     "become_enabled": become == "true", "verbosity": 1, "timeout": 5400,
     "ask_job_type_on_launch": True, "ask_variables_on_launch": True,
     "ask_credential_on_launch": False}
b["extra_vars"] = ("---\n%s\n" % extra.strip()) if extra.strip() else ""
print(json.dumps(b))' "$name" "$playbook" "$become" "$extra" "$INV_ID" "$PROJECT_ID" "$EE_ID" > "$BODY"
    jt="$(upsert job_templates "$name")"
    for cred in "$MACHINE_CRED_ID" "$WAS_CRED_ID"; do
        api POST "/job_templates/$jt/credentials/" -d "{\"id\": $cred}" >/dev/null || true
    done
    if [ "$k8s" = "k8s" ] && [ -n "$K8S_CRED_ID" ]; then
        api POST "/job_templates/$jt/credentials/" -d "{\"id\": $K8S_CRED_ID}" >/dev/null || true
    fi
    JT_IDS+=("$jt")
done

# ---------------------------------------------------------------------------
say "Workflow"
# ---------------------------------------------------------------------------
py 'import json,sys
print(json.dumps({"name": sys.argv[1], "organization": int(sys.argv[2]), "inventory": int(sys.argv[3]),
  "description": "Three KubeVirt machines, WAS, a deployment manager, two federated nodes, "
                 "a cluster of two members, started; the console on the node address.",
  "ask_variables_on_launch": True}))' "$WORKFLOW" "$ORG_ID" "$INV_ID" > "$BODY"
WF_ID="$(upsert workflow_job_templates "$WORKFLOW")"

prev=""
for jt in "${JT_IDS[@]}"; do
    node="$(api GET "/workflow_job_templates/$WF_ID/workflow_nodes/?page_size=200" | py 'import sys,json
for n in json.load(sys.stdin)["results"]:
    if str((n.get("summary_fields", {}).get("unified_job_template") or {}).get("id")) == sys.argv[1]:
        print(n["id"]); break' "$jt")"
    if [ -z "$node" ]; then
        node="$(api POST "/workflow_job_templates/$WF_ID/workflow_nodes/" -d "{\"unified_job_template\": $jt}" \
                | py 'import sys,json;print(json.load(sys.stdin).get("id",""))')"
        [ -n "$node" ] || die "could not add template $jt to the workflow"
        ok "node $node for template $jt"
    else
        ok "template $jt is node $node"
    fi
    if [ -n "$prev" ]; then
        api POST "/workflow_job_template_nodes/$prev/success_nodes/" -d "{\"id\": $node}" >/dev/null || true
    fi
    prev="$node"
done

say "Survey"
AWX_WORKFLOW="$WORKFLOW" bash "$HERE/apply-survey.sh" | tail -4

say "Done"
printf '   Launch it in AWX:\n     %s\n' \
    "$(printf '%s' "$API" | sed 's#/api/v2##')/#/templates/workflow_job_template/$WF_ID/details"
