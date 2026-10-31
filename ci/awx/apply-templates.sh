#!/usr/bin/env bash
# Create, in AWX, the job templates that build a cell, and wire them into the
# install workflow in order.
#
#   bash ci/awx/apply-templates.sh            apply
#   bash ci/awx/apply-templates.sh --show     print the graph as it is today
#
# Run it from the k3s node, like apply-survey.sh. The admin password is read
# from the Secret the operator generated and never appears in an argument, an
# environment variable or this repository.
#
# WHY THIS IS A SCRIPT. The templates were created by hand in the UI, which is
# why three of them existed and the three that build a cell did not. A job
# template is configuration: which playbook, which inventory, which credential,
# whether Job type is selectable. Clicking it means nobody can tell what AWX is
# supposed to hold, and a rebuilt AWX holds something else. This script is the
# answer to "what is in AWX", and it is re-runnable: it finds each object by
# name and patches it rather than creating a second one.
#
# ONE JOB TEMPLATE PER ROLE. Each step of the build is separately launchable,
# because replaying one step after a change has to cost one wsadmin session
# rather than the whole chain. The workflow runs them in order; a job template
# run on its own does the same work for that step alone. See README section 18.
#
# WHAT IT DOES NOT DO. It creates no credential carrying a secret. The WAS
# administrative password is typed once into AWX by a human - this script only
# creates the credential TYPE that carries it, so that the password reaches the
# playbook as an injected extra var and never as a template variable, which is
# plain text anyone with read access can see.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
API="${AWX_API:-http://awx.lab.example.com/api/v2}"
WORKFLOW="${AWX_WORKFLOW:-WAS lab - install WAS for Developers}"
PROJECT="${AWX_PROJECT:-WAS Evolution}"
INVENTORY="${AWX_INVENTORY:-WAS install lab}"
MACHINE_CRED="${AWX_MACHINE_CRED:-WAS lab VM (ansible)}"
WAS_CRED_TYPE="${AWX_WAS_CRED_TYPE:-WAS administrative user}"
COL=ansible_collections/wasevo/websphere/playbooks

export KUBECONFIG="${KUBECONFIG:-$HOME/.kube/config}"

say() { printf '\n== %s\n' "$*"; }
ok()  { printf '   ok    %s\n' "$*"; }
note(){ printf '   --    %s\n' "$*"; }
die() { printf '   FAIL  %s\n' "$*" >&2; exit 1; }

# Same credential handling as apply-survey.sh: a 0600 netrc, removed on exit,
# so the password never lands in this host's process list.
NETRC="$(mktemp)"
chmod 600 "$NETRC"
trap 'rm -f "$NETRC"' EXIT

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

# Look an object up by exact name. Returns its id, or nothing.
id_of() {
    local kind="$1" name="$2"
    api GET "/$kind/?name=$(py 'import sys,urllib.parse;print(urllib.parse.quote(sys.argv[1]))' "$name")" \
      | py 'import sys,json
d=json.load(sys.stdin)
for r in d.get("results", []):
    if r["name"] == sys.argv[1]:
        print(r["id"]); break' "$name"
}

say "AWX"
api GET /ping/ >/dev/null || die "cannot reach $API"
ok "$API reachable"

WF_ID="$(id_of workflow_job_templates "$WORKFLOW")"
[ -n "$WF_ID" ] || die "no workflow named \"$WORKFLOW\""
PROJECT_ID="$(id_of projects "$PROJECT")"
[ -n "$PROJECT_ID" ] || die "no project named \"$PROJECT\""
INV_ID="$(id_of inventories "$INVENTORY")"
[ -n "$INV_ID" ] || die "no inventory named \"$INVENTORY\""
MACHINE_CRED_ID="$(id_of credentials "$MACHINE_CRED")"
[ -n "$MACHINE_CRED_ID" ] || die "no credential named \"$MACHINE_CRED\""
ok "workflow $WF_ID, project $PROJECT_ID, inventory $INV_ID, machine credential $MACHINE_CRED_ID"

