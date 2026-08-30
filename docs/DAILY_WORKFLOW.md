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

The Company Facts step does not redownload all 50 companies merely because its raw
six-hour response cache has expired. It compares the current relevant filing set
with locally recorded refresh state, refreshes changed companies, follows up recent
filings for 48 hours, and performs a seven-day full safety refresh. All checks happen
during an explicitly started report; the application never remains running in the
background. `--force` still requests a full refresh.

Every step reports its own result. The command continues after an expected degraded
provider result so it can preserve any usable output, but exits nonzero and names
every step that requires review. Cached or stale data remains explicitly labelled.
The production ranking excludes unfinished same-day bars, rejects completed prices
older than five days, marks mixed ticker dates partial, and caps failed-refresh
fundamental fallback at seven days. A provider-derived session calendar distinguishes
ordinary weekends and market holidays from missing stock bars; a genuine gap makes
only the affected momentum, volatility, moving-average, volume, or drawdown metric
unavailable. Per-stock price, continuity, and fundamental decisions are retained
with the run and summarized in the report and dashboard.
Negative debt/equity and provider-summary ROE above the configured 200% validity
limit are withheld with explicit notes. A metric needs at least 10 usable peers to
receive percentile influence; weaker samples remain visible as raw values but reduce
score coverage instead of producing extreme small-sample ranks.
Top-candidate eligibility additionally requires the configured minimum latest
price and 20-day average dollar volume. A stock below either floor retains its
relative score and raw metrics, but its explicit eligibility reasons keep it out
of the top list. Equal overall scores use ticker order as a deterministic tie-breaker.
Scores are conditional on the metrics that were actually available: missing values
are neither estimated nor assigned a penalty. Overall and per-component coverage are
shown separately, and a favorable label is withheld below the configured overall
coverage gate. All labels describe relative standing within the selected universe,
not an absolute judgment about the company or investment.
Use `--force` only when an intentional live refresh should bypass fresh caches.
Each step also reports its wall-clock elapsed time, followed by the total deterministic
workflow time before `morning` launches the dashboard. Dashboard viewing time is not
included because the local server intentionally runs until the user stops it.

Each new ranking run also records a fingerprinted reproducibility manifest containing
its exact universe membership, scoring and calculation policy, provider policy,
application/schema versions, and relevant local package versions. The dashboard and
report compare runs only when both manifests are complete, their calculation contracts
match, their stored memberships reconcile, and their market-data dates are ordered.
Legacy runs without this evidence remain viewable but are labelled limited.

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
roadmap. Keep the launching terminal open; stop the server with Ctrl+C on Windows or
Control+C (⌃C) on macOS. Closing the browser tab alone does not stop it. Source-code
watching is disabled for this end-user workflow, so Watchdog and Xcode Command Line
Tools are unnecessary. Deployment is not part of this workflow.
