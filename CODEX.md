# Codex Morning Analysis Workflow

When the user says **“Run my morning analysis,” “run my daily report,”** or an
equivalent phrase, perform this entire two-part workflow from the repository root:
first complete the deterministic application phase, then complete and import the
current-source qualitative research phase. Do not describe the daily report as
finished while its generated research template is still empty. This is research-only:
never connect to a broker, place an order, or portray a ranking as certainty.

Treat `docs/DAILY_WORKFLOW.md` as the agent-neutral operational contract. Codex
executes its deterministic phase with `stockrank daily-report`, then performs the
current-source research phase below whenever the user requests their daily or morning
report. A request for only the deterministic/base report is the exception and must be
explicit.

`stockrank morning` is the one-command convenience launcher for a person who wants
the deterministic base report followed immediately by the dashboard. Do not use it
as a substitute for this full AI-assisted workflow: keeping `daily-report`, research
import, and `dashboard` separate lets current-source research be added before the
interactive view is presented.

Use the executable inside this project's virtual environment, not an unrelated
global installation:

- Windows: `.\.venv\Scripts\stockrank.exe`
- macOS/Linux: `./.venv/bin/stockrank`

The steps below use `stockrank` as shorthand for the applicable executable.

1. Read `README.md`, `docs/DAILY_WORKFLOW.md`, and this file. Inspect the effective
   configuration with `stockrank config-check`, check `git status`, and preserve
   unrelated user changes. Before roadmap development, also read `docs/ROADMAP.md`
   and follow its sequence and acceptance gates.
2. Run `stockrank daily-report` exactly once. This command owns the ordered
   deterministic steps, timing, final validation, and failure handling. Do not
   reproduce it by manually invoking the individual SEC, Yahoo, shadow, or validation
   commands. Never substitute demo data for unavailable live data. If a network
   source fails, report the failure and whether cached values were used.
3. Confirm the deterministic command completed and inspect freshness, missing-field
   coverage, provider warnings, eligible count, `runtime/reports/latest.md`, and the
   generated `runtime/reports/research_template.json`. Preserve the template's exact
   `run_id`; research from another run must not be imported into the current one.
4. Research only the strongest eligible candidates (normally 5–10, never padded)
   and the market/sector context. Use current web research. Prioritize SEC filings,
   company investor-relations releases and earnings materials, then reliable
   secondary sources. Verify both publication date and event date. Do not rely on
   search snippets for material claims. If current web access or a local command
   requires approval, request it instead of replacing the step with unsourced prose.
5. Clearly separate sourced facts, analyst expectations, calculated metrics,
   Codex interpretation, and speculation. Say when a value is stale, delayed,
   missing, or low confidence. Do not invent a catalyst, analyst target, or date.
6. Fill the generated `runtime/reports/research_template.json` in place. Keep concise
   notes and source metadata/URLs; do not download or archive articles or filings. A
   separately created or previewed Markdown research document is only scratch work
   and does **not** populate the dashboard. Transfer any useful scratch research into
   the generated JSON template.
7. Import with
   `stockrank research-import --file runtime/reports/research_template.json`.
   Require a zero exit status and the
   `Imported researched notes and refreshed report` confirmation before continuing.
8. Run `stockrank validate-latest` and confirm it reports
   `Qualitative research=imported` for the same run. Then launch `stockrank dashboard`, present the
   refreshed Markdown report, and summarize meaningful changes versus the preceding
   run. Do not describe the full AI-assisted report as complete if import or
   post-import validation failed.
9. Before any commit, run tests and `git status --short`; verify `.gitignore`, that
   `.env.example` has placeholders only, and that no `.env`, database, cache,
   report, log, temp file, or secret is staged. Do not commit unless requested.

Use `stockrank storage-status` when storage is relevant. `stockrank storage-clean`
is a dry run; use `--apply` only when cleanup is requested or clearly part of the
morning workflow and the preview contains only expired runtime artifacts.

## Reasoning-level recommendation

Before starting each roadmap milestone, numbered substep, or meaningful operational
task, recommend **Light**, **Medium**, **High**, or **Extra High** reasoning effort and
give the user a one-sentence rationale. Prefer light for explanations of existing behavior,
status checks, launching the dashboard, running an already-tested command such as
the deterministic daily report, and other simple low-risk tasks. Prefer medium for
routine implementation, documentation, dashboard polish, and straightforward tests.
Prefer high for financial-data semantics, scoring changes, migrations, architecture,
difficult debugging or review, and qualitative financial research. Reserve Extra
High for exceptional work with unusually broad consequences or interacting risks,
such as the roadmap's survivorship-aware backtest, a major cross-cutting redesign,
or an unresolved high-stakes correctness investigation. Escalate when a task reveals
more ambiguity or material risk than its initial recommendation anticipated, and do
not use Extra High when High is sufficient.

## Forward-roadmap guardrails

- Treat `docs/ROADMAP.md` as authoritative for Steps 2.4–5. Do not skip a promotion
  gate or silently combine separately reviewable substeps.
- After an independently reviewable roadmap substep is complete, pause for the
  user's green light before beginning the next one unless the user has explicitly
  authorized multiple substeps together.
- Do not let SEC-derived metrics change production rankings during Steps 2.4A or
  2.4B. Step 2.4C requires a new model version, a before/after comparison, and
  explicit user approval.
- Store metric-level source, period, availability, calculation-version, fallback,
  and quality lineage before beginning historical attribution.
- Universe maintenance creates dated proposals only. Never activate a proposed
  universe automatically or rewrite membership in historical runs.
- Label current-universe historical replay as survivorship-biased. Do not call it a
  survivorship-aware backtest without adequate historical membership, delisting,
  corporate-action, and price data.
- Keep Step 5 local and no-cost by default. Paid/keyed providers, recurring
  automation, public/cloud deployment, and OpenAI API use require explicit user
  approval after costs, terms, privacy, and alternatives are explained.
