# Forward Roadmap — Steps 2.4 through 5

This is the authoritative implementation sequence after Step 2.3. It refines the
high-level roadmap in `V1_DESIGN.md`. If the documents differ, follow this file
unless the user explicitly approves a later revision.

The permanent priorities remain correctness, transparency, data quality,
reliability, maintainability, useful analysis, and then convenience. No step may
connect to a brokerage or execute a trade. Paid services, public deployment,
background automation, or OpenAI API integration require separate user approval.

Before each numbered step or substep, Codex must recommend **medium** or **high**
reasoning effort with a one-sentence explanation. Each independently reviewable
substep ends with tests, relevant live validation, documentation, a privacy/source-
control check, user review, and a separate commit only when the user requests it.
After completing an independently reviewable substep, Codex pauses for the user's
green light before starting the next one unless the user explicitly authorizes a
larger group of substeps in advance.

## Step 2.4 — SEC metric derivation and controlled provider promotion

Step 2.4 must not be implemented as a direct replacement of Yahoo fields with raw
Company Facts. SEC facts first need comparable financial periods and transparent
local calculations.

### 2.4A Financial snapshot and calculation layer

**Reasoning recommendation: high.** Fiscal periods, cumulative quarterly facts,
negative-value growth, and sector conventions create subtle correctness risks.

Build immutable point-in-time annual, discrete-quarter, year-to-date, and trailing-
twelve-month snapshots from facts that were available at the requested cutoff.
Define and test:

- fiscal-calendar and 52/53-week handling;
- discrete-quarter derivation from cumulative year-to-date facts;
- annual and comparable-period revenue and earnings growth;
- sign-aware behavior when income or cash flow is zero or crosses zero;
- free cash flow as operating cash flow less capital expenditures, only when both
  inputs are comparable;
- margins, return on equity, current ratio, and other ratios with explicit
  denominator, averaging, and invalid-value rules;
- sector-specific exclusions for banks, insurers, and other structurally different
  businesses;
- calculation lineage: source facts, units, periods, accessions, availability time,
  formula version, and missing/invalid reason.

The ranking model remains unchanged throughout 2.4A. Acceptance requires
deterministic fixtures covering non-calendar fiscal years, amendments/restatements,
date cutoffs, cumulative quarters, missing inputs, negative denominators, and sector
exceptions, plus a full-universe coverage report.

### 2.4B Shadow provider comparison

**Reasoning recommendation: high.** Similar field names can represent different
periods or economic definitions, so comparisons require judgment and evidence.

Run SEC-derived and existing Yahoo summary metrics side by side without changing
production rankings. Classify comparisons as comparable, approximately comparable,
materially different, stale, missing, or structurally incomparable. Report coverage,
freshness, period alignment, fallback candidates, and material discrepancies by
metric, company, and sector.

Use configurable tolerances rather than silently treating every numeric difference
as an error. Complete at least three successful full-universe shadow runs on
separate analysis dates before promotion. Review representative edge cases and all
systematic or material discrepancies. Shadow results must be clearly labelled and
must not overwrite existing run metrics.

### 2.4C Precedence, fallback, and model promotion

**Reasoning recommendation: high.** This changes the meaning of scored metrics and
therefore requires an explicit, reviewable cutover.

Create a per-metric precedence matrix. The expected direction is:

- SEC authoritative for supported reported revenue, earnings, cash flow, assets,
  equity, and comparable balance-sheet facts;
- local formulas authoritative for historical growth, free cash flow, margins,
  return on equity, and current ratio when required SEC inputs are valid;
- Yahoo retained for forward-looking or market-derived fields such as forward P/E,
  PEG, beta, analyst-dependent estimates, and any current field without a reliable
  SEC substitute;
- missing remains missing when no defensible source exists; liabilities must never
  be relabelled as debt merely to increase coverage.

Every selected metric stored with a run must record source, as-of/availability time,
period, formula version, fallback status, and quality label. Promotion requires a
before/after ranking comparison, coverage comparison, documented exceptions, a new
scoring-model version (never an in-place change to `v1.0.0`), and explicit user
approval. Historical runs remain unchanged and understandable.

## Step 2.5 — Versioned universe proposals, not automatic activation

**Reasoning recommendation: high.** Listing identity, corporate actions, security
type, and survivorship directly affect both daily rankings and future backtests.

Build a monthly-capable universe-maintenance foundation that joins current listing
information to SEC ticker/CIK identities and applies documented checks for security
type, exchange, listing status, price/liquidity history, fundamental coverage,
corporate actions, delistings, and sector balance.

The system may create a dated proposed universe with additions, removals, reasons,
evidence, and validation warnings. It must never activate a proposal automatically.
The user approves any new version. Activation applies prospectively and never
rewrites membership stored with earlier runs. Corporate-identity overrides remain
separate from investment-universe membership.

Acceptance requires deterministic eligibility tests, dated proposal diffs, explicit
handling of unresolved identities and corporate actions, and proof that rejecting a
proposal leaves the active universe unchanged.

