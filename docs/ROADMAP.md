# Forward Roadmap — Steps 2.4 through 5

This is the authoritative implementation sequence after Step 2.3. It refines the
high-level roadmap in `V1_DESIGN.md`. If the documents differ, follow this file
unless the user explicitly approves a later revision.

The permanent priorities remain correctness, transparency, data quality,
reliability, maintainability, useful analysis, and then convenience. No step may
connect to a brokerage or execute a trade. Paid services, public deployment,
background automation, or OpenAI API integration require separate user approval.

### Implemented cross-cutting foundation — per-user customization

Each installation may use an ignored local profile and explicit user-approved
universe without modifying repository defaults. Guided configuration maps named
profile, horizon, and risk choices to visible component weights, validates thresholds
and membership, and assigns reproducible model and universe identifiers. Historical
runs retain their original configuration. This foundation does not perform automatic
stock discovery or bypass the Step 2.5 proposal and approval requirements.

### Implemented cross-cutting foundation — daily usability

The current dashboard provides a compact comparison with the previous completed run
using the same universe and scoring model, an export of all current rankings to CSV,
and read-only personalization guidance. The `stockrank morning` convenience command
runs the deterministic report and launches the dashboard in sequence. Safe Windows
and macOS update helpers preserve local preferences and runtime data. These conveniences
do not perform causal attribution, forward-return evaluation, or the full historical
analysis planned for Step 3.

SEC Company Facts synchronization uses persisted filing fingerprints for incremental
daily refreshes. Unchanged companies reuse normalized local facts, recent filings are
rechecked during user-started runs for 48 hours, and a seven-day full refresh provides
a correction safeguard. It preserves the declared SEC request ceiling and does not
introduce a scheduler, background process, or parallel request burst.

Before each numbered step or substep, the acting development agent must recommend **light**, **medium**, **high**, or **very high**
reasoning effort with a one-sentence explanation. Light is appropriate for simple
low-risk operational or explanatory work; roadmap implementation will normally use
medium or high according to the recommendation recorded for that step. Very high is
reserved for exceptional work where several material analytical, architectural, or
correctness risks interact. Each independently reviewable
substep ends with tests, relevant live validation, documentation, a privacy/source-
control check, user review, and a separate commit only when the user requests it.
After completing an independently reviewable substep, the agent pauses for the user's
green light before starting the next one unless the user explicitly authorizes a
larger group of substeps in advance.

## Pre-Step-3 integrity review — Fix Steps 1 through 6

These Fix Step numbers are a temporary remediation sequence and are separate from
the product-roadmap numbers below. They were created by a fine-toothed review of the
Step 1 foundation and an independent critique. Accepted findings are incorporated
here according to risk; suggestions are not requirements merely because they were
raised.

1. **Market-data freshness guardrails — complete.** Exclude unfinished same-day
   bars, reject over-age completed prices and fundamental fallbacks, make mixed
   ticker dates partial, preserve per-security freshness lineage, and avoid caching
   partial price responses as successful refreshes.
2. **Price-series integrity — complete.** Validate expected trading-session continuity before
   session-based momentum, volatility, moving-average, and drawdown calculations.
   Distinguish weekends and market holidays from suspicious gaps, define invalidation
   thresholds, preserve warnings, and test incomplete histories.
3. **Financial-ratio and percentile validity — complete.** Prevent invalid negative leverage
   and pathological return-on-equity values from being rewarded. Require defensible
   peer counts before assigning full-strength percentiles. Any changed scored inputs
   require an explicit new scoring-model version.
4. **Missing-data and score-meaning safeguards — complete.** Coverage remains separate
   from the conditional score, and missing values receive neither imputation nor an
   arbitrary penalty. Per-component coverage is displayed instead of imposing a
   redundant component cutoff; low overall coverage blocks favorable labels. Exact
   metric peer samples are exposed, and all recommendation language now states that
   results are relative to the selected universe rather than an absolute investment
   judgment. Stored legacy labels remain readable.
5. **Historical integrity and reproducibility.** Preserve SEC fact observation
   vintages or correction history, version deterministic formula definitions, retain
   a run reproducibility manifest, and strengthen comparable-run rules. Older runs
   lacking required lineage remain labelled limited rather than silently repaired.
6. **Maintainability and public presentation.** Correct the GitHub repository-name
   spelling through a coordinated remote/local migration, improve the README front
   door, add a representative dashboard image, establish an appropriate license and
   basic continuous integration after user review, and split large modules only when
   a clear responsibility boundary justifies the regression risk.

After Fix Step 6, return to the previously identified Issue 8 decision rather than
silently choosing it during remediation. Each Fix Step follows the same test,
validation, privacy, user-review, and user-authorized commit gates described above.

## Step 2.4 — SEC metric derivation and controlled provider promotion

Step 2.4 must not be implemented as a direct replacement of Yahoo fields with raw
Company Facts. SEC facts first need comparable financial periods and transparent
local calculations.

### 2.4A Financial snapshot and calculation layer — complete

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