# ---------------------------------------------------------------------------
# Sync the project first
# ---------------------------------------------------------------------------
# AWX validates `playbook` against the files of the project's LAST SUCCESSFUL
# UPDATE, not against the repository. A template naming a playbook that was
# pushed after that update is refused with "Playbook not found for project." -
# which reads like a path typo and is not one.
#
# So the project is updated here and waited on. This is also what a workflow
# node would do at launch, but the refusal above happens while this script
# builds the templates, long before any launch.
say "Project"
UPDATE_ID="$(api POST "/projects/$PROJECT_ID/update/" \
             | py 'import sys,json;print(json.load(sys.stdin).get("id",""))')"
if [ -z "$UPDATE_ID" ]; then
    note "the project could not be updated from here; using the files it has"
else
    for _ in $(seq 1 60); do
        status="$(api GET "/project_updates/$UPDATE_ID/" \
                  | py 'import sys,json;print(json.load(sys.stdin).get("status",""))')"
        case "$status" in
            successful) ok "project updated to the current commit"; break ;;
            failed|error|canceled)
                die "the project update ended as $status - check the project's SCM settings" ;;
            *) sleep 2 ;;
        esac
    done
    [ "$status" = "successful" ] || die "the project update did not finish in 120s (status $status)"
    api GET "/projects/$PROJECT_ID/" | py 'import sys,json
d = json.load(sys.stdin)
print("   --    revision %s" % (d.get("scm_revision") or "?")[:12])'
fi

# The Execution Environment the existing templates use. Taken from the
# workflow's own templates rather than hardcoded, so this script does not
# decide the EE - whoever set up AWX did.
EE_ID="$(api GET "/job_templates/?page_size=200" | py 'import sys,json
for t in json.load(sys.stdin)["results"]:
    if t.get("execution_environment"):
        print(t["execution_environment"]); break')"
[ -n "$EE_ID" ] || die "could not work out which Execution Environment to use"
ok "execution environment $EE_ID"

# ---------------------------------------------------------------------------
# The steps that build a cell, in the order a cell needs them
# ---------------------------------------------------------------------------
# name | playbook | extra vars
#
# config_dmgr_hosts=dmgr is what lets the cluster playbooks run on the LAB.
# Their default host pattern is the intersection of an environment group and
# the deployment manager group, because the environment is a launch input; the
# lab declares no environment group on purpose - the same VM is built as any
# environment - so the pattern is overridden here, exactly as the profile
# playbook is already overridden for the same reason.
STEPS=(
  "WAS lab - 5. Create the profiles|$COL/lab_create_profiles.yml|"
  "WAS lab - 6. Create the cluster|$COL/traditional_cluster.yml|config_dmgr_hosts: dmgr"
  "WAS lab - 7. Create the application servers|$COL/traditional_cluster_members.yml|config_dmgr_hosts: dmgr"
  "WAS lab - 8. J2C authentication aliases|$COL/traditional_j2c.yml|config_dmgr_hosts: dmgr"
  "WAS lab - 9. JDBC providers and datasources|$COL/traditional_jdbc.yml|config_dmgr_hosts: dmgr"
  "WAS lab - 10. Shared libraries|$COL/traditional_shared_libraries.yml|config_dmgr_hosts: dmgr"
  "WAS lab - 11. Service integration buses|$COL/traditional_sibus.yml|config_dmgr_hosts: dmgr"
  "WAS lab - 12. JMS resources|$COL/traditional_jms.yml|config_dmgr_hosts: dmgr"
  "WAS lab - 13. Transaction service and peer recovery|$COL/traditional_transactions.yml|config_dmgr_hosts: dmgr"
  "WAS lab - 14. EJB container and timers|$COL/traditional_ejb_container.yml|config_dmgr_hosts: dmgr"
  "WAS lab - 15. CDI|$COL/traditional_cdi.yml|config_dmgr_hosts: dmgr"
  "WAS lab - 16. JPA level and defaults|$COL/traditional_jpa.yml|config_dmgr_hosts: dmgr"
)

