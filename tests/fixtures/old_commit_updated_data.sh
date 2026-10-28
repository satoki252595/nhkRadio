#!/usr/bin/env bash
# Pre-fix "Commit updated data" step from .github/workflows/data-update.yml
# (run 40418054139 #215). It pushes the generated commit without fetching.
# When origin/main has moved, git rejects the push with "fetch first".

set -Eeuo pipefail

git config user.name "github-actions[bot]"
git config user.email "github-actions[bot]@users.noreply.github.com"
git add data/ web/static/data/
git diff --staged --quiet || git commit -m "chore: update programs data"
git push
