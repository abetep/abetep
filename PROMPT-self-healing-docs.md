# Master Prompt — Self-Healing Technical Documentation (GitHub Action)

> Prompt listo para pegar en Claude Code (o un agente de código equivalente).
> Está redactado en inglés porque es el idioma con el que mejor rinden los
> agentes de código y el estándar para un proyecto de portfolio open source.
> Recomendación de uso: ejecútalo por fases (el prompt ya lo exige), revisando
> el resultado de cada fase antes de autorizar la siguiente.

---

## The Prompt

You are a senior AI/platform engineer. Build **"doc-sentinel"**: a production-quality GitHub Action that detects when code changes in a pull request make the project's documentation inaccurate, pinpoints the exact stale sections, and either opens a PR with corrected docs (high confidence) or flags the sections for human review (low confidence).

This is a portfolio project that must look and behave like a tool other engineers would actually install. Optimize for correctness, clean architecture, and a professional developer experience — not for demo shortcuts.

### Ground rules (apply to everything you do)

1. **Work in phases, in order.** At the end of each phase: run the test suite, show me a short summary of what was built and how you verified it, and STOP for my review before starting the next phase.
2. **No placeholders, no mocks left in production paths.** Every function you write must be fully implemented. If something needs an API key at runtime, read it from an environment variable and fail with a clear error message when missing.
3. **Tests are part of every phase**, not a final phase. Use pytest. Each module gets unit tests; LLM calls are mocked in tests behind a thin client interface so the suite runs offline.
4. **Deterministic where possible.** LLM calls use temperature 0 and structured outputs (JSON schema / tool use). Every LLM response is validated with Pydantic before use; on validation failure, retry once with the validation error in the prompt, then give up gracefully.
5. **Cost-conscious by design.** Cache embeddings by content hash so unchanged chunks are never re-embedded. Log token usage per run and print a cost estimate in the Action summary.
6. **Conventional commits**, one commit per coherent unit of work.

### Tech stack (fixed — do not substitute)

- Python 3.11+, packaged with `pyproject.toml` (hatchling or setuptools), src layout: `src/doc_sentinel/`
- Embeddings: OpenAI `text-embedding-3-small`
- Vector store: ChromaDB in persistent file mode (no server)
- LLM: Claude Sonnet via the Anthropic API (default), with a provider-agnostic client interface so GPT-4o can be swapped in via config
- Git/GitHub: `GitPython` for diff parsing, `PyGithub` for PR/comment creation
- Code parsing: Python `ast` module (do not regex-parse Python code); markdown parsing with `markdown-it-py`
- CI/CD: GitHub Actions; the Action itself is a Docker container action
- Lint/format: ruff; type-check with mypy (strict on `src/`)

### Repository layout to create

```
doc-sentinel/
├── action.yml
├── Dockerfile
├── pyproject.toml
├── README.md
├── src/doc_sentinel/
│   ├── indexing/        # Phase 1: code & doc parsers, link graph
│   ├── detection/       # Phase 2: diff parsing, change filtering, staleness verification
│   ├── repair/          # Phase 3: correction generation + validation
│   ├── github/          # Phase 4: PR/comment workflows
│   ├── llm/             # provider-agnostic LLM + embedding clients
│   └── cli.py           # `doc-sentinel index|check|repair` entry points
├── tests/
└── .github/workflows/   # CI for doc-sentinel itself (lint, type-check, tests)
```

---

### PHASE 1 — Code-to-docs mapping (the index)

Build `doc_sentinel.indexing`:

1. **Code parser** (`code_parser.py`): walk the target repo and extract semantic chunks using `ast`: functions (signature + docstring + decorators), classes (name, bases, public methods), FastAPI/Flask route definitions, Pydantic/settings config schemas, and CLI commands (click/argparse/typer). Each chunk gets a stable ID: `"{relative_path}::{qualified_name}"`. Represent chunks as a Pydantic model with: id, kind, file, line span, signature, docstring, source hash.
2. **Doc parser** (`doc_parser.py`): split every `.md`/`.mdx` file under configurable doc roots into sections by heading. Each section: heading path (e.g. `"Configuration > Environment Variables"`), raw markdown, line span, and extracted code references (backtick-quoted identifiers, code-block contents, function/class/config-key names matched against the code chunk inventory).
3. **Link graph** (`link_graph.py`): connect doc sections to code chunks with two strategies, each producing typed edges with a score:
   - *Lexical*: doc section explicitly mentions a chunk's name → edge with score 1.0.
   - *Semantic*: embed all chunks and sections (OpenAI embeddings, cached in ChromaDB keyed by content hash); connect pairs above cosine similarity threshold (default 0.75, configurable) → edge with the similarity as score.
4. **Persistence**: serialize the graph to `.doc-sentinel/index.json` (chunks, sections, edges, config used, tool version). Loading must validate the schema and detect version mismatches.
5. **CLI**: `doc-sentinel index --repo PATH` builds/refreshes the index incrementally (only re-parse and re-embed files whose hash changed).

**Acceptance criteria:** unit tests cover the parser on a fixture mini-repo (functions, classes, a FastAPI route, a config schema, markdown with nested headings); `doc-sentinel index` on the fixture produces a correct, deterministic index.json; embedding client is mocked in tests.

STOP for review.

---

### PHASE 2 — Change detection pipeline

Build `doc_sentinel.detection`:

