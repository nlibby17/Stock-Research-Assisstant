# Version 1 Design and Roadmap

## Decision summary

V1 favors reliability, explainability, and low storage over breadth. It screens an
explicit 50-name, liquid, U.S.-listed universe spanning all 11 GICS-style sectors.
This is a curated research universe—not an index, market proxy, or claim to cover
all U.S. opportunities. It is small enough for responsible use of an unofficial
free source and broad enough to exercise cross-sector ranking. Change it by editing
`config/universe.csv`; each run stores the exact universe used.

Daily adjusted/unadjusted prices and a small set of current fundamental summaries
come from Yahoo Finance through the open-source `yfinance` client. The adapter is
isolated so it can be replaced. SEC EDGAR is the preferred primary source for research-agent
research and the planned structured-fundamental adapter. SQLite is the only durable
runtime store. Streamlit is a read-only dashboard over the same stored runs.

## Source assessment (checked 2026-08-26)

### Yahoo Finance through yfinance — selected for V1 screening

- Cost/key: free and no key; `yfinance` is an unaffiliated open-source client.
- Freshness: daily bars are labelled end-of-day/previous-close. Exchange status and
  delays vary, so V1 does not claim real-time data.
- Limits/reliability: no published API quota or SLA for this unofficial access;
  schemas, throttling, and availability can change. The library documentation says
  downloaded Yahoo data is intended for research/education and Yahoo Finance API
  use is personal-use only. Batch price fetches, 6-hour price caching, 24-hour
  fundamental caching, retries, and cache fallback minimize requests.
- Usage: appropriate only for this personal local research workflow after the user
  reviews the applicable Yahoo terms. It is not selected for redistribution or a
  commercial product.

### SEC EDGAR APIs — selected for primary-source research and structured facts

- Cost/key: free, no API key.
- Freshness: submissions and XBRL APIs update as filings disseminate; SEC states
  typical processing under a minute for XBRL and under a second for submissions,
  though delays can increase at peaks.
- Limits: declare a descriptive User-Agent/contact and stay below the SEC's
  aggregate ceiling of 10 requests/second. V1 research stores filing URLs,
  accession identifiers, dates, and notes—not full documents.
- Limitations: issuer taxonomy choices, amended facts, fiscal calendars, and XBRL
  contexts require careful normalization. Steps 2.1–2.3 preserve that evidence;
  Step 2.4 derives comparable periods and validates provider precedence before any
  SEC value can affect production rankings.

### Alpha Vantage — optional/deferred

The official standard free allowance is 25 requests/day. That cannot refresh a
50-stock multi-endpoint screen every morning, and real-time/15-minute-delayed U.S.
data is premium. It remains a possible provider for a smaller watchlist or for a
user whose educational project receives higher limits. V1 does not request a key.

### Twelve Data — optional/deferred

The Basic plan currently advertises 8 API credits/minute and 800/day, resetting at
00:00 UTC. It is a credible keyed price-data alternative, but endpoint credit costs,
exchange entitlements, and plan terms must be checked for the exact use. Adding it
would improve provider redundancy; it is deferred until the user chooses to create
and manage a key.

## Data flow and failure policy

```text
preferences + universe
        |
provider adapter -> normalized price bars/fundamentals -> SQLite cache
        |                         |
        +---- warnings -----------+
                                  v
                         metrics -> scorer
                                      |
                    immutable run + results + config snapshot
                                      |
                         Markdown report + Streamlit
                                      |
                         research-agent JSON import
```

A provider exception is recorded per ticker/source. Fresh cache is preferred; stale
cache can be used only when labelled with its original timestamp. Missing data is
not imputed. Synthetic demo values require the explicit `--demo` flag and carry a
synthetic label throughout.

## Scoring details

Raw values are converted to within-run percentile scores. Directions are stored in
configuration: most metrics favor higher values; valuation multiples must be
positive and favor lower values; debt and volatility favor lower values; maximum
drawdown favors the shallower (higher) value. Ties receive the same average rank.

A sector convention excludes industrial-company FCF, gross-margin, current-ratio,
and debt/equity fields for Financials because those fields are absent or not
economically comparable for banks and diversified financial institutions. Missing
weights are rescaled and the reduced coverage remains visible.

