# CLAUDE.md

All project rules live in AGENTS.md (imported below) and in `.claude/rules/`.
Do not duplicate rules here.

@AGENTS.md

## Claude Code specifics

- Before you push or open an MR, run `/pre-push-review` and fix what it reports.
- To add a business slice, run `/new-slice <name>`.
- `.claude/settings.json` hooks block: pushes when `make lint`/`make test` fail,
  pushes from branches without a type prefix, `--no-verify`, force-pushes, and
  commits/pushes on protected branches. Do not edit or bypass these
  hooks; if one blocks you, fix the cause or ask the human.
- Never read or edit `.env`. Use `.env.example`.
- Never merge, tag, or push to `dev`/`stage`/`main`/`master`/`prod`.
- Specs: `docs/architecture.md` and the Google Doc (appendix الف). Where they
  conflict (⚖ pending in AGENTS.md, list in docs/STRUCTURE_GAP.md §۳), or a
  point is ambiguous or marked ⚠️, ask instead of guessing, and record the
  decision in the MR description.
