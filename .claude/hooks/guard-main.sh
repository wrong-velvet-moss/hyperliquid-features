#!/usr/bin/env bash
# PreToolUse(Bash): block `git commit` / `git push` while on main or master.
#
# Defense-in-depth guardrail: every change should land on a feature branch and
# ship as a PR — never directly on the default branch. Denies the tool call and
# tells Claude to branch first.

input="$(cat)"
cmd="$(printf '%s' "$input" | jq -r '.tool_input.command // empty' 2>/dev/null)"
[ -z "$cmd" ] && exit 0

branch="$(git rev-parse --abbrev-ref HEAD 2>/dev/null)"
case "$branch" in
  main | master) : ;;
  *) exit 0 ;; # not on a protected branch — nothing to guard
esac

case "$cmd" in
  *"git commit"* | *"git push"* | *"git "*" commit"* | *"git "*" push"*)
    reason="Blocked: you are on '${branch}'. Do not commit or push to ${branch}. Create a feature branch first (git switch -c <type>/<topic>), commit there, and open a PR."
    jq -nc --arg r "$reason" '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$r}}'
    exit 0
    ;;
esac
exit 0
