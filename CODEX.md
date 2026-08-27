# Codex Morning Analysis Workflow

When the user says **“Run my morning analysis”** (or equivalent), perform this
workflow from the repository root. This is research-only: never connect to a
broker, place an order, or portray a ranking as certainty.

1. Read `README.md`, `config/preferences.toml`, and this file. Check `git status`
   and preserve unrelated user changes.
2. Activate `.venv` if present. Run `stockrank sec-health`,
   `stockrank sec-filings-sync`, `stockrank sec-facts-sync`, then `stockrank run` (or
   `python -m stockrank.cli run`). Never substitute demo data for unavailable
   live data. If a network source fails, report the failure and whether cached
   values were used.
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

Before starting each roadmap milestone or numbered substep, recommend either
**medium** or **high** reasoning effort and give the user a one-sentence rationale.
Prefer high for financial-data semantics, scoring changes, migrations, architecture,
and difficult debugging or review. Prefer medium for routine implementation,
documentation, dashboard polish, daily operation, and straightforward tests.
