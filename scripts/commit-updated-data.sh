#!/usr/bin/env bash
# Commit generated program data, then rebase it onto the latest origin/main
# before pushing.
#
# data-update checks out main, generates data for a long time, and then
# commits data/ and web/static/data/. If main moves during generation, a
# plain git push is rejected (non-fast-forward / "fetch first"; run
# 40418054139). Fetch and rebase immediately before push. A content conflict
# aborts the rebase and fails the step. A rejected push stays a failure.

set -Eeuo pipefail

export GIT_TERMINAL_PROMPT=0
export GIT_EDITOR=true
export GIT_SEQUENCE_EDITOR=true

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root" || exit 1

git config user.name "github-actions[bot]"
git config user.email "github-actions[bot]@users.noreply.github.com"
git add data/ web/static/data/
git diff --staged --quiet || git commit -m "chore: update programs data"

git fetch origin main
if ! git rebase origin/main; then
  echo "rebase onto origin/main failed; aborting without push" >&2
  git rebase --abort || true
  exit 1
fi
git push
