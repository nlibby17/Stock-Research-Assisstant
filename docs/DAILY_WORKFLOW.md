# Daily Report Workflow

This workflow is tool-neutral. The deterministic application can be operated by a
person, Codex, or another capable local agent. It never requires an OpenAI API key
and never connects to a broker or places trades.

## Deterministic phase

Validate the active profile and universe after any personalization change:

```text
stockrank config-check
```

Use `stockrank config-check --live` before the first report for a newly supplied
universe. Personal configuration is created with `stockrank configure`; it remains
local to the computer and does not alter historical runs.

From the repository root, run:

```text
stockrank daily-report
```

For a person who wants the base report and dashboard in one step, use
`stockrank morning`. It runs the same deterministic report workflow and launches
the dashboard only after that workflow succeeds. Keep using `daily-report` by itself
when an AI or human will import qualitative research before opening the dashboard.

This performs, in order:

1. SEC identity and provider health validation.
2. SEC 10-K/10-Q filing metadata synchronization.
3. SEC Company Facts synchronization.
4. Local SEC financial snapshot construction.
5. Yahoo-backed production ranking and base-report generation.
6. Isolated SEC/Yahoo shadow comparison.
7. Final run validation.

Every step reports its own result. The command continues after an expected degraded
provider result so it can preserve any usable output, but exits nonzero and names
every step that requires review. Cached or stale data remains explicitly labelled.
Use `--force` only when an intentional live refresh should bypass fresh caches.

The shadow comparison is skipped if the Yahoo production-ranking step fails. A
comparison counts toward Step 2.4B only when it is linked to a recently completed
production run containing all configured securities with one consistent underlying
market-data date. Repeating the workflow after midnight, over a weekend, or against
the same cached market close does not advance the evidence counter.

## Optional current-source research phase

The deterministic phase writes `runtime/reports/research_template.json`. A person
or AI research agent may complete it using current sources, then run:

```text
stockrank research-import --file runtime/reports/research_template.json
stockrank validate-latest
```

Research the strongest eligible candidates only; never pad the list. Prioritize SEC
filings, company investor-relations and earnings materials, then reliable secondary
sources. Verify both publication and event dates. Clearly distinguish sourced facts,
analyst expectations, calculated metrics, interpretation, and speculation. Never
invent catalysts, targets, or dates. Store concise notes and source metadata, not
article or filing bodies.

## Dashboard

Run `stockrank dashboard` after the base report or research import. The dashboard is
local and reads the same SQLite history. It shows basic observed changes from the
previous completed run with the same universe and model, offers a CSV download of
all current rankings, and provides read-only personalization guidance. These basic
comparisons do not claim causal attribution or complete the later historical-analysis
roadmap. Deployment is not part of this workflow.
