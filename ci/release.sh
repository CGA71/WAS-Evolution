#!/usr/bin/env bash
# Publish a version of the collection: galaxy.yml carries it, a tag names it,
# AWX runs it (ci/awx/promote.sh).
#
#   bash ci/release.sh 0.2.0             galaxy.yml -> 0.2.0, commit, tag v0.2.0, push both
#   bash ci/release.sh 0.2.0 --no-push   the same, left local
#
# The version in galaxy.yml and the tag are written together, by this script,
# so they cannot disagree; the release-version CI job refuses a tag where they
# do. The tag is made on main, on the commit origin already has - the one its
# pipeline validated - plus the one-line version commit. Check that pipeline
# is green before running this: a tag is what AWX will run.
#
# REMOTE names the remote GitLab builds from (default: origin).

set -euo pipefail

die() { printf 'FAIL  %s\n' "$*" >&2; exit 1; }
ok()  { printf 'ok    %s\n' "$*"; }

version="${1:-}"
push=true
[ "${2:-}" = "--no-push" ] && push=false
[ -n "$version" ] || die "usage: ci/release.sh X.Y.Z [--no-push]"
printf '%s' "$version" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$' \
    || die "\"$version\" is not X.Y.Z (the tag adds the v)"
tag="v$version"
remote="${REMOTE:-origin}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GALAXY="ansible_collections/wasevo/websphere/galaxy.yml"
cd "$ROOT"

# --- where we are ------------------------------------------------------------
[ "$(git rev-parse --abbrev-ref HEAD)" = "main" ] || die "not on main"
[ -z "$(git status --porcelain)" ] || die "uncommitted changes - a version is a commit, not a working tree"
git fetch -q "$remote" main --tags
[ "$(git rev-parse HEAD)" = "$(git rev-parse "$remote/main")" ] \
    || die "main is not $remote/main - push or pull first: the version must be the code the pipeline validated"
if git rev-parse -q --verify "refs/tags/$tag" >/dev/null; then die "$tag already exists"; fi

# --- the version goes up -------------------------------------------------------
current="$(sed -n 's/^version:[[:space:]]*//p' "$GALAXY" | tr -d "\"' ")"
[ -n "$current" ] || die "no version: line in $GALAXY"
if [ "$current" != "$version" ]; then
    highest="$(printf '%s\n%s\n' "$current" "$version" | sort -t. -k1,1n -k2,2n -k3,3n | tail -1)"
    [ "$highest" = "$version" ] || die "$version is below the current $current"
fi
last="$(git tag -l 'v*' | sed 's/^v//' | sort -t. -k1,1n -k2,2n -k3,3n | tail -1)"
if [ -n "$last" ]; then
    highest="$(printf '%s\n%s\n' "$last" "$version" | sort -t. -k1,1n -k2,2n -k3,3n | tail -1)"
    [ "$highest" = "$version" ] || die "$version is below the last tag v$last"
fi

# --- galaxy.yml, the commit, the tag -------------------------------------------
if [ "$current" = "$version" ]; then
    ok "$GALAXY already says $version - nothing to commit"
else
    # No sed -i: its syntax differs between GNU and BSD/AIX.
    sed "s/^version:.*/version: $version/" "$GALAXY" > "$GALAXY.tmp" && mv "$GALAXY.tmp" "$GALAXY"
    git add "$GALAXY"
    git commit -q -m "Release $tag"
    ok "galaxy.yml $current -> $version, committed"
fi
git tag -a "$tag" -m "WAS Evolution $tag"
ok "tagged $tag on $(git rev-parse --short HEAD)"

if $push; then
    # Atomic: main and the tag land together or not at all.
    git push -q --atomic "$remote" main "$tag"
    ok "pushed main and $tag to $remote"
    printf '\nnext: once the %s pipeline is green,  bash ci/awx/promote.sh %s\n' "$tag" "$tag"
else
    printf '\nnot pushed. When ready:  git push --atomic %s main %s\n' "$remote" "$tag"
fi
