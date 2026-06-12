# Claude Code workflow hooks

These hooks enforce a **commit-per-change, auto-ship-as-PR** workflow. They live
in `settings.json` (committed, so the whole team gets them) and call scripts in
`hooks/`.

| Event | Script | What it does |
|-------|--------|--------------|
| `PostToolUse` (Write\|Edit) | `auto-commit.sh` | Commits the just-written file. Each edit → one commit. Skips `main`/`master`. |
| `PreToolUse` (Bash) | `guard-main.sh` | Blocks `git commit` / `git push` while on `main`/`master`. |
| `Stop` | `auto-ship.sh` | Sweeps up leftover tracked changes, **pushes** the branch, and **opens a PR** if none exists. |

## How it flows

1. Branch off `main` (`git switch -c <type>/<topic>`). The guard blocks work on `main`.
2. Every Write/Edit is auto-committed to the feature branch as its own commit.
3. When Claude stops, `auto-ship.sh` pushes the branch (setting upstream on the
   first push) and runs `gh pr create --fill` if the branch has no PR yet — so a
   turn that edits files ends with a pushed branch and an open PR.

## Notes

- **`pre-commit` is optional.** Both `auto-commit.sh` and `auto-ship.sh` detect
  whether `pre-commit` is installed: if it is, it runs as the safety net (and the
  commit hook re-stages + retries once if pre-commit reformats the file); if it
  isn't, they commit with `--no-verify` so the workflow still works. Install
  pre-commit (`make hooks`) to get the large-file / secret / ruff checks back.
- **Untracked files are never auto-committed** — only tracked modifications get
  swept up, so new or secret-bearing files won't slip into history.
- **History is intentionally granular** (one commit per edit). Squash-merge the PR
  if you want a single commit on `main`.
- These run only after you approve the project hooks — manage or disable them from
  the `/hooks` menu.