# ---------------------------------------------------------------------------
# The credential type for the WAS administrator
# ---------------------------------------------------------------------------
# The profile, cluster and member roles all need was_admin_user and
# was_admin_password, and they default to empty and refuse clearly rather than
# shipping "wsadmin"/"wsadmin" the way the source repository did.
#
# A credential type is how that password reaches a playbook without being
# stored in the clear: AWX injects it as an extra var at launch, keeps it
# encrypted at rest and masks it in the output. Putting it in a template's
# extra_vars instead would put it in plain text, readable by anyone who can
# view the template.
say "Credential type"
CT_ID="$(id_of credential_types "$WAS_CRED_TYPE")"
CT_BODY="$(py '
import json
print(json.dumps({
    "name": __import__("sys").argv[1],
    "description": "The WAS cell administrator. Injected as extra vars, so it "
                   "never appears in a job template or a log.",
    "kind": "cloud",
    "inputs": {
        "fields": [
            {"id": "was_admin_user", "label": "Administrative user",
             "type": "string", "help_text": "The deployment manager administrator, not a local account."},
            {"id": "was_admin_password", "label": "Password",
             "type": "string", "secret": True},
        ],
        "required": ["was_admin_user", "was_admin_password"],
    },
    "injectors": {
        "extra_vars": {
            "was_admin_user": "{{ was_admin_user }}",
            "was_admin_password": "{{ was_admin_password }}",
        }
    },
}))' "$WAS_CRED_TYPE")"

if [ "${1:-}" != "--show" ]; then
    if [ -n "$CT_ID" ]; then
        api PATCH "/credential_types/$CT_ID/" -d "$CT_BODY" >/dev/null \
            || die "could not update the credential type"
        ok "\"$WAS_CRED_TYPE\" updated (id $CT_ID)"
    else
        CT_ID="$(api POST "/credential_types/" -d "$CT_BODY" \
                 | py 'import sys,json;print(json.load(sys.stdin).get("id",""))')"
        [ -n "$CT_ID" ] || die "could not create the credential type"
        ok "\"$WAS_CRED_TYPE\" created (id $CT_ID)"
    fi
fi

# Is there a credential OF that type yet? One cannot be created here: it holds
# a password, and a password does not come from a repository.
WAS_CRED_ID="$(api GET "/credentials/?credential_type=$CT_ID" | py 'import sys,json
d=json.load(sys.stdin)
print(d["results"][0]["id"] if d.get("count") else "")')"
if [ -n "$WAS_CRED_ID" ]; then
    ok "a credential of that type exists (id $WAS_CRED_ID) and will be attached"
else
    note "no credential of that type yet. Create one in AWX - Resources,"
    note "Credentials, type \"$WAS_CRED_TYPE\" - and re-run this script to"
    note "attach it. Until then the three templates ask for a credential at"
    note "launch, so a run is still possible by picking it in the dialog."
fi

# ---------------------------------------------------------------------------
# Show
# ---------------------------------------------------------------------------
if [ "${1:-}" = "--show" ]; then
    say "The workflow graph today"
    api GET "/workflow_job_templates/$WF_ID/workflow_nodes/?page_size=200" | py 'import sys,json
for n in json.load(sys.stdin)["results"]:
    u = n.get("summary_fields", {}).get("unified_job_template") or {}
    print("   node %-5s %-45s success -> %s" % (n["id"], u.get("name"), n.get("success_nodes")))'
    say "The job templates"
    api GET "/job_templates/?page_size=200" | py 'import sys,json
for t in json.load(sys.stdin)["results"]:
    print("   id %-4s %-45s survey=%-5s job_type_prompt=%-5s" % (
        t["id"], t["name"], t["survey_enabled"], t["ask_job_type_on_launch"]))
    print("        playbook %s" % t["playbook"])
    print("        credentials: %s" % ", ".join(
        c["name"] for c in t["summary_fields"].get("credentials", [])))'
    exit 0
fi

# ---------------------------------------------------------------------------
# Apply: one job template per step
# ---------------------------------------------------------------------------
say "Job templates"

JT_IDS=()
for step in "${STEPS[@]}"; do
    name="${step%%|*}"
    rest="${step#*|}"
    playbook="${rest%%|*}"
    extra="${rest#*|}"

    body="$(py '
