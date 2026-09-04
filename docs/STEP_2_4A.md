# Step 2.4A — SEC Financial Snapshot and Calculation Layer

Step 2.4A is complete. It converts normalized SEC Company Facts into immutable,
point-in-time financial snapshots without changing the production ranking model.
The current calculation version is `sec-financials-v1.1.0`. Earlier snapshots keep
their original version and remain immutable and readable.

## Period construction

- Annual observations require an SEC fiscal-period label of `FY` and a duration
  from 330 through 385 days, which includes conventional 52/53-week years.
- Direct quarters span 70 through 115 days.
- Cumulative Q2/Q3 and fiscal-year values are converted to discrete quarters only
  by subtracting the preceding cumulative value with the same fiscal start and
  unit. The derived span must itself be a valid quarter.
- TTM requires four contiguous discrete quarters, a common unit, gaps no longer
  than 14 days, and a combined span from 330 through 385 days.
- Weighted-average diluted shares use day-weighted cumulative-quarter subtraction
  and a day-weighted TTM average. Cumulative diluted EPS is not subtracted because
  changing denominators make that derivation unreliable.
- YTD keeps the latest valid Q1, Q2, or Q3 cumulative period.
- Instant facts and ratios require aligned reporting dates.

An explicit historical build first reconstructs each stable fact key from the latest
locally recorded observation at or before the requested cutoff. Later corrections
are not backdated, and legacy seed observations are known only from their recorded
seed time. Effective amendment or restatement selection then also requires filing
availability at or before the cutoff. A date-only CLI cutoff is interpreted as the
end of that day in the configured application timezone and stored in UTC.

## Calculation rules

- Growth is `(current - prior) / abs(prior)` for comparable annual or year-ago
  quarterly periods. Zero values and sign crossings are marked invalid rather than
  emitted as misleading extreme percentages.
- Free cash flow is operating cash flow minus nonnegative capital-expenditure
  payments, only for aligned periods.
- Gross, operating, net, and free-cash-flow margins require aligned periods and
  positive revenue.
- Return on equity is TTM net income divided by average beginning and ending
  stockholders' equity. Both equity dates must be within 14 days of the TTM
  boundaries, and average equity must be positive.
- Current ratio uses current assets and current liabilities from the same date and
  requires positive current liabilities.
- Industrial FCF, FCF margin, gross margin, operating margin, and current ratio are
  explicitly excluded for the `Financials` sector. ROE remains applicable.
- The broad `us-gaap:Revenues` fact takes precedence over the narrower
  `RevenueFromContractWithCustomerExcludingAssessedTax` alias when both describe
  the same filing context. This prevents non-contract revenue streams from being
  omitted at diversified companies.

Every stored metric has one of five quality states: `reported`, `derived`,
`missing`, `invalid`, or `excluded`. Missing stays missing. Lineage includes each
source fact's taxonomy concept, exact value/unit, period, accession, filing and
availability dates, precision, and SEC source URL.

## Persistence and isolation

Each build appends a snapshot header and metric rows to SQLite. Snapshot IDs are
immutable; attempting to reuse one fails. The schema retains the requested cutoff,
build time, company/sector, formula version, warnings, values, reasons, formulas,
and lineage.

Provider-shadow runs separately record the exact set of SEC formula versions and
manifests they consumed. Promotion evidence qualifies only when every configured
security has the same complete contract and that contract exactly matches the
currently supported version and manifest. Missing, mixed, unsupported, and legacy
contracts remain inspectable but are explicitly nonqualifying.

The calculation layer does not read, overwrite, or rescore `run_results`. At Step
2.4A completion, production model `v1.0.0` continued using the existing Yahoo
summary fields. The later `v1.2.0` production model retains those Yahoo fundamental
inputs while adding market-session, ratio-validity, and peer-sample guardrails; it
does not promote SEC metrics.
Promotion remains prohibited until Step 2.4B shadow comparison is complete and the
user explicitly approves a new model version in Step 2.4C.

## Acceptance result — 2026-08-27

The local five-year SEC dataset produced 50 of 50 snapshots with no build failures.
Selected metric coverage was:

| Metric | Available | Explicitly excluded |
| --- | ---: | ---: |
| Annual revenue | 50/50 | 0 |
| Latest discrete-quarter revenue | 49/50 | 0 |
| TTM revenue | 49/50 | 0 |
| TTM net income | 50/50 | 0 |
| TTM free cash flow | 37/50 | 5 Financials |
| Annual revenue growth | 50/50 | 0 |
| Annual earnings growth | 49/50 | 0 |
| TTM gross margin | 15/50 | 5 Financials |
| TTM net margin | 49/50 | 0 |
| TTM return on equity | 48/50 | 0 |
| Current ratio | 44/50 | 5 Financials |

Lower Gross Profit and capital-expenditure coverage reflects actual SEC concept and
period availability; those values were not inferred from unrelated fields. The
test suite covers non-calendar and 53-week years, cumulative-quarter subtraction,
TTM construction, point-in-time restatements, zero/sign-crossing growth, missing
inputs, sector exclusions, exact-decimal storage, and snapshot immutability.
