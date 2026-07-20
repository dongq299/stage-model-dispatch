# stage-model-dispatch

A Claude Code skill that assigns a **model tier + reasoning effort to every stage** of delegated subagent work — research, design, implementation, review, tests — instead of burning your deepest model on everything.

Distilled from daily multi-model operation. The frame is fixed; the values are yours to tune.

## Why

- **Defaults are ceilings.** The table caps each stage. Nothing silently upgrades; downgrading is a user decision, not the model's.
- **Cross-family review.** Review stages pair the table model with a second model family (another CLI/agent). Disagreements are settled by verifying the dissenting opinion first.
- **Silent-substitution canary.** When a premium tier's quota runs out, some harnesses silently swap in your session model — no error. A one-line `[MODEL:<id>]` tag check catches it before you trust downgraded output as frontier work.

## Install

```bash
git clone <repo-url> ~/.claude/skills/stage-model-dispatch
```

Or copy `SKILL.md` into `~/.claude/skills/stage-model-dispatch/`. Claude Code picks it up automatically.

## Customize

1. Edit the **Tier map** in `SKILL.md` to your model stack (T1–T4).
2. Rename the effort values to your harness's ladder.
3. Have a second model family (another CLI/agent)? Wire it into the research/review stages. If not, delete those mentions — everything else stands alone.

## License

MIT
