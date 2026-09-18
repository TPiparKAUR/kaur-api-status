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

# Outside Actions there is no GITHUB_REF_NAME. Resolving it once here also
# means every git call below names the branch explicitly, which is what keeps
# a push working if HEAD ever ends up detached.
ref="${GITHUB_REF_NAME:-$(git rev-parse --abbrev-ref HEAD)}"

git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

git add -- "$@"
if git diff --cached --quiet; then
  echo "Nothing changed."
  exit 0
fi
git commit -m "$message"

for attempt in 1 2 3 4 5; do
  if git push origin "HEAD:${ref}"; then
    exit 0
  fi
  echo "Push rejected on attempt ${attempt}; rebasing onto ${ref}."

  # Measured 2026-09-18 (run 233): the rebase below hit a content conflict in
  # REPORT.md and docs/data/status.json, `|| true` swallowed it, and the run
  # was left with a .git/rebase-merge directory and a detached HEAD. Every
  # later attempt then failed on *that* ("not currently on a branch",
  # "already a rebase-merge directory") rather than on the race it was meant
  # to survive, so all five attempts were spent and the cycle's checks were
  # discarded. Clearing any half-finished rebase first is what makes the
  # retries independent of each other.
  git rebase --abort >/dev/null 2>&1 || true

  # -X theirs keeps the commit being replayed, which is the right side for the
  # two generated files: REGEN_CMD rebuilds both from the merged log a few
  # lines down, so whichever version survives the rebase is overwritten
  # anyway. It does not affect logs/*.jsonl — the union merge driver in
  # .gitattributes takes precedence over a strategy option, so concurrent
  # appends still combine.
  if ! git pull --rebase -X theirs --autostash origin "${ref}"; then
    echo "Rebase failed on attempt ${attempt}; aborting it and retrying." >&2
    git rebase --abort >/dev/null 2>&1 || true
    sleep $((attempt * 3))
    continue
  fi

  if [ -n "${REGEN_CMD:-}" ]; then
    eval "${REGEN_CMD}"
    git add -- "$@"
    git diff --cached --quiet || git commit --amend --no-edit
  fi
  sleep $((attempt * 3))
done

git rebase --abort >/dev/null 2>&1 || true
echo "Could not push after 5 attempts." >&2
exit 1
