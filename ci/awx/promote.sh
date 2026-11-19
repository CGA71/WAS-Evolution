#!/usr/bin/env bash
# Point the AWX project at a released version: the tag ci/release.sh made.
#
#   bash ci/awx/promote.sh                  which version the project runs now
#   bash ci/awx/promote.sh v0.2.0           run v0.2.0 from now on
#   bash ci/awx/promote.sh v0.1.0           back to the previous one - a rollback is a promotion
#   bash ci/awx/promote.sh main --branch    the moving branch, on purpose (a lab AWX only)
#
# AWX runs what its project's "SCM branch/tag/commit" names. On a tag it runs
# a fixed, validated version - what VAL02 was built with is a fact, not a
# guess. On main it runs whatever was pushed last, green pipeline or not.
#
# The project is updated and waited for. If AWX cannot check the tag out (not
# pushed, typo), the previous value is put back and the script fails: the
# project is never left pointing at nothing.
#
# Same authentication and network rules as the other scripts here: see
# README.md in this directory. AWX_PROJECT names the project (default
# "WAS Evolution").

set -euo pipefail

API="${AWX_API:-https://awx.example.internal/api/v2}"
AWX_USER="${AWX_USER:-admin}"
PROJECT="${AWX_PROJECT:-WAS Evolution}"

say() { printf '\n== %s\n' "$*"; }
ok()  { printf '   ok    %s\n' "$*"; }
die() { printf '   FAIL  %s\n' "$*" >&2; exit 1; }

ref="${1:-}"
if [ -n "$ref" ]; then
    if [ "${2:-}" = "--branch" ]; then
        :
    elif ! printf '%s' "$ref" | grep -Eq '^v[0-9]+\.[0-9]+\.[0-9]+$'; then
        die "\"$ref\" is not a version tag (vX.Y.Z). To run a branch on purpose: promote.sh $ref --branch"
    fi
fi

WORKDIR="$(python3 -c 'import tempfile; print(tempfile.mkdtemp(prefix="awx-"))')"
[ -d "$WORKDIR" ] || die "could not create the temporary directory"
trap 'rm -rf "$WORKDIR"' EXIT
NETRC="$WORKDIR/netrc"
BODY="$WORKDIR/body"

if [ -n "${AWX_TOKEN_FILE:-}" ]; then
    [ -r "$AWX_TOKEN_FILE" ] || die "cannot read AWX_TOKEN_FILE ($AWX_TOKEN_FILE)"
    ( umask 077
      printf 'Authorization: Bearer %s\n' "$(tr -d ' \r\n' < "$AWX_TOKEN_FILE")" > "$WORKDIR/auth.header" )
    AUTH=(-H "@$WORKDIR/auth.header")
else
    IFS= read -rsp "AWX password for $AWX_USER: " _awx_pw </dev/tty \
        || die "could not read the AWX password from the terminal"
    printf '\n' >&2
    [ -n "$_awx_pw" ] || die "empty AWX password"
    _host="${API#*://}"; _host="${_host%%/*}"
    ( umask 077
      printf 'machine %s login %s password %s\n' "$_host" "$AWX_USER" "$_awx_pw" > "$NETRC" )
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

api GET /ping/ >/dev/null || die "cannot reach $API"
PROJECT_ID="$(api GET "/projects/?name=$(py 'import sys,urllib.parse;print(urllib.parse.quote(sys.argv[1]))' "$PROJECT")" \
  | py 'import sys,json
for r in json.load(sys.stdin).get("results", []):
    if r["name"] == sys.argv[1]:
        print(r["id"]); break' "$PROJECT")"
[ -n "$PROJECT_ID" ] || die "no project named \"$PROJECT\""

current="$(api GET "/projects/$PROJECT_ID/" | py 'import sys,json;print(json.load(sys.stdin).get("scm_branch") or "")')"
say "$PROJECT (id $PROJECT_ID)"
ok "runs ${current:-the repository default branch}"
[ -n "$ref" ] || exit 0
if [ "$ref" = "$current" ]; then ok "already on $ref"; exit 0; fi

set_branch() {
    py 'import json,sys; print(json.dumps({"scm_branch": sys.argv[1]}))' "$1" > "$BODY"
    api PATCH "/projects/$PROJECT_ID/" --data-binary "@$BODY" >/dev/null
}
update() {
    local id st
    id="$(api POST "/projects/$PROJECT_ID/update/" | py 'import sys,json;print(json.load(sys.stdin).get("id",""))')"
    [ -n "$id" ] || return 1
    for _ in $(seq 1 90); do
        st="$(api GET "/project_updates/$id/" | py 'import sys,json;print(json.load(sys.stdin).get("status",""))')"
        case "$st" in successful) return 0 ;; failed|error|canceled) return 1 ;; *) sleep 2 ;; esac
    done
    return 1
}

set_branch "$ref" || die "could not set the project to $ref"
if update; then
    ok "now runs $ref (was ${current:-the default branch})"
    printf '   --    rollback: bash ci/awx/promote.sh %s\n' "${current:-main --branch}"
else
    set_branch "$current" || true
    update || true
    die "AWX could not check out $ref - is the tag pushed? The project is back on ${current:-the default branch}"
fi