import json, sys
name, playbook, extra, inv, proj, ee = sys.argv[1:7]
body = {
    "name": name,
    "job_type": "run",
    "inventory": int(inv),
    "project": int(proj),
    "playbook": playbook,
    "execution_environment": int(ee),
    "become_enabled": True,
    "verbosity": 1,
    "timeout": 5400,
    # Simulating a run is a check run, so Job type has to be selectable. The
    # templates created by hand shipped with this false, which is why the only
    # way to rehearse an install was to perform it.
    "ask_job_type_on_launch": True,
    "ask_variables_on_launch": True,
    # Until a WAS administrative credential exists, the operator picks one at
    # launch. Once it exists this script attaches it and the prompt is just a
    # way to override it.
    "ask_credential_on_launch": True,
}
if extra.strip():
    body["extra_vars"] = "---\n%s\n" % extra.strip()
print(json.dumps(body))' "$name" "$playbook" "$extra" "$INV_ID" "$PROJECT_ID" "$EE_ID")"

    jt_id="$(id_of job_templates "$name")"
    if [ -n "$jt_id" ]; then
        api PATCH "/job_templates/$jt_id/" -d "$body" >/dev/null \
            || die "could not update \"$name\""
        ok "updated  $name (id $jt_id)"
    else
        jt_id="$(api POST "/job_templates/" -d "$body" \
                 | py 'import sys,json
d = json.load(sys.stdin)
if "id" not in d:
    print("", end="")
    raise SystemExit(json.dumps(d)[:400])
print(d["id"])')"
        [ -n "$jt_id" ] || die "could not create \"$name\""
        ok "created  $name (id $jt_id)"
    fi

    # Credentials are a sub-collection, not a field: they are attached, and
    # attaching one that is already attached is accepted.
    api POST "/job_templates/$jt_id/credentials/" \
        -d "{\"id\": $MACHINE_CRED_ID}" >/dev/null || true
    if [ -n "$WAS_CRED_ID" ]; then
        api POST "/job_templates/$jt_id/credentials/" \
            -d "{\"id\": $WAS_CRED_ID}" >/dev/null || true
    fi
    JT_IDS+=("$jt_id")
done

# ---------------------------------------------------------------------------
# Wire them into the workflow, in order, after whatever is last today
# ---------------------------------------------------------------------------
# Appended rather than inserted: the install nodes come first because a profile
# needs a product, and a cluster needs a profile. Each node runs on the SUCCESS
# of the one before, so a failed install never reaches the profiles.
say "Workflow"

for jt_id in "${JT_IDS[@]}"; do
    existing="$(api GET "/workflow_job_templates/$WF_ID/workflow_nodes/?page_size=200" | py 'import sys,json
for n in json.load(sys.stdin)["results"]:
    u = n.get("summary_fields", {}).get("unified_job_template") or {}
    if str(u.get("id")) == sys.argv[1]:
        print(n["id"]); break' "$jt_id")"
    if [ -n "$existing" ]; then
        ok "template $jt_id is already node $existing in the graph"
        continue
    fi

    # The leaf: the node nothing follows. That is where the next step goes.
    leaf="$(api GET "/workflow_job_templates/$WF_ID/workflow_nodes/?page_size=200" | py 'import sys,json
nodes = json.load(sys.stdin)["results"]
for n in nodes:
    if not n.get("success_nodes") and not n.get("always_nodes"):
        print(n["id"]); break')"

    new_node="$(api POST "/workflow_job_templates/$WF_ID/workflow_nodes/" \
        -d "{\"unified_job_template\": $jt_id}" \
        | py 'import sys,json;print(json.load(sys.stdin).get("id",""))')"
    [ -n "$new_node" ] || die "could not add a workflow node for template $jt_id"

    if [ -n "$leaf" ]; then
        api POST "/workflow_job_template_nodes/$leaf/success_nodes/" \
            -d "{\"id\": $new_node}" >/dev/null \
            || die "could not chain node $new_node after node $leaf"
        ok "node $new_node added, runs on the success of node $leaf"
    else
        ok "node $new_node added as the first node"
    fi
done

say "Done"
printf '   The survey is attached by the other script, which reads the graph:\n\n'
printf '     bash %s/apply-survey.sh\n\n' "$(dirname "$HERE")/awx"
printf '   Then check the workflow at:\n\n     %s\n\n' \
    "$(printf '%s' "$API" | sed 's#/api/v2##')/#/templates/workflow_job_template/$WF_ID/visualizer"