Within a component, missing metrics remove their weight and the available weights
are rescaled. Component coverage is the share of configured metric weight present.
The overall score uses each component's configured weight multiplied by its
coverage, then rescales. Overall coverage is the sum of those effective weights.
A security below 60% coverage is ineligible for the top list. Scores are rounded
only for display; full values and raw metrics are stored.

Labels are deterministic: 75+ `Strong candidate`, 65–74.99 `Worth further
research`, 55–64.99 `Watchlist candidate`, below 55 `Currently unattractive`.
The top list includes eligible scores of 55+ and caps at 10 without padding.

## Metric availability

Available in V1 (subject to source gaps): latest daily close and date; market cap;
1/3/6/12-month price momentum; 3-month annualized volatility; one-year drawdown;
20-day average dollar volume; revenue and earnings growth summaries; free-cash-flow
margin/yield; gross and profit margins; ROE; debt/equity; current ratio; trailing and
forward P/E; PEG; and price/sales.

Deferred from ranking:

- Earnings revisions, consensus estimates/targets, surprises and upcoming earnings:
  coverage and definitions are inconsistent in free feeds. A research agent may cite current,
  clearly attributed values in research.
- Peer-relative valuation and sector strength: V1's curated sample is too small for
  defensible industry peer groups. Sector ETF trends can appear in market context.
- Insider and institutional activity: SEC Forms 3/4/5 and 13F need entity-aware,
  transaction-aware normalization; raw aggregator fields can mislead.
- News/catalysts/risks: language is not a deterministic numeric input. A research agent reviews
  recent dated sources and imports concise notes.
- True point-in-time FCF/earnings growth and historical fundamentals: current Yahoo
  summaries are not safe for backtests. SEC facts, filing acceptance timestamps,
  and period contexts are now stored, but Step 2.4 must derive and validate
  comparable metrics before they become ranking inputs.
- Valuation relative to a company's own history: requires retained point-in-time
  shares, earnings, and fundamentals; current-only multiples would create hindsight.

## Runtime layout, size, and retention

```text
runtime/
  stockrank.sqlite3       normalized cache and immutable history
  cache/sec/              transient SEC JSON request cache
  logs/stockrank.log      rotating log (2 MB x 3)
  reports/                latest/history Markdown and research JSON
  tmp/                    removable intermediates
```

Expected size for 50 symbols with warm, compressed SEC submissions and Company
Facts caches is about 60–100 MB: normalized bars and cache, up to roughly 8 MB
logs, and a few MB reports. Immutable
daily ranking history is
expected to add roughly 20–40 MB per year at this size. No articles or filings are
archived. SEC JSON may exist temporarily to avoid repeat requests, but it is not
part of immutable history. Cleanup keeps compact run/results/research history,
removes bars older than 550 days, expired cache summaries, reports older than 30
days (except `latest.*`), and temp files older than one day. Cleanup previews by
default.

## Roadmap

The authoritative implementation order and acceptance gates are maintained in
[`ROADMAP.md`](ROADMAP.md). The high-level stages are:

1. **V1 foundation — complete:** provider/cache, normalized schema, metrics,
   versioned scores, CLI, report, dashboard, research import, and tests.
2. **Data hardening — in progress:** SEC identity, submissions, and Company Facts
   are complete. Next are financial-period derivation, shadow provider comparison,
   controlled model promotion, and review-only dated universe proposals.
3. **Historical intelligence:** entries/exits, score and coverage deltas, rule-based
   change attribution, forward returns, and model/universe-version comparisons.
4. **Point-in-time evaluation:** first a clearly labelled current-universe replay,
   then survivorship-aware backtesting only when historical membership, delisting,
   corporate-action, and price coverage are defensible.
5. **Operational hardening and optional expansion:** backup/recovery, diagnostics,
   optional user-authorized scheduling, and evidence-driven provider or deployment
   decisions rather than mandatory paid integrations.

No stage includes brokerage connectivity or automated trade execution.

### Step 2.1 status: SEC identity and connection foundation

Completed foundation:

- official ticker/CIK/exchange mapping from
  `https://www.sec.gov/files/company_tickers_exchange.json`;
- normalized 10-digit CIKs and ticker aliases such as `BRK.B` → `BRK-B`;
- required application/contact user agent loaded only from the ignored `.env`;
- HTTPS and SEC-host allowlisting, five-request-per-second default throttling,
  retries for transient HTTP failures, and bounded exponential backoff;