1. **Diff parsing** (`diff_parser.py`): given a base ref and head ref, use GitPython to get changed files and hunks; map hunks to affected code chunks by intersecting line spans with the Phase 1 chunk inventory (re-parse changed files at both refs to capture the old and new versions of each chunk).
2. **Semantic filtering** (`change_filter.py`): classify each affected chunk change as `signature_change`, `behavior_change`, `config_change`, `added`, `removed`, or `cosmetic`. Rules: docstring/comment/whitespace-only diffs and changes under `tests/` are `cosmetic` and dropped; signature comparison is done on the parsed AST, not text.
3. **Suspect selection** (`suspects.py`): for each meaningful change, query the link graph for connected doc sections; deduplicate; rank by edge score.
4. **LLM staleness verification** (`verifier.py`): for each suspect, one LLM call with: old chunk source, new chunk source, doc section content. Structured output: `{is_stale: bool, confidence: float, issues: [{quote_from_docs, what_is_wrong, what_code_says_now}]}`. `quote_from_docs` must be an exact substring of the section — validate this programmatically and treat non-matching quotes as a failed response.

**Acceptance criteria:** fixture-based tests where a scripted code change (rename a parameter, change a default, delete a function) yields exactly the expected suspects and, with a mocked LLM, the expected verdicts; a cosmetic-only diff yields zero suspects.

STOP for review.

---

### PHASE 3 — Doc repair engine

Build `doc_sentinel.repair`:

1. **Correction generator** (`generator.py`): for each confirmed-stale section, one LLM call with the section, the new code, and the Phase 2 diagnosis. Instructions to the model: rewrite ONLY the inaccurate spans, preserve style/tone/structure/formatting, never touch accurate sentences. Output: full replacement markdown for the section plus a machine-readable list of edits.
2. **Validator** (`validator.py`): a second, independent LLM pass that receives the new code + corrected section and answers: accurate? minimal (unchanged parts preserved — verify programmatically by diffing, not just by asking)? style-consistent? Output a 0–1 quality score with reasons.
3. **Confidence router** (`router.py`): combine verifier confidence, change class, and validator score into a mode: `auto_fix` (e.g. renamed param, changed default, all scores high), `draft_with_todos` (new/removed feature — inject `<!-- TODO(doc-sentinel): human review -->` markers), or `flag_only`. Thresholds live in one config object with sane defaults, overridable via Action inputs.

**Acceptance criteria:** with mocked LLM responses, an end-to-end test runs index → detect → repair on the fixture repo and produces a patched markdown file where untouched sections are byte-identical; router unit tests cover all three modes.

STOP for review.

---

### PHASE 4 — The GitHub Action

1. **`action.yml`**: Docker container action. Inputs: `anthropic-api-key`, `openai-api-key`, `docs-path`, `confidence-threshold`, `mode` (`fix` | `flag-only`), `base-ref`. Outputs: `stale-count`, `fixed-count`, `flagged-count`, `fix-pr-url`. Triggered by the consumer's workflow on `pull_request` for code paths.
2. **`Dockerfile`**: slim Python 3.11 image, dependencies installed from the lockfile, non-root user, entrypoint runs the pipeline.
3. **PR workflows** (`github/workflows.py`): for `auto_fix` corrections — create branch `doc-sentinel/fix-<pr-number>`, commit patches, open a PR whose body lists each fix as *doc quote → what changed in code → new text*. For `flag_only` — comment on the triggering PR with deep links (`file#Lstart-Lend`) to each stale section and the diagnosis.
4. **Summary comment** on every run (idempotent — update the existing comment instead of posting duplicates, via an HTML marker): "🩺 Doc Check: N sections verified, X auto-fixed (PR #…), Y flagged for review", plus a collapsible details table and the token/cost estimate.
5. **Self-CI**: workflow for this repo running ruff, mypy, pytest on every PR.

**Acceptance criteria:** `docker build` succeeds; an integration test exercises the workflow logic against a mocked PyGithub; a `workflow_dispatch` smoke-test workflow can run the Action end-to-end against this repo itself.

STOP for review.

---

### PHASE 5 — Real-world evaluation

1. Create `evals/`: pick a well-documented open-source project (e.g. a FastAPI-based app), vendor a snapshot as a fixture, and script **10+ labeled test cases**: deliberate code changes with ground-truth annotations of which doc sections become stale.
2. An eval runner executes the full pipeline (real LLM calls, behind an `--live` flag) and reports precision, recall, F1 for staleness detection, plus a rubric-scored correction quality (second-model grading with the rubric in the repo).
3. Write results into `evals/RESULTS.md` and surface the headline numbers in the README. Report honest numbers — a credible 85% beats a fake 100%.

STOP for review.

---

### PHASE 6 — Portfolio polish

1. **README**: problem statement first ("every team's docs are perpetually stale"), 60-second quickstart (copy-paste workflow YAML), architecture diagram (mermaid), the eval numbers, configuration reference, cost-per-run estimate, limitations section.
2. **Marketplace readiness**: branding in `action.yml`, semver tag `v0.1.0`, `v0` major tag, CHANGELOG.
3. **Demo script** (`demo/DEMO.md`): the exact <3-minute walkthrough — push a breaking change, Action runs, summary comment appears, auto-fix PR opens — with the shell commands to reproduce it.

Final deliverable: I should be able to add three lines of YAML to any repo's workflow and have working self-healing docs.

---

## Cómo usarlo (nota para ti, no forma parte del prompt)

- **Pégalo entero** al inicio de la sesión: las "ground rules" y el stack fijo evitan que el agente improvise; los "STOP for review" te dan control por fase sin tener que re-explicar el contexto.
- **Revisa de verdad cada fase** antes de decir "continue with Phase N": es donde corriges rumbo barato. Pide `git log --oneline` y ejecuta los tests tú mismo.
- **Secretos**: exporta `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` en tu entorno local y como secrets del repo; el prompt ya obliga al agente a leerlos de env vars y nunca hardcodearlos.
- Si usas Claude Code, ejecuta primero `/init` en el repo nuevo para que genere un `CLAUDE.md`, y añade ahí las ground rules del prompt para que persistan entre sesiones.
