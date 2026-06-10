#!/usr/bin/env bash
# Stop hook: nudge to commit, push, and open a PR when work is left unshipped.
#
# Informational only (systemMessage) — never blocks. Covers the gaps the
# auto-commit hook can't: manual/Bash edits that weren't committed, an unpushed
# branch, or a pushed branch with no PR yet. The network (gh) check only runs
# when the tree is clean and fully pushed, so the only thing left is the PR.

root="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
[ -z "$root" ] && exit 0
cd "$root" || exit 0

branch="$(git rev-parse --abbrev-ref HEAD 2>/dev/null)"
dirty="$(git status --porcelain 2>/dev/null)"
msgs=()

[ -n "$dirty" ] && msgs+=("uncommitted changes — stage & commit them")

case "$branch" in
  main | master)
    msgs+=("on ${branch} — branch before changing code")
    ;;
  "") : ;;
  *)
    upstream="$(git rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null)"
    if [ -z "$upstream" ]; then
      msgs+=("'${branch}' has no upstream — git push -u origin ${branch}")
    else
      ahead="$(git rev-list --count '@{u}'..HEAD 2>/dev/null || echo 0)"
      if [ "${ahead:-0}" -gt 0 ]; then
        msgs+=("${ahead} commit(s) unpushed — git push")
      elif [ -z "$dirty" ] && command -v gh >/dev/null 2>&1; then
        pr="$(gh pr view --json number -q .number 2>/dev/null)"
        [ -z "$pr" ] && msgs+=("no open PR for '${branch}' — gh pr create")
      fi
    fi
    ;;
esac

[ ${#msgs[@]} -eq 0 ] && exit 0

note="📦 Ship reminder:"
for m in "${msgs[@]}"; do note="${note} • ${m}"; done
jq -nc --arg s "$note" '{systemMessage:$s}'
exit 0