- atomic 24-hour JSON cache with an explicitly labelled, seven-day maximum stale
  fallback;
- persisted SEC provider health and 50-stock identity-coverage reporting;
- deterministic tests for configuration, host restrictions, parsing, caching,
  retries, stale fallback, malformed payloads, and health persistence.

The identity cache is infrastructure, not evidence that a company is currently
eligible for the investment universe. Security classification and proposed
universe changes remain Step 2.5 work.

### Step 2.2 status: filing and availability-date tracking

Completed filing layer:

- current submissions plus SEC-published historical submission pages when their
  date ranges overlap the configured five-year window;
- normalized 10-K, 10-Q, 10-K/A, and 10-Q/A metadata with accession numbers,
  filing/report dates, raw acceptance values, UTC availability, primary documents,
  canonical archive links, source URLs, fetch times, and precision labels;
- point-in-time filtering and effective-filing selection that keeps amendments as
  independent evidence while preferring the latest available record for the same
  form and reporting period;
- active/inactive reconciliation so post-acceptance SEC corrections are visible;
- audited, evidence-linked predecessor CIKs for corporate identity transitions;
- stored coverage and health plus report/dashboard links to the latest filings.

The SEC webmaster guidance describes acceptance time as an Eastern clock. Because
the submissions JSON commonly appends `Z` to that value, the application preserves
the raw string and explicitly localizes the documented Eastern wall clock before
converting it to UTC. Missing acceptance times fall back to date-only precision.

### Step 2.3 status: Company Facts normalization

Completed structured-fact layer:

- one official Company Facts request per current or audited predecessor CIK;
- a versioned allowlist of canonical fields, standard taxonomy tags, expected
  units, period types, and ordered aliases;
- normalized exact decimal values with instant/duration dates, fiscal year/period,
  frame, form, accession, filing date, original tag metadata, and source URL;
- accession joins to filing acceptance timestamps, with explicit date-only
  precision when a stored filing match is unavailable;
- exact-context deduplication, rejection of conflicting duplicate values, and
  point-in-time selection of later amendments/restatements;
- active/inactive reconciliation, five-year storage, full-universe concept
  coverage and provider-health reporting.

Company Facts are intentionally not ranking inputs yet. Step 2.4A now derives
comparable financial periods and transparent local calculations. Step 2.4B will
compare those results with existing Yahoo summaries in shadow mode, and Step 2.4C
will define precedence and fallbacks and quantify ranking changes before any model
promotion.

### Step 2.4A status: financial snapshots and calculation lineage

Completed calculation layer:

- immutable, formula-versioned snapshots for an explicit point-in-time cutoff;
- annual, discrete-quarter, YTD, and TTM observations with non-calendar and
  52/53-week fiscal-year handling;
- cumulative-quarter subtraction and four-contiguous-quarter TTM construction;
- sign-aware annual and quarterly growth, FCF, margins, average-equity ROE, and
  aligned-date current ratio calculations;
- explicit missing, invalid, derived, reported, and sector-excluded quality states;
- metric-level accession, concept, period, availability, and source-URL lineage;
- CLI build/status coverage and a read-only dashboard table, with no connection to
  production scoring.

The calculation rules and validation result are in
[`STEP_2_4A.md`](STEP_2_4A.md). Step 2.4B is the next gate; the current scoring model
still reads Yahoo summary fundamentals exactly as before.

### Step 2.4B status: shadow comparison in progress

The immutable comparison infrastructure, configurable tolerance matrix, CLI status,
and dashboard breakdowns are implemented. The first successful 50-stock run is
stored; two additional full-universe runs on distinct analysis dates are required
before Step 2.4B can be considered complete. Comparisons are classified by metric,
company, and sector as comparable, approximately comparable, materially different,
stale, missing, or structurally incomparable. None are ranking inputs.

## Universe maintenance policy

V1 remains manually curated and versioned; the enforceable selection policy is in
`config/universe_policy.toml`. This avoids pretending an unofficial quote endpoint
is an authoritative security master. Once the SEC/provider layer is stronger, a
monthly-capable proposal workflow may join active exchange listings to SEC
ticker/CIK data, apply security-type, history, liquidity, coverage,
corporate-action, delisting, and sector-balance checks, then write a dated proposed
universe with evidence for review. It never activates a proposal automatically.
User-approved changes apply prospectively, and historical runs always retain their
original member list and universe version.
