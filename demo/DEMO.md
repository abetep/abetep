# Demo Script (< 3 minutes)

**Storyline:** "Every team's docs are perpetually stale — here's a CI bot
that heals them."

## Setup (before recording)

```bash
# A demo repo with doc-sentinel installed (see README quickstart) and
# ANTHROPIC_API_KEY / OPENAI_API_KEY set as repo secrets.
git clone <your-demo-repo> && cd <your-demo-repo>
git checkout -b rename-include-history
```

## Beat 1 — The problem (0:00–0:20)

Show `docs/api.md` on screen: *"Pass `include_history=True` to embed the
task's full change history."* Say: "This doc is correct today. Watch how
easily it stops being correct — and how nobody would notice."

## Beat 2 — The breaking change (0:20–0:50)

```bash
sed -i 's/include_history/with_history/g' taskbox/api.py
git commit -am "refactor: rename include_history to with_history"
git push -u origin rename-include-history
gh pr create --fill
```

Say: "A routine rename. No doc file touched, so no reviewer will flag it."

## Beat 3 — The Action runs (0:50–1:40)

Open the PR's Checks tab; show the doc-sentinel job running. Narrate the
pipeline over the log output: "It diffs the PR on the AST, finds the doc
sections linked to `get_task`, and asks the LLM to verify each one against
the old and new code — every claim must quote the docs verbatim."

## Beat 4 — The payoff (1:40–2:40)

Show, in order:

1. The PR comment: *🩺 Doc Check Results: … 1 auto-fixed (see PR #…)*
2. The auto-opened docs PR: the diff shows exactly one changed phrase,
   `include_history=True` → `with_history=True`, rest of the file untouched.
3. The PR body table: section → what changed in code → correction.

Say: "High-confidence fixes become a PR. Complex changes get a draft with
TODO markers. Anything uncertain is flagged for a human — it fails closed,
never silent."

## Beat 5 — Close (2:40–3:00)

"Precision 0.83, recall 1.00 on the labeled eval suite in the repo — and it
costs about a dime per pull request. Install it from the marketplace with
five lines of YAML."
