# Step 2 — Data Hardening

Step 2 strengthens data identity, provenance, availability dates, and provider
reliability before the application adds historical attribution or backtesting.
Yahoo remains the price source while SEC EDGAR becomes the authoritative source
for supported reported fundamentals.

## Milestones

1. **2.1 SEC identity and connection foundation — complete**
   - declared user agent, SEC-host HTTPS restriction, conservative throttling;
   - retries, bounded stale fallback, atomic runtime cache;
   - ticker/CIK/exchange mapping, universe coverage, persisted provider health.
2. **2.2 Filing and availability-date tracking — complete**
   - recent and paginated historical submissions metadata;
   - 10-K, 10-Q, and amendment preservation and point-in-time effective selection;
   - raw acceptance strings plus SEC-Eastern-to-UTC normalization;
   - reporting periods, filing dates, accession and primary-document URLs;
   - active/inactive records for post-acceptance corrections or removals;
   - audited predecessor-CIK continuity for corporate reorganizations;
   - full-universe sync health, coverage, CLI status, report and dashboard links.
3. **2.3 Company Facts normalization — complete**
   - explicit, versioned XBRL concept aliases and expected units;
   - exact decimal values, instant/duration periods, fiscal labels and frames;
   - accession joins to Step 2.2 filing-availability timestamps;
   - deterministic duplicate rejection, restatement selection, and missing values;
   - five-year normalized storage, provider health, CLI and dashboard coverage.
4. **2.4 SEC metric derivation and controlled provider promotion — next**
   - **2.4A:** point-in-time annual, quarterly, YTD, and TTM financial snapshots
     with explicit local formulas and metric lineage;
   - **2.4B:** SEC/Yahoo shadow comparison across at least three separate analysis
     dates, with no production-ranking changes;
   - **2.4C:** reviewed precedence/fallback rules, before/after ranking comparison,
     and explicit user approval before promotion to a new model version.
5. **2.5 Versioned universe proposals**
   - listing/CIK joins, eligibility checks, corporate-action handling, and dated
     proposed universe versions;
   - proposals are never activated automatically and never rewrite prior runs.

Each milestone ends with deterministic tests, a live validation where applicable,
documentation, and a separately reviewable commit.

The authoritative acceptance gates, reasoning recommendations, and Steps 3–5 are
defined in [`ROADMAP.md`](ROADMAP.md). Step 2.4 must follow 2.4A → 2.4B → 2.4C;
raw Company Facts must never be substituted directly into production rankings.

## Step 2.1 operational command

```powershell
stockrank sec-health
stockrank sec-health --force
```

The default command uses a fresh identity cache when available. `--force` makes
an explicit live request. Both commands compare SEC identities with the configured
universe and save the latest health result for the dashboard. Neither command
changes the universe or ranking.

## Step 2.2 operational commands

```powershell
stockrank sec-filings-sync
stockrank sec-filings-sync --force
stockrank sec-filings-sync --ticker NVDA
stockrank sec-filings-status
```

The configured default retains five years of normalized 10-K/10-Q metadata.
Additional SEC history pages are requested only when their published date ranges
intersect that window. A successful sync reconciles records in the window so later
SEC corrections or removals become inactive rather than being silently deleted.

Amendments remain independent source records. For a point-in-time view, the
effective selector chooses the latest filing available for the same base form and
reporting period. If an SEC acceptance timestamp is missing, availability falls
back to the filing date with date-only precision rather than inventing a time.

## Step 2.3 operational commands

```powershell
stockrank sec-facts-sync
stockrank sec-facts-sync --force
stockrank sec-facts-sync --ticker NVDA
stockrank sec-facts-status
```

The versioned `config/sec_companyfacts.toml` file is the only concept allowlist.
Each canonical field declares whether it is an instant or duration fact, its
accepted units, and ordered taxonomy/tag alternatives. Alternatives represent the
same economic field and are never summed. Exact duplicate contexts are collapsed;
conflicting values for the same concept, filing, unit, and period fail loudly.

Facts join to Step 2.2 by accession number to inherit the filing acceptance time.
A fact without a matching stored filing is labelled with date-only availability.
For the same canonical field, unit, and period, the point-in-time selector chooses
the latest filing available at the requested cutoff, then uses configured concept
priority to resolve aliases from that filing. Missing concepts remain missing.

Step 2.3 does not change ranking values. That promotion boundary belongs to Step
2.4, which will compare SEC-derived and Yahoo summary fields, document differences,
and define explicit precedence and fallbacks before changing the scoring model.
Provider health requires the five configured core concepts for every company.
Optional concepts remain visible as coverage counts because fields such as gross
profit, current assets, and conventional debt components are not uniformly reported
or economically comparable across banks, insurers, utilities, and industrial firms.
