# Correction Quality Rubric

Used to grade generated doc corrections (second-model grading in live evals).
Score each correction 1–5:

| Score | Meaning |
|---|---|
| 5 | Factually correct against the new code, minimal (only stale spans touched), style-identical |
| 4 | Correct and style-consistent, but touches slightly more text than necessary |
| 3 | Correct on the main point but misses a secondary stale detail, or style drifts |
| 2 | Partially correct: fixes something but introduces an inaccuracy or removes accurate content |
| 1 | Wrong: contradicts the new code, hallucinates behavior, or rewrites the section wholesale |

A correction is **shippable** at 4 or above. Report the mean score and the
shippable rate across all graded corrections.
