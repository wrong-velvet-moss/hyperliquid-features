#!/usr/bin/env bash
# Stop hook: ship the current feature branch — commit any leftover tracked
# changes, push, and open a PR if none exists. This is the full-auto counterpart
# to auto-commit.sh (which only makes a per-edit commit). It never runs on
# main/master and never blocks the turn (always exits 0).

root="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
[ -z "$root" ] && exit 0
cd "$root" || exit 0

branch="$(git rev-parse --abbrev-ref HEAD 2>/dev/null)"
case "$branch" in
  main | master | "") exit 0 ;; # only ship feature branches
esac

did=()

# 1. Sweep up any leftover *tracked* modifications the per-edit hook didn't catch
#    (e.g. files changed via Bash). Untracked files are left alone on purpose so
#    new/secret files never get auto-committed.
verify_flag=""
command -v pre-commit >/dev/null 2>&1 || verify_flag="--no-verify"
git add -u 2>/dev/null
if ! git diff --cached --quiet 2>/dev/null; then
  git commit $verify_flag --quiet -m "chore: ship tracked changes" >/dev/null 2>&1 \
    && did+=("committed leftover tracked changes")
fi

# 2. Push — set upstream on the first push, otherwise push only if ahead.
upstream="$(git rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null)"
if [ -z "$upstream" ]; then
  git push -u origin "$branch" >/dev/null 2>&1 && did+=("pushed -u origin ${branch}")
else
  ahead="$(git rev-list --count '@{u}'..HEAD 2>/dev/null || echo 0)"
  if [ "${ahead:-0}" -gt 0 ]; then
    git push >/dev/null 2>&1 && did+=("pushed ${ahead} commit(s)")
  fi
fi

# 3. Open a PR if this branch has none yet (auto-filled from commit history).
if command -v gh >/dev/null 2>&1; then
  if ! gh pr view --json number >/dev/null 2>&1; then
    if gh pr create --fill >/dev/null 2>&1; then
      url="$(gh pr view --json url -q .url 2>/dev/null)"
      did+=("opened PR ${url}")
    fi
  fi
fi

[ ${#did[@]} -eq 0 ] && exit 0

note="🚀 Auto-ship:"
for d in "${did[@]}"; do note="${note} • ${d}"; done
jq -nc --arg s "$note" '{systemMessage:$s}'
exit 0
