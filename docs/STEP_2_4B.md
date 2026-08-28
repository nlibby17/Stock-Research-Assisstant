# Step 2.4B — SEC/Yahoo Shadow Provider Comparison

Step 2.4B is in progress. The comparison infrastructure and first qualified
full-universe market-data date are complete, but promotion evidence requires three
distinct underlying market-data dates. Current progress is **1/3**.

## Purpose and isolation

This step measures whether SEC-derived Step 2.4A values and existing Yahoo summary
fields are sufficiently aligned for a future precedence decision. It does not
choose a source, fill production gaps, rescore a company, or modify `run_results`.
Production model `v1.0.0` remains unchanged.

Each run freezes its cutoff, universe scope, configuration version, both provider
values, freshness, SEC period and quality, tolerance values, classification,
difference, fallback candidate, and reason in immutable SQLite records. It also
records the linked production run, evidence date, qualification state, and reason.

## Versioned comparison policy

`config/provider_comparison.toml` defines the mappings and tolerances. The initial
matrix compares:

- Yahoo total revenue with SEC TTM revenue;
- Yahoo FCF and locally derived Yahoo FCF margin with SEC TTM FCF and FCF margin;
- Yahoo revenue and earnings growth with SEC quarterly year-over-year growth;
- Yahoo gross margin and profit margin with SEC TTM gross and net margins;
- Yahoo ROE with SEC TTM average-equity ROE;
- Yahoo current ratio with the latest aligned SEC current ratio;
- Yahoo debt/equity as structurally incomparable because no approved SEC debt
  substitute exists. Total liabilities are never relabelled as debt.

Yahoo summary fields do not expose their underlying statement period dates through
the normalized provider contract. Every mapping records that limitation. Growth,
FCF, FCF margin, and ROE begin as approximately comparable because provider formula
or averaging details are not fully exposed.

## Classification rules

Rows receive exactly one classification:

- `comparable`: a directly mapped pair is fresh and within strict absolute or
  relative tolerance;
- `approximately_comparable`: the mapping is definitionally approximate, or the
  difference exceeds strict tolerance but remains below at least one material
  threshold;
- `materially_different`: the difference exceeds both material thresholds;
- `stale`: a present Yahoo snapshot or SEC reporting period exceeds its configured
  age limit;
- `missing`: one or both values are unavailable or the SEC calculation is invalid;
- `structurally_incomparable`: the metric has no defensible mapping or is excluded
  by a sector convention.

Potential fallback directions are recorded only for later Step 2.4C review. They
are never applied by the shadow process.

## First eligible full-universe result — 2026-08-27

The first eligible `provider-shadow-v1.0.1` run stored 500 of 500 expected rows
across 50 companies and 10 mappings:

| Classification | Rows |
| --- | ---: |
| Comparable | 145 |
| Approximately comparable | 203 |
| Materially different | 30 |
| Missing | 52 |
| Structurally incomparable | 70 |
| Stale | 0 |

The main initial signal is FCF definition/freshness disagreement: 22 of 50 raw FCF
rows and 5 of 50 FCF-margin rows were materially different. The 70 structural rows
are intentional: 50 debt/equity rows have no approved SEC counterpart, and 20
industrial FCF/margin/liquidity comparisons are excluded for the five Financials
companies. Missing Gross Profit facts explain most gross-margin gaps. These are
review findings, not source-precedence decisions.

An earlier same-day `provider-shadow-v1.0.0` diagnostic run exposed a revenue-alias
priority defect: a narrower contract-revenue fact could be selected ahead of broad
total revenue when both appeared in one filing context. Step 2.4A was corrected and
versioned as `sec-financials-v1.0.1`; the shadow policy was versioned in parallel.
The diagnostic run remains immutable for audit purposes but does not count toward
the current three-date promotion evidence.

The dashboard reports classifications by metric and sector and lists every material
company-level discrepancy with both values, relative difference, SEC period end,
and alignment note.

## Remaining acceptance work

1. Run the normal daily data workflow on two additional market-data dates.
2. Record one successful full-universe shadow run on each new date.
3. Review systematic discrepancies and representative edge cases across all three
   dates.
4. Confirm that comparison tables remain isolated from rankings and document the
   final Step 2.4B assessment.

Only then may the user decide whether to begin Step 2.4C. A comparison qualifies
only when it follows a recently completed production run containing the exact
configured universe, with a price date for every stock and one consistent market-data
date. Same-close, after-midnight, and weekend reruns are useful for testing but do
not advance the distinct-date requirement. Evidence from a different universe
version is tracked separately and cannot advance the active universe's count. If the production ranking fails, the
daily workflow skips the shadow step rather than attaching evidence to an older run.
