#!/usr/bin/env bash
# Create, in AWX, the certificate job templates of ONE organisation, and the
# daily schedule that keeps its certificate inventory fresh.
#
#   AWX_ORGANIZATION="Client A" AWX_INVENTORY="Client A - WAS" \
#       bash ci/awx/apply-certificates.sh
#
#   AWX_ORGANIZATION=Default AWX_PORTAL_INVENTORY="WAS cell lab" \
#       bash ci/awx/apply-certificates.sh            also the portal template
#
#   bash ci/awx/apply-certificates.sh --show         what the organisation holds
#
# Run it from the k3s node, like the other scripts here: the admin password is
# read from the Secret the operator generated and never appears in an argument,
# an environment variable or this repository.
#
# ONE ORGANISATION PER CLIENT. AWX's organisations are the tenants: a client's
# users see that organisation's inventories, jobs and job artifacts and nothing
# else. The certificate portal reads AWX with the viewer's own session, so this
# separation is the portal's too - there is no second rights model to keep in
# step. Run this script once per organisation.
#
# THE PORTAL FINDS THESE TEMPLATES BY PLAYBOOK, not by name: a template whose
# playbook is traditional_certificates.yml is an inventory, one whose playbook
# is traditional_certificate_renewal.yml is a renewal. The names below are only
# what an operator reads.
#
# WHAT IT DOES NOT DO. It creates no credential carrying a secret. The WAS
# administrative credential of each organisation is typed into AWX by a human,
# with the type apply-templates.sh creates; this script attaches it when it
# exists.

set -euo pipefail

API="${AWX_API:-http://awx.lab.example.com/api/v2}"
ORGANIZATION="${AWX_ORGANIZATION:-Default}"
PROJECT="${AWX_PROJECT:-WAS Evolution}"
INVENTORY="${AWX_INVENTORY:-}"
PORTAL_INVENTORY="${AWX_PORTAL_INVENTORY:-}"
MACHINE_CRED="${AWX_MACHINE_CRED:-WAS lab VM (ansible)}"
WAS_CRED_TYPE="${AWX_WAS_CRED_TYPE:-WAS administrative user}"
# Only for an inventory that declares no environment group, like the lab: the
# deployment manager group to run on. A client inventory leaves it empty and
# the portal passes the cell's was_environment at launch.
DMGR_HOSTS="${AWX_DMGR_HOSTS:-}"
# The daily inventory, in the AWX host's time zone.
SCHEDULE_RRULE="${AWX_CERT_RRULE:-DTSTART;TZID=Europe/Paris:20261116T060000 RRULE:FREQ=DAILY;INTERVAL=1}"
COL=ansible_collections/wasevo/websphere/playbooks

export KUBECONFIG="${KUBECONFIG:-$HOME/.kube/config}"

say() { printf '\n== %s\n' "$*"; }
ok()  { printf '   ok    %s\n' "$*"; }
note(){ printf '   --    %s\n' "$*"; }
die() { printf '   FAIL  %s\n' "$*" >&2; exit 1; }

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

q() { py 'import sys,urllib.parse;print(urllib.parse.quote(sys.argv[1]))' "$1"; }

# Look an object up by exact name, optionally within one organisation: two
# clients each have a "Certificates - renew", and they are not the same one.
id_of() {
    local kind="$1" name="$2" org="${3:-}"
    local filter="name=$(q "$name")"
    [ -n "$org" ] && filter="$filter&organization=$org"
    api GET "/$kind/?$filter" | py 'import sys,json
d=json.load(sys.stdin)
for r in d.get("results", []):
    if r["name"] == sys.argv[1]:
        print(r["id"]); break' "$name"
}