### 2.4B Shadow provider comparison — in progress (per-runtime evidence gate)

**Reasoning recommendation: high.** Similar field names can represent different
periods or economic definitions, so comparisons require judgment and evidence.

Run SEC-derived and existing Yahoo summary metrics side by side without changing
production rankings. Classify comparisons as comparable, approximately comparable,
materially different, stale, missing, or structurally incomparable. Report coverage,
freshness, period alignment, fallback candidates, and material discrepancies by
metric, company, and sector.

Use configurable tolerances rather than silently treating every numeric difference
as an error. Complete at least three successful full-universe shadow runs linked to
complete production runs on separate underlying market-data dates before promotion.
Command time is not evidence: midnight, weekend, and duplicate same-close reruns
remain one date. Evidence counters are isolated by comparison-policy and universe
version so different personal universes are never combined. Review representative edge cases and all systematic or material
discrepancies. Shadow results must be clearly labelled and must not overwrite
existing run metrics.

The qualifying-date count is local runtime state and is intentionally not stored in
Git. Use `stockrank provider-shadow-status` or the dashboard to read the active
installation's current evidence count.

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

Before promotion, review whether the broad `Financials` convention incorrectly
groups structurally different businesses such as banks, payment networks, asset
managers, brokers, and diversified holding companies. Review REIT accounting
separately. Do not adopt sector-relative percentiles without adequate peer counts;
the current 50-stock universe is likely too small for reliable within-sector ranks.
Fundamental trend metrics may be evaluated as a versioned challenger, but must not be
inserted into the frozen production score without the same comparison and promotion
gate. Nested 1/3/6/12-month momentum exposure should likewise be documented and
tested before any alternative momentum definition is promoted.

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

Expanded universes must also identify foreign private issuers and other registrants
whose reporting does not fit the current 10-K/10-Q contract. Support for 20-F, 6-K,
10-KT, or other forms requires explicit period-normalization and coverage rules; do
not merely add form names to the allowlist or imply comparability with domestic
quarterly reporting.

## Step 3 — Historical intelligence and change attribution

Step 3 turns immutable daily runs into an auditable history, useful comparisons,
evidence-based explanations, and prospective outcome tracking. It is independently
valuable and does not require Step 4 to be undertaken later.

### 3.1 Historical record integrity

**Reasoning recommendation: high.** Every later historical feature depends on
knowing exactly which stored runs are complete and meaningfully comparable.

Audit that each run preserves universe membership, metric values and lineage,
component and overall scores, configuration and model version, data-quality labels,
provider/fallback state, and relevant prices and dates. Define explicit comparison-
eligibility rules. Older incomplete runs must be labelled as limited rather than
silently backfilled with information that was not stored at the time.

Acceptance requires deterministic integrity checks and a clear reason whenever two
runs cannot be compared.

### 3.2 Historical comparison engine

**Reasoning recommendation: medium.** The calculations are straightforward once
the Step 3.1 comparison contract is fixed, but version boundaries must remain clear.

Given two eligible runs, calculate rank and score changes, component changes,
top-candidate entries and exits, recommendation-label changes, and coverage gains or
losses. Support the previous comparable run and an explicitly selected earlier run.
Do not claim that an observed difference explains why it happened.

Acceptance requires reproducible Python comparisons with fixtures for ties, missing
metrics, changed coverage, and incompatible model or universe versions.

The comparison layer should also expose deterministic per-metric and per-component
contributions suitable for a later “Why is this ranked here?” view. Contribution
display must distinguish a raw metric, its peer-relative percentile, configured
weight, effective weight after missingness, and resulting score contribution.

### 3.3 Rule-based change attribution

Attribution is split because detecting an observable event and claiming that it
contributed to a score change are separate analytical problems.

#### 3.3A Observable event detection

**Reasoning recommendation: high.** Filing availability, restatements, provider
changes, and price movement must be detected from stored evidence and correct dates.

Identify relevant price movement, newly available filings, revised or restated
facts, provider/fallback changes, newly available or missing metrics, and model,
preference, or universe changes. Preserve the evidence linked to each event.

#### 3.3B Evidence-to-change explanations

**Reasoning recommendation: high.** Multiple simultaneous events and percentile
effects can make a single causal explanation unjustified.

Connect detected events to deterministic metric, component, and ranking changes
only when the stored calculations support the connection. Separate direct
mathematical contributions from contextual observations, and label residual or
ambiguous changes rather than inventing an explanation.

Acceptance for 3.3 requires evidence-linked explanations, explicit ambiguity, and
tests proving that unsupported causal language is not generated.

### 3.4 Prospective outcome tracking

Prospective tracking evaluates recommendations saved before outcomes were known; it
is useful even when optional historical backtesting is never pursued.

#### 3.4A Observation and maturity ledger

**Reasoning recommendation: high.** Recommendation dates, market calendars, and
incomplete horizons must be handled without prematurely reporting an outcome.

Register documented forward horizons such as one, three, six, and twelve months for
historical candidates. Preserve the original run and selection rule, and keep each
observation incomplete until its horizon has genuinely elapsed.

