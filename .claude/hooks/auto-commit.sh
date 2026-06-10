#!/usr/bin/env bash
# PostToolUse(Write|Edit): commit the file that was just written.
#
# Each Write/Edit becomes its own commit so the branch carries a granular
# history you can open as a PR. Protected branches (main/master) are skipped so
# work always lands on a feature branch. pre-commit runs as normal; if it
# reformats the file and aborts, we re-stage and retry once.
#
# To skip pre-commit on auto-commits (faster, but bypasses the safety net),
# add --no-verify to the `git commit` invocations below.

input="$(cat)"

file="$(printf '%s' "$input" | jq -r '.tool_input.file_path // .tool_response.filePath // empty' 2>/dev/null)"
[ -z "$file" ] && exit 0

root="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
[ -z "$root" ] && exit 0
cd "$root" || exit 0

branch="$(git rev-parse --abbrev-ref HEAD 2>/dev/null)"
case "$branch" in
  main | master)
    printf '{"systemMessage":"⚠ On %s — auto-commit skipped. Create a feature branch so changes can ship as a PR."}\n' "$branch"
    exit 0
    ;;
esac

# Only handle files that live inside this repo.
case "$file" in
  "$root"/*) : ;;
  *) exit 0 ;;
esac

git add -- "$file" 2>/dev/null
if git diff --cached --quiet -- "$file" 2>/dev/null; then
  exit 0 # nothing staged for this file (unchanged or ignored)
fi

rel="${file#"$root"/}"

# Skip pre-commit only when it isn't installed — otherwise the commit aborts with
# "pre-commit not found". When pre-commit IS available, let it run as the safety net.
verify_flag=""
command -v pre-commit >/dev/null 2>&1 || verify_flag="--no-verify"

commit_one() {
  git commit $verify_flag --quiet -m "chore: update ${rel}" -- "$file" >/dev/null 2>/tmp/claude-autocommit.err
}

if commit_one; then
  printf '{"suppressOutput":true}\n'
  exit 0
fi

# pre-commit likely reformatted the file and aborted — re-stage the fixes and retry once.
git add -- "$file" 2>/dev/null
if ! git diff --cached --quiet -- "$file" 2>/dev/null && commit_one; then
  printf '{"suppressOutput":true}\n'
else
  printf '{"systemMessage":"Auto-commit failed for %s — see /tmp/claude-autocommit.err (likely a pre-commit failure that needs a manual fix)."}\n' "$rel"
fi
exit 0
