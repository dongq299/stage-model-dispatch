---
name: stage-model-dispatch
description: Use when delegating multi-step work to subagents (research, design, implementation, review, testing) and choosing a model/effort per stage; or when classifying a task as big-flow vs small-flow.
---

# Stage Model Dispatch

Assign a model tier and a reasoning-effort level to **each stage** of delegated work, instead of running every subagent on one default model. The tables below are **ceilings** — never auto-upgrade past them; downgrade only when the user explicitly asks.

## Tier map (edit this for your stack)

| Tier | Role | Example |
|---|---|---|
| T1 | deepest reasoning | your frontier model |
| T2 | strong generalist | one step down |
| T3 | balanced | mid-tier |
| T4 | fast & cheap | smallest model |

Effort values assume a `low < medium < high < max` ladder — map them to whatever your harness calls its levels.

## Procedure

1. Skim the task, then open your reply with a one-line verdict: `[big-flow | small-flow — reason]`. The user can override it.
2. Delegate each stage with the model/effort from the table. Every delegation prompt must include the **role 3-pack** (below).
3. **Review stages**: run the table model's review **plus a cross-review from a different model family** (another CLI/agent) if you have one. When they disagree, **verify the dissenting opinion first** — only a confirmed high-severity finding blocks progress.
4. **Research stage**: run two agents **in parallel on the same goal** (different families if possible). Not a division of labor — the point is different blind spots on identical scope.
5. **Research merge**: a T1 agent merges, dedupes, and flags contradictions. Pass the merged file to the design stage **verbatim** — no lossy re-summarizing in between.
6. Before dispatching, map stage dependencies: independent work runs in parallel (like the research pair); dependent stages run serially. Don't serialize what doesn't depend.

## Role 3-pack (required in every delegation prompt)

1. **Role, one line** — domain + stage duty ("senior backend engineer implementing the payments module")
2. **2–3 concrete acceptance lenses** for this stage's output ("refutation-first, boundary values, rollback path") — no bare abstractions like "quality"
3. **One line on what this stage is NOT** ("the reviewer does not edit code")

## Stage handoff

Every stage saves its output to a file; the next stage receives the **path**, not a paraphrase. Add context if needed, but never replace the artifact with your own summary — lossy re-summarizing between stages is where delegated work quietly degrades.

## Big-flow defaults

| Stage | Tier | Effort |
|---|---|---|
| 1. Research (2× parallel, same goal) | T3 + second family | medium |
| 1b. Research merge | T1 | high |
| 2. Design | T1 | high |
| 3. Design review (+cross-review) | T2 | high |
| 4. Implementation | T2 | max |
| 5. Code review (+cross-review) | T1 | high |
| 6. Tests / smoke | T4 | medium |
| 7. Deploy / retrospective | T4 | medium |
| 8. Chores, simple lookups | T4 | low |

## Small-flow defaults

| Stage | Tier | Effort |
|---|---|---|
| 1. Quick check + short research | T3 (+second family) | medium |
| 2. Code | T2 | max |
| 3. Review (+cross-review) | T1 | high |
| 4. Run tests | T4 | medium |
| 5. Deploy | T4 | low |

## Flow classification

- Basis = **how much you must understand**, not how much you will change.
- Big-flow triggers: 3+ modules to understand / can't start without a design / multi-file behavior change.
- Mid-flight promotion (escape hatch): ~15 files read or ~10 attempts without a root cause → promote to big-flow from the next stage on. Existing outputs carry over.

## Inline boundary

Direct edits up to ~2 code files per turn stay on the session model — no table. From the 3rd file, stop and delegate (small-flow table). Any direct **change** still gets a T1 review (+cross-review) before you call it done — never self-review only. Read-only work and text reports need no review.

## Silent-substitution canary

If a tier has its own quota, some harnesses **silently** fall back to the session model when it runs out — no error, no signal. Detect it: ask every T1 delegation to end with a final line `[MODEL:<its model id>]`. Exactly one tag, on the last line, matching the requested tier — anything else means substituted. Strip the tag before passing output onward. On substitution: pin an explicit fallback model (one tier down) for the remaining T1 stages, and say so in your report. Never present substituted output as T1.

## Verification evidence

Test and verify stages may not report "passed" as a bare claim — the report must include an excerpt of the real command output (test summary lines, exit status). No excerpt = unverified; label it as such.

## Failure rule

Same stage fails the same acceptance check twice → stop, report, propose a different approach. No third identical retry.

## Downgrade mode (off by default)

Only when the user explicitly asks to save tokens: every cell drops one model tier and one effort step, and parallel research halves its agent count. Lasts for the current session only.

## Common mistakes

- Splitting the research goal between the two parallel agents — it's the same goal through different eyes
- Skipping the classification line and delegating straight away — the user loses their intervention point
- Applying the table to the interactive session model — it governs delegation only
- A role that is just a title ("you are an expert") — all three pack elements are required
- Leaving the T1 model pinned after its quota is gone — the harness substitutes silently; pin the fallback explicitly and report it
- Reporting "tests passed" with no output excerpt — no evidence, no claim
