#!/usr/bin/env bash
# Commit the given paths and push, rebasing and retrying when another workflow
# pushed in between.
#
# Two scheduled workflows commit to the same branch, so losing a race is normal
# rather than exceptional, and a run that simply gives up throws away work it
# already did — which is how a discovery run that had harvested its endpoints
# ended up writing nothing.
#
# Usage:  [REGEN_CMD="<cmd>"] commit_and_push.sh "<message>" <path>...
#
# REGEN_CMD, if set, re-runs after each rebase. Generated files (the report, the
# dashboard data) are rebuilt from the merged log rather than hand-resolved.
set -euo pipefail

message="$1"
shift

git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

git add -- "$@"
if git diff --cached --quiet; then
  echo "Nothing changed."
  exit 0
fi
git commit -m "$message"

for attempt in 1 2 3 4 5; do
  if git push; then
    exit 0
  fi
  echo "Push rejected on attempt ${attempt}; rebasing onto ${GITHUB_REF_NAME}."
  git pull --rebase --autostash origin "${GITHUB_REF_NAME}" || true
  if [ -n "${REGEN_CMD:-}" ]; then
    eval "${REGEN_CMD}"
    git add -- "$@"
    git diff --cached --quiet || git commit --amend --no-edit
  fi
  sleep $((attempt * 3))
done

echo "Could not push after 5 attempts." >&2
exit 1
