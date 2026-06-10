# Claude Code workflow hooks

These hooks enforce a **commit-per-change, ship-as-PR** workflow. They live in
`settings.json` (committed, so the whole team gets them) and call scripts in
`hooks/`.

| Event | Script | What it does |
|-------|--------|--------------|
| `PostToolUse` (Write\|Edit) | `auto-commit.sh` | Commits the just-written file. Each edit → one commit. Skips `main`/`master`. |
| `PreToolUse` (Bash) | `guard-main.sh` | Blocks `git commit` / `git push` while on `main`/`master`. |
| `Stop` | `remind-ship.sh` | Nudges to commit, push, and open a PR when work is left unshipped. |

## How it flows

1. Branch off `main` (`git switch -c <type>/<topic>`). The guard blocks work on `main`.
2. Every Write/Edit is auto-committed to the feature branch as its own commit.
3. When Claude stops, the Stop hook reminds you to push and `gh pr create`.

## Notes

- **Auto-commits run `pre-commit`.** If pre-commit reformats the file and aborts,
  the hook re-stages and retries once. The first commit of a session can be slow
  while pre-commit builds its environments (timeout is 120s). To skip pre-commit
  on auto-commits, add `--no-verify` to the `git commit` lines in `auto-commit.sh`.
- **History is intentionally granular** (one commit per edit). Squash-merge the PR
  if you want a single commit on `main`.
- Manage or disable these from the `/hooks` menu.