## Step 3 — Historical intelligence and change attribution

Step 3 turns immutable daily runs into useful history without claiming causality
that the stored evidence cannot support.

### 3.1 Historical data contract and run comparisons

**Reasoning recommendation: high.** Metric lineage, model versions, universe
versions, and provider changes must remain distinguishable.

Verify that each run preserves universe membership, metric values and lineage,
component and overall scores, configuration/model version, data-quality labels, and
relevant prices. Add comparisons for rank/score changes, top-list entries and exits,
coverage changes, and recommendation-label changes.

### 3.2 Rule-based change attribution

**Reasoning recommendation: high.** Attribution must separate evidence from
interpretation and avoid unsupported causal claims.

Attribute changes to observable categories such as price movement, newly available
filings, revised/restated facts, provider/fallback changes, universe changes, and
model/configuration changes. Label residual or ambiguous changes rather than
inventing an explanation.

### 3.3 Forward-return tracking and benchmarks

**Reasoning recommendation: high.** Date alignment, corporate actions, missing
prices, and benchmark selection affect performance conclusions.

Track forward returns at documented horizons for historical candidates and compare
them with appropriate broad benchmarks. Keep observation status incomplete until a
horizon has elapsed. Preserve the price source and dates used. Do not interpret
correlation as predictive proof.

### 3.4 Historical dashboard and reports

**Reasoning recommendation: medium.** Once historical calculations are tested,
this is primarily presentation and workflow work.

Add clearly labelled views for entries/exits, largest changes, attribution,
forward-return maturity, model versions, and universe versions. Historical views
must not mix incomparable model versions without an explicit label or filter.

## Step 4 — Point-in-time evaluation in two honesty levels

Step 4 must distinguish a current-universe replay from a genuinely
survivorship-aware backtest.

### 4.0 Backtest data readiness

**Reasoning recommendation: high.** Retention and corporate-action choices can
invalidate every later result.

Before replaying the model, extend price-history retention beyond the current 550
days, preserve adjusted-price methodology and benchmark history, document dividends
and splits, and define rebalance timing, transaction-cost assumptions, missing-data
rules, and model/universe-version inputs. The expected storage increase for the
50-stock universe should be estimated before implementation.

### 4A Current-universe historical replay

**Reasoning recommendation: high.** Point-in-time facts remove look-ahead bias but
do not remove survivorship or selection bias.

Replay supported model versions using only facts available at each historical
cutoff, but label every result **current-universe replay — survivorship-biased**.
Use it for debugging, sensitivity analysis, and provisional factor evaluation, not
as evidence of market-wide historical performance.

### 4B Survivorship-aware backtesting

**Reasoning recommendation: high.** This is the highest-risk analytical step in the
roadmap and must remain conditional on adequate historical universe data.

Proceed only when dated universe membership, delistings, corporate actions, and
historical prices are sufficiently complete. Report coverage, exclusions, benchmark
methodology, turnover, transaction costs, and uncertainty. If free sources cannot
support a defensible test, stop at 4A or propose a licensed source with costs and
terms for user review.

## Step 5 — Operational hardening and evidence-driven optional expansion

Step 5 is not a mandatory paid-provider phase. It makes the local application
durable and uses measured gaps from earlier steps to decide whether expansion is
worthwhile.

### 5.1 Reliability, recovery, and reproducibility

**Reasoning recommendation: medium.** Use high only for a substantial schema,
security, or concurrency redesign.

Add documented backup/restore and integrity checks, environment diagnostics,
reproducible setup verification, retention monitoring, and failure-recovery tests.
The local manual workflow remains the baseline.

### 5.2 Optional scheduling and notifications

**Reasoning recommendation: medium.** The workflow is straightforward once failure
and privacy boundaries are defined.

Add recurring local execution only if the user explicitly requests automation.
Failures must be visible; cached/stale results must be labelled; no background task
may broaden data access or perform external actions beyond the approved workflow.

### 5.3 Optional provider decision gate

**Reasoning recommendation: high.** Cost, licensing, entitlements, definitions,
coverage, and operational dependency require careful comparison.

Evaluate a free or paid provider only against measured unresolved gaps. Document
what it adds, the free alternative, rate limits and terms, recurring cost, storage,
and a same-universe comparison before requesting approval. Do not add a provider,
API key, subscription, or OpenAI API integration automatically.

### 5.4 Optional deployment review

**Reasoning recommendation: high.** Moving a local financial-research application
to the cloud changes its privacy, persistence, authentication, and usage assumptions.

Remain local by default. Consider deployment only after an explicit request and a
separate review of secrets, authentication, database persistence, provider terms,
private/public access, operating cost, and recovery. The Streamlit **Deploy** button
is not part of the normal workflow.

## Definition of the planned final state

The completed system remains a research and ranking aid operated by the user through
Codex. It produces reproducible calculations, source-aware metrics, dated universe
versions, transparent historical comparisons, and appropriately qualified
evaluation results. It never portrays a ranking or backtest as certainty and never
connects to a brokerage or executes a transaction.