new_id() { py 'import sys,json
d = json.load(sys.stdin)
if "id" not in d:
    raise SystemExit(json.dumps(d)[:400])
print(d["id"])'; }

say "AWX"
api GET /ping/ >/dev/null || die "cannot reach $API"
ok "$API reachable"

ORG_ID="$(id_of organizations "$ORGANIZATION")"
[ -n "$ORG_ID" ] || die "no organisation named \"$ORGANIZATION\" - create the client's organisation first"
ok "organisation \"$ORGANIZATION\" (id $ORG_ID)"

# ---------------------------------------------------------------------------
# Show
# ---------------------------------------------------------------------------
if [ "${1:-}" = "--show" ]; then
    say "Certificate templates of \"$ORGANIZATION\""
    api GET "/job_templates/?organization=$ORG_ID&playbook__contains=certificate&page_size=200" | py 'import sys,json
for t in json.load(sys.stdin)["results"]:
    s = t["summary_fields"]
    print("   id %-4s %-28s inventory=%s" % (t["id"], t["name"], (s.get("inventory") or {}).get("name")))
    print("        playbook %s" % t["playbook"])
    print("        credentials: %s" % ", ".join(c["name"] for c in s.get("credentials", [])))'
    exit 0
fi

[ -n "$INVENTORY" ] || [ -n "$PORTAL_INVENTORY" ] \
    || die "set AWX_INVENTORY (the client's WAS inventory) and/or AWX_PORTAL_INVENTORY (the k3s node)"

PROJECT_ID="$(id_of projects "$PROJECT")"
[ -n "$PROJECT_ID" ] || die "no project named \"$PROJECT\""
MACHINE_CRED_ID="$(id_of credentials "$MACHINE_CRED")"
[ -n "$MACHINE_CRED_ID" ] || die "no credential named \"$MACHINE_CRED\""

# Same Execution Environment as the templates already there: whoever set up AWX
# decided it, not this script.
EE_ID="$(api GET "/job_templates/?page_size=200" | py 'import sys,json
for t in json.load(sys.stdin)["results"]:
    if t.get("execution_environment"):
        print(t["execution_environment"]); break')"
[ -n "$EE_ID" ] || die "could not work out which Execution Environment to use"
ok "project $PROJECT_ID, machine credential $MACHINE_CRED_ID, execution environment $EE_ID"

# The organisation's WAS administrator, if a human has created it yet.
CT_ID="$(id_of credential_types "$WAS_CRED_TYPE")"
WAS_CRED_ID=""
if [ -n "$CT_ID" ]; then
    WAS_CRED_ID="$(api GET "/credentials/?credential_type=$CT_ID&organization=$ORG_ID" | py 'import sys,json
d=json.load(sys.stdin)
print(d["results"][0]["id"] if d.get("count") else "")')"
fi

# Create or patch one template; prints its id.
apply_jt() {
    local name="$1" playbook="$2" inv_id="$3" extra="$4" ask_inventory="$5"
    local body jt_id
    body="$(py '
import json, sys
name, playbook, inv, proj, ee, org, extra, ask_inv = sys.argv[1:9]
body = {
    "name": name,
    "organization": int(org),
    "job_type": "run",
    "inventory": int(inv),
    "project": int(proj),
    "playbook": playbook,
    "execution_environment": int(ee),
    "become_enabled": True,
    "verbosity": 1,
    "timeout": 3600,
    "ask_job_type_on_launch": True,
    # The portal launches with the cell to act on and, for a renewal, the
    # certificate: both come as launch-time extra vars.
    "ask_variables_on_launch": True,
    "ask_inventory_on_launch": ask_inv == "yes",
    "ask_credential_on_launch": True,
    "extra_vars": ("---\n%s\n" % extra.strip()) if extra.strip() else "",
}
print(json.dumps(body))' "$name" "$playbook" "$inv_id" "$PROJECT_ID" "$EE_ID" "$ORG_ID" "$extra" "$ask_inventory")"

    jt_id="$(id_of job_templates "$name" "$ORG_ID")"
    if [ -n "$jt_id" ]; then
        api PATCH "/job_templates/$jt_id/" -d "$body" >/dev/null || die "could not update \"$name\""
        ok "updated  $name (id $jt_id)" >&2
    else
        jt_id="$(api POST "/job_templates/" -d "$body" | new_id)" || die "could not create \"$name\""
        ok "created  $name (id $jt_id)" >&2
    fi
    api POST "/job_templates/$jt_id/credentials/" -d "{\"id\": $MACHINE_CRED_ID}" >/dev/null || true
    printf '%s' "$jt_id"
}

# ---------------------------------------------------------------------------
# Inventory and renewal, on the client's deployment managers
# ---------------------------------------------------------------------------
if [ -n "$INVENTORY" ]; then
    say "Certificate templates"
    INV_ID="$(id_of inventories "$INVENTORY" "$ORG_ID")"
    [ -n "$INV_ID" ] || die "no inventory named \"$INVENTORY\" in \"$ORGANIZATION\""
    EXTRA=""
    [ -n "$DMGR_HOSTS" ] && EXTRA="config_dmgr_hosts: $DMGR_HOSTS"

    INV_JT="$(apply_jt "Certificates - inventory" "$COL/traditional_certificates.yml" "$INV_ID" "$EXTRA" yes)"
    REN_JT="$(apply_jt "Certificates - renew" "$COL/traditional_certificate_renewal.yml" "$INV_ID" "$EXTRA" yes)"

    if [ -n "$WAS_CRED_ID" ]; then
        for jt in "$INV_JT" "$REN_JT"; do
            api POST "/job_templates/$jt/credentials/" -d "{\"id\": $WAS_CRED_ID}" >/dev/null || true
        done
        ok "WAS administrative credential $WAS_CRED_ID attached"
    else
        note "no \"$WAS_CRED_TYPE\" credential in \"$ORGANIZATION\" yet: create it,"
        note "then re-run this script to attach it (until then: pick it at launch)"
    fi

    # Daily, so the portal is never older than a day even if nobody opens it.
    say "Schedule"
    SCHED_NAME="Certificates - daily inventory"
    SCHED_BODY="$(py 'import json,sys;print(json.dumps({"name": sys.argv[1], "rrule": sys.argv[2], "enabled": True}))' \
                  "$SCHED_NAME" "$SCHEDULE_RRULE")"
    SCHED_ID="$(api GET "/job_templates/$INV_JT/schedules/?name=$(q "$SCHED_NAME")" | py 'import sys,json
d=json.load(sys.stdin)
print(d["results"][0]["id"] if d.get("count") else "")')"
    if [ -n "$SCHED_ID" ]; then
        api PATCH "/schedules/$SCHED_ID/" -d "$SCHED_BODY" >/dev/null || die "could not update the schedule"
        ok "updated  $SCHED_NAME (id $SCHED_ID)"
    else
        SCHED_ID="$(api POST "/job_templates/$INV_JT/schedules/" -d "$SCHED_BODY" | new_id)" \
            || die "could not create the schedule"
        ok "created  $SCHED_NAME (id $SCHED_ID)"
    fi
fi

# ---------------------------------------------------------------------------
# The portal, on the k3s node - one per AWX, not per client
# ---------------------------------------------------------------------------
if [ -n "$PORTAL_INVENTORY" ]; then
    say "Portal template"
    PINV_ID="$(id_of inventories "$PORTAL_INVENTORY")"
    [ -n "$PINV_ID" ] || die "no inventory named \"$PORTAL_INVENTORY\""
    PORTAL_JT="$(apply_jt "Certificates - portal" "$COL/platform_certificate_portal.yml" "$PINV_ID" "" no)"
    note "launch it once (id $PORTAL_JT), then open $(printf '%s' "$API" | sed 's#/api/v2##')/wasevo/certificates/"
fi

say "Done"
printf '   A user of "%s" sees its cells once they have Read on its inventory\n' "$ORGANIZATION"
printf '   and the inventory template, and Execute on the renewal template.\n\n'
