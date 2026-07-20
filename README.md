# stage-model-dispatch

A Claude Code skill that decides **which model — and how much thinking — to use at every stage** of delegated work, so your expensive-model quota goes where it actually changes the outcome.

## What you get

- **Your quota lasts longer.** Running tests, file lookups, and chores stop eating your frontier model. The deep models are saved for design and review — the stages where they actually matter.
- **One decision instead of fifty.** Classify the task once (big-flow or small-flow); a table decides every stage's model and effort from there. No per-delegation agonizing.
- **Built-in second opinions.** Reviews are never a model grading its own homework: a second model family cross-reviews, and when the two disagree, the dissenting view gets checked first.
- **No more secret stand-ins.** When a premium model's quota runs out, some harnesses silently hand your task to a weaker model — no error, no warning, and you keep believing the expensive model did the work. This skill makes every delegated agent **sign its reply** with a one-line model receipt (`[MODEL:<id>]`). Wrong signature → a stand-in did the work, and the skill pins an explicit fallback instead of pretending.

## How it works

1. **Classify** — big-flow (needs design first) or small-flow (patch-sized), announced in one line you can override.
2. **Dispatch** — each stage (research → design → implement → review → test) runs on the model tier and effort from the table. Defaults are ceilings: nothing silently upgrades, and downgrading is your call, not the model's.
3. **Gate** — reviews before "done", with evidence: test stages must attach real command output. "Passed" alone doesn't count.

## Install

```bash
git clone https://github.com/dongq299/stage-model-dispatch ~/.claude/skills/stage-model-dispatch
```

Or copy `SKILL.md` into `~/.claude/skills/stage-model-dispatch/`. Claude Code picks it up automatically.

## Customize

1. Edit the **Tier map** in `SKILL.md` to your model stack (T1–T4).
2. Rename the effort values to your harness's ladder.
3. Have a second model family (another CLI/agent)? Wire it into the research/review stages. If not, delete those mentions — everything else stands alone.

## License

MIT