#### 3.4B Returns and benchmark context

**Reasoning recommendation: high.** Adjusted prices, acquisitions, delistings,
missing values, and benchmark alignment can materially change conclusions.

Calculate mature adjusted returns and appropriate broad-benchmark comparisons,
including excess return and relevant drawdown or risk context. Prefer group-level
summaries over anecdotes about individual winners, preserve source dates, and never
present correlation or a small sample as proof of predictive ability.

Daily recommendations with overlapping forward-return windows are not independent
observations. Store the raw observations, but report unique dates, unique securities,
overlap structure, and an appropriately conservative effective evidence count.
Statistical summaries must not treat hundreds of heavily overlapping daily windows
as hundreds of independent trials.

Acceptance for 3.4 requires deterministic date alignment, explicit incomplete and
unavailable states, corporate-action handling, and reproducible benchmark results.

### 3.5 Historical dashboard and reports

**Reasoning recommendation: medium.** Once historical calculations are tested,
this is primarily presentation and workflow work.

Add clearly labelled views for entries and exits, largest changes, evidence-based
attribution, outcome maturity, benchmark context, model versions, and universe
versions. Historical views must not mix incomparable runs without an explicit label
or filter, and the dashboard must not perform financial calculations itself.

Planned high-value views include a side-by-side comparison of two to five selected
stocks and a single-company deep dive showing current metrics, score contributions,
history, SEC lineage, data quality, and research notes. These are presentation layers
over tested calculations, not new scoring factors, and should be implemented only
after the underlying Step 3 data contracts they consume are complete.

Acceptance requires readable views backed by the tested Step 3 calculation layer,
with clear limited-data and not-yet-mature states.

## Post-Step-3 decision gate — provider and evaluation scope

Before optional Step 4, explicitly decide whether the current frozen data policy is
sufficient for the intended evaluation. A tested system is the combination of its
universe version, scoring-model version, metric definitions, and provider/fallback
policy; changing scored inputs later creates a new system rather than silently
upgrading the evaluated one.

Choose one documented path:

1. **Skip Step 4:** proceed directly to Step 5; no paid or additional provider is
   required for the normal research application.
2. **Evaluate the current system:** freeze the approved Step 2.4C provider policy
   and model version, then perform only the optional Step 4 work the user approves.
3. **Change providers before evaluation:** first establish the measured data gap,
   compare the proposed source with current sources on the same universe and dates,
   normalize definitions and periods, review ranking impact and cost/terms, and
   explicitly approve a new provider-policy and scoring-model version. Only then
   decide whether to evaluate that new version in Step 4.

A provider used only for unscored research, calendars, listing identity, or another
clearly isolated feature does not automatically create a scoring-model change. Any
provider that changes scored values, availability, fallback behavior, adjusted
prices, or historical membership requires versioned promotion and new validation.
Prior runs and evaluation results remain immutable and labelled with the exact
system they tested.

## Step 4 — Optional point-in-time evaluation in two honesty levels

Step 4 is an optional research track, not a requirement for a useful or complete
personal research application. After Step 3, proceed only following an explicit
user decision to investigate historical model behavior and completion of the
provider/data-sufficiency gate above. If evaluation is declined or the available
data cannot support an honest result, proceed directly to Step 5. Any evaluation
must distinguish a current-universe replay from a genuinely survivorship-aware
backtest and must never be presented as proof of future returns.

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

If repeated model experimentation is approved, establish development, validation,
and untouched holdout periods before examining results. Reusing the same history to
revise successive models creates research overfitting even when each individual
calculation is point-in-time. A frozen production model may run beside explicitly
labelled challenger models, and weight-sensitivity or rank-stability analysis should
report fragility rather than being portrayed as predictive proof.

### 4B Survivorship-aware backtesting

**Reasoning recommendation: very high.** This is the highest-risk analytical step in the
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
API key, subscription, or OpenAI API integration automatically. If a provider is
being considered to support optional Step 4, make that decision at the post-Step-3
gate rather than after completing an evaluation it could make obsolete. A provider
considered later remains a versioned future-system proposal: it never changes prior
runs or evaluation results in place, and any scored-data change must repeat the
relevant comparison, promotion, and validation gates.

### 5.4 Optional deployment review

**Reasoning recommendation: high.** Moving a local financial-research application
to the cloud changes its privacy, persistence, authentication, and usage assumptions.

Remain local by default. Consider deployment only after an explicit request and a
separate review of secrets, authentication, database persistence, provider terms,
private/public access, operating cost, and recovery. The Streamlit **Deploy** button
is not part of the normal workflow.

## Definition of the planned final state

The completed system remains a research and ranking aid operated manually or with a
capable local research agent. It produces reproducible calculations, source-aware
metrics, dated universe versions, and transparent historical comparisons. If the
optional evaluation track is undertaken, its results remain appropriately qualified.
The application never portrays a ranking or backtest as certainty and never connects
to a brokerage or executes a transaction.
