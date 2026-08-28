# Codex Morning Analysis Workflow

When the user says **“Run my morning analysis”** (or equivalent), perform this
workflow from the repository root. This is research-only: never connect to a
broker, place an order, or portray a ranking as certainty.

Treat `docs/DAILY_WORKFLOW.md` as the agent-neutral operational contract. Codex may
execute its deterministic phase with `stockrank daily-report`, then perform the
current-source research phase below.

1. Read `README.md`, inspect the effective configuration with `stockrank config-check`,
   and read this file. Check `git status` and preserve unrelated user changes. Before roadmap development, also read
   `docs/ROADMAP.md` and follow its sequence and acceptance gates.
2. Activate `.venv` if present. Run `stockrank sec-health`,
   `stockrank sec-filings-sync`, `stockrank sec-facts-sync`,
   `stockrank sec-financials-build`, then `stockrank run` (or
   `python -m stockrank.cli run`), followed by `stockrank provider-shadow-run`.
   SEC financial snapshots and provider comparisons are monitored shadow artifacts
   and must not be substituted into production scoring before the Step 2.4C gate.
   Never substitute demo data for unavailable live data. If a network source fails,
   report the failure and whether cached values were used.
3. Run `stockrank validate-latest`. Inspect freshness, missing-field coverage,
   provider warnings, eligible count, and the latest report/research template in
   `runtime/reports/`.
4. Research only the strongest eligible candidates (normally 5–10, never padded)
   and the market/sector context. Use current web research. Prioritize SEC filings,
   company investor-relations releases and earnings materials, then reliable
   secondary sources. Verify both publication date and event date. Do not rely on
   search snippets for material claims.
5. Clearly separate sourced facts, analyst expectations, calculated metrics,
   Codex interpretation, and speculation. Say when a value is stale, delayed,
   missing, or low confidence. Do not invent a catalyst, analyst target, or date.
6. Fill the generated `runtime/reports/research_template.json`. Keep concise notes
   and source metadata/URLs; do not download or archive articles or filings. Import
   with `stockrank research-import --file runtime/reports/research_template.json`.
7. Re-run `stockrank validate-latest`; open the dashboard with
   `stockrank dashboard` only if the user wants the interactive view. Present the
   Markdown report and summarize meaningful changes versus the preceding run.
8. Before any commit, run tests and `git status --short`; verify `.gitignore`, that
   `.env.example` has placeholders only, and that no `.env`, database, cache,
   report, log, temp file, or secret is staged. Do not commit unless requested.

Use `stockrank storage-status` when storage is relevant. `stockrank storage-clean`
is a dry run; use `--apply` only when cleanup is requested or clearly part of the
morning workflow and the preview contains only expired runtime artifacts.

## Reasoning-level recommendation

Before starting each roadmap milestone, numbered substep, or meaningful operational
task, recommend **light**, **medium**, **high**, or **very high** reasoning effort and
give the user a one-sentence rationale. Prefer light for explanations of existing behavior,
status checks, launching the dashboard, running an already-tested command such as
the deterministic daily report, and other simple low-risk tasks. Prefer medium for
routine implementation, documentation, dashboard polish, and straightforward tests.
Prefer high for financial-data semantics, scoring changes, migrations, architecture,
difficult debugging or review, and qualitative financial research. Reserve very
high for exceptional work with unusually broad consequences or interacting risks,
such as the roadmap's survivorship-aware backtest, a major cross-cutting redesign,
or an unresolved high-stakes correctness investigation. Escalate when a task reveals
more ambiguity or material risk than its initial recommendation anticipated, and do
not use very high when high is sufficient.

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
