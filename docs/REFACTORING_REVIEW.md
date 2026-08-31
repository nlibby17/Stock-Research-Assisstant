# Refactoring Review and Decision Ledger

This document is the authoritative record for the pre-Step-3 code-structure review.
It is intentionally separate from the product roadmap: refactoring must preserve
application behavior and does not advance or redefine a product-roadmap step.

## Objective

Collect independent recommendations across the application's largest subsystems,
verify every claim against the repository, and make an explicit decision on every
proposal before changing production code. No recommendation is accepted merely
because an external model proposed it, and no refactoring implementation begins
until the complete planned review has been analyzed and approved.

## Frozen baseline

- Baseline commit: `38b08eb` (`Complete public documentation and CI setup`).
- Baseline verification: 129 local tests passed; GitHub CI passed on Windows,
  macOS, and Linux.
- The application is operational on Windows 10/11, current macOS, and the tested
  macOS 11 Python 3.12/PyArrow compatibility path.
- Current large modules at intake: `cli.py` 1,757 lines, `storage.py` 1,748 lines,
  `dashboard.py` 1,246 lines, and `data/sec.py` 1,143 lines.
- Runtime history, personal configuration, scoring semantics, provider policy,
  command behavior, reports, and dashboard behavior are not refactoring targets.

If product behavior changes intentionally, that work must be proposed and approved
separately from this ledger.

## Required process

1. **Collect:** review one cohesive subsystem at a time in a fresh external-model
   conversation. Preserve every concrete recommendation and every explicit
   do-not-refactor recommendation in this ledger.
2. **Verify:** inspect the named functions, dependencies, callers, tests, output
   contracts, and repository history. Recalculate all quoted counts and estimates.
3. **Decide:** classify every item as `ACCEPT`, `MODIFY`, `DEFER`, or `REJECT`, with
   repository evidence and a concise reason. `INTAKE` means it has not yet been
   evaluated; it is not approval.
4. **Synthesize:** resolve overlaps and dependency order across all subsystem
   reviews. Produce one bounded implementation plan and an explicit no-change list.
5. **Approve:** obtain user approval for the complete analyzed plan before editing
   production code.
6. **Implement:** make small behavior-preserving slices. Add characterization tests
   before an extraction when existing tests do not lock down its contract.
7. **Validate:** after every slice, run focused tests and the full suite. Before each
   authorized commit, run lint, cross-platform-relevant checks, privacy/staging
   checks, and review the diff. Verify GitHub CI after each push.

Refactoring commits must not be combined with scoring changes, schema changes,
provider promotion, new features, or visual redesigns. A smaller file is not itself
evidence of a better design.

## Decision status vocabulary

- `INTAKE`: recorded exactly enough for later verification; no judgment yet.
- `ACCEPT`: verified and approved substantially as proposed.
- `MODIFY`: the underlying problem is verified, but the boundary or solution changes.
- `DEFER`: potentially valid but not justified before the named future trigger.
- `REJECT`: unsupported, incorrect, over-engineered, or contrary to project goals.
- `IMPLEMENTED`: completed after approval with tests and commit evidence recorded.

Every item must eventually leave `INTAKE`. `IMPLEMENTED` is unavailable until every
planned review round has been collected, analyzed, and the synthesized plan approved.

## Planned review rounds

| Round | Scope | External source | State |
|---|---|---|---|
| R1 | CLI commands and orchestration | Qwen3-Coder-Next | Analyzed; decisions recorded below |
| R2 | Dashboard composition and presentation helpers | Qwen3-Coder-Next | Analyzed; decisions recorded below |
| R3 | Storage, migrations, and persistence boundaries | Codex internal two-pass | Analyzed; decisions recorded below |
| R4 | SEC transport, identity, and submissions ingestion | Codex internal two-pass | Pending |
| R5 | SEC financial calculations and refresh orchestration | Codex internal two-pass | Pending |

Additional rounds require a concrete reason discovered during verification. They are
not created merely to review every small module.

## R1 intake — CLI commands and orchestration

### Review context

- External model: `Qwen/Qwen3-Coder-Next` through Hugging Face Chat.
- Source bundle: `AGENTS.md`, `README.md`, `pyproject.toml`, `cli.py`,
  `command_parser.py`, `daily_workflow.py`, and `tests/test_cli.py`.
- External instruction: analysis only; maximum five evidence-based recommendations;
  preserve behavior and identify code that should remain unchanged.
- All quoted line counts, duplication estimates, risk claims, test-coverage claims,
  and proposed interfaces below remain external assertions until verified locally.

### Verified R1 baseline and source reliability

- `cli.py` is 1,757 lines with 20 top-level `command_*` handlers, eight private
  top-level helpers, and no nested functions. The external report's claims of more
  than 2,000 lines, 35 handlers, three helpers, and one nested function are incorrect.
- `tests/test_cli.py` contains nine tests, not 32. It directly exercises setup-check,
  parser wiring, daily-workflow composition, morning/dashboard behavior, and the
  isolated PyArrow check. It does not execute the SEC sync, SEC financial build,
  provider-shadow, storage-maintenance, configuration-check, validation, configure,
  run, or research-import handler bodies.
- Qwen's architectural proposals remain useful hypotheses, but its repeated claims
  of existing coverage and negligible/no behavior risk are not reliable. Missing
  characterization tests must be treated as a prerequisite, not post-extraction
  cleanup.
- The line-count target in the external conclusion is discarded. File shrinkage is
  not an acceptance criterion; clearer ownership and safer tests are.

### CLI-01 — provider health and SEC sync orchestration

- **Status:** `MODIFY`
- **External proposal:** create `stockrank/providers.py` containing command-agnostic
  identity, submissions, Company Facts, and financial-snapshot orchestration. Return
  typed `ProviderSyncResult` data to thin CLI formatters.
- **Named scope:** `command_sec_health`, `command_sec_filings_sync`,
  `command_sec_facts_sync`, and `command_sec_financials_build`.
- **External rationale:** repeated client construction, universe traversal, fetching,
  persistence, provider-health recording, and summary output allegedly account for
  roughly 500–600 extractable lines.
- **External rating:** do now; difficulty 4/10; high confidence.
- **Verification required:** determine whether the commands actually share one
  stable lifecycle, distinguish orchestration from provider/domain policy, identify
  existing helpers in `data/sec.py`, `sec_refresh.py`, and `sec_financials.py`, and
  verify output, exception, cache, and health-recording contracts.
- **Verified evidence:** the four named handlers span 622 lines, and SEC-related
  command/status code occupies a substantial contiguous portion of `cli.py`.
  However, their lifecycles are not identical. `command_sec_health` performs one
  identity check; filing sync handles predecessor identities and filing replacement;
  Company Facts sync owns incremental refresh decisions, fingerprints, timing, and
  state writes; financial build is a local calculation over stored facts with no SEC
  request. All mutate storage or provider-health state, contrary to the external
  report's no-state-mutation characterization.
- **Boundary finding:** transport/parsing already belongs to `data/sec.py`, refresh
  policy to `sec_refresh.py`, and deterministic formulas to `sec_financials.py`. A
  generic `providers.py` would misleadingly mix SEC-specific application workflows
  while excluding the Yahoo pipeline. Moving 500–600 lines into it would primarily
  relocate complexity, and one universal `ProviderSyncResult` cannot cleanly express
  filing coverage, fact-refresh diagnostics, and financial-metric coverage.
- **Decision:** `MODIFY`. Preserve the valid goal of removing SEC application
  orchestration from the CLI, but defer the exact boundary to R4 and R5. Synthesis
  should consider narrowly named SEC operation/service boundaries with distinct typed
  results and thin CLI output adapters. Before implementation, add characterization
  tests for exit codes, output order, partial scopes, failures, health records, cache
  states, and storage mutations for each command.

### CLI-02 — provider-promotion evidence classification

- **Status:** `MODIFY`
- **External proposal:** create `stockrank/promotion.py` with a typed
  `PromotionEvidence` result and an `evaluate_promotion_evidence(...)` function.
- **Named scope:** the eligibility and reason-building portion of
  `command_provider_shadow_run`.
- **External rationale:** promotion qualification is business policy rather than CLI
  formatting and should be independently testable.
- **External rating:** do now; difficulty 3/10; high confidence.
- **Verification required:** inspect existing boundaries in
  `provider_comparison.py` and `storage.py`, enumerate every evidence invariant,
  verify side effects and chronology rules, and identify missing characterization
  tests before any move.
- **Verified evidence:** lines 1424–1491 of `cli.py` implement a cohesive promotion-
  evidence policy with many independent rejection reasons: scope, production-run
  status/provider/universe, completion chronology, refresh-failure warnings, maximum
  link age, exact result membership, missing or mixed price dates, run/date alignment,
  stale comparison rows, and completeness. Existing comparison tests cover metric
  classification and persistence of already-constructed evidence, but not this
  qualification decision tree.
- **Boundary finding:** the policy should leave CLI glue, but Qwen's proposed function
  accepts `Storage`, an unfinished comparison-run concept, and a misspecified universe
  type. That would hide database reads rather than create a deterministic unit. The
  current `provider_comparison.py` is otherwise calculation-focused; whether the
  evaluator belongs there or in a narrowly named `provider_evidence.py` will be
  resolved during synthesis.
- **Decision:** `MODIFY`. Extract a pure typed evaluator that receives explicit
  production-run metadata, stored results, comparison status/rows, expected identity,
  and cutoff values, then returns qualified/date/run/reason. Keep retrieval,
  persistence, health recording, and printing in an application/CLI boundary. Add
  parameterized characterization tests for every qualification and rejection path
  before moving the policy.

### CLI-03 — storage inspection and cleanup

- **Status:** `DEFER`
- **External proposal:** create `stockrank/storage_cleanup.py` with typed inspection
  and cleanup results consumed by thin CLI handlers.
- **Named scope:** `command_storage_status`, `command_storage_clean`, and associated
  file-size helpers.
- **External rationale:** retention and filesystem/row-count inspection form a
  storage-administration responsibility distinct from CLI printing.
- **External rating:** later; difficulty 2/10; high confidence.
- **Verification required:** locate the actual retention policy and tests, identify
  platform-sensitive path behavior and destructive boundaries, and determine whether
  two small handlers justify a new module.
- **Verified evidence:** the two handlers total 89 lines, with 13 lines of size
  helpers. Database cleanup is already isolated in `Storage.cleanup_database`, while
  filesystem size accounting, retention planning, display, and deletion remain in
  the CLI. No test currently executes the filesystem-retention portion.
- **Risk finding:** cleanup is destructive when `--apply` is used, so the external
  report's minimal-risk assessment is too optimistic. Any extraction should first
  model a bounded cleanup plan separately from application, verify protected names
  and permitted runtime roots, and test Windows/macOS path and timestamp behavior.
- **Decision:** `DEFER` until R3. The storage review must decide whether a cohesive
  `runtime_maintenance` boundary is justified across database and filesystem policy.
  Implement only if R3 confirms that boundary or a second consumer/expanded policy
  creates a real need; otherwise keep the small handlers in the CLI.

### CLI-04 — configuration validation formatting

- **Status:** `REJECT`
- **External proposal:** create `stockrank/validation.py` to centralize conversion of
  settings validation warnings/errors into user-facing output.
- **Named scope:** `command_setup_check` and `command_config_check`.
- **External rationale:** allegedly duplicated validation and formatting could drift.
- **External rating:** later; difficulty 2/10; medium confidence.
- **Verification required:** compare the commands' actual purposes and output
  contracts, inspect existing validation ownership in `config.py`, and reject the
  extraction if it only moves a few lines without creating a coherent abstraction.
- **Verified evidence:** both commands call the existing `validate_settings`, but
  they intentionally have different contracts. Setup-check verifies project files,
  a crash-isolated PyArrow import, SEC identity configuration, database creation, and
  runtime writability. Config-check reports active scoring/universe policy and can
  perform live Yahoo/SEC coverage checks. Only small warning/error print loops are
  superficially duplicated.
- **Decision:** `REJECT`. A generic formatter would move a few lines while obscuring
  stdout/stderr ordering and the two commands' distinct purposes. Validation rules
  already have one owner in `config.py`; no additional module is justified.

### CLI-05 — daily and morning workflow definitions

- **Status:** `REJECT`
- **External proposal:** create `stockrank/workflows.py` to build daily/morning step
  definitions and conditional skip rules, leaving timing and execution in
  `daily_workflow.py`.
- **Named scope:** `command_daily_report`, `command_morning`, their step definitions,
  and shadow-step skip decisions.
- **External rationale:** workflow composition is distinct from CLI glue and from the
  existing workflow runner.
- **External rating:** do now; difficulty 3/10; high confidence.
- **Verification required:** determine whether this would split one cohesive workflow
  across two modules, inspect the current `daily_workflow.py` extraction and tests,
  and measure whether a new module clarifies or obscures dependency direction.
- **Verified evidence:** `command_daily_report` is a 36-line composition root and
  `command_morning` is a 15-line wrapper. The generic runner already lives in
  `daily_workflow.py`, whose contract explicitly says the workflow is assembled by
  the command layer. Moving command-handler references into `workflows.py` would
  either import back into `cli.py` and create a cycle or require an artificial
  callback registry. The shadow-skip rule belongs to execution state and is already
  tested in the runner path.
- **Decision:** `REJECT`. Keep step composition at the CLI boundary and timing,
  failure handling, skip behavior, final paths, and elapsed reporting in
  `daily_workflow.py`. Revisit only if a second real workflow with meaningfully shared
  composition appears; hypothetical future commands are not sufficient.

### R1 external preserve/do-not-do recommendations

The external preserve/do-not-do proposals resolve as follows:

- **Accept:** keep `command_parser.py` and `daily_workflow.py` structurally unchanged
  during R1; both have cohesive responsibilities and relevant tests.
- **Accept:** keep `main()` and `build_parser()` as minimal CLI wiring.
- **Modify:** keep the PyArrow and interactive-prompt helpers with their current
  setup/configuration responsibilities. Move size-formatting/file-size helpers only
  if R3 later approves a runtime-maintenance boundary.
- **Accept:** keep the small `command_research_import` handler in the command layer.
- **Accept:** do not create one module per command.
- **Accept as hard invariants:** do not change scoring logic, workflow order, output
  semantics, or skip behavior during refactoring.

### R1 decision summary

| ID | Decision | Implementation consequence |
|---|---|---|
| CLI-01 | `MODIFY` | Coordinate a narrower SEC operation boundary with R4/R5; add command characterization tests first |
| CLI-02 | `MODIFY` | Plan a pure provider-evidence evaluator with exhaustive branch tests |
| CLI-03 | `DEFER` | Let R3 determine whether runtime maintenance deserves a module |
| CLI-04 | `REJECT` | Keep validation ownership in `config.py` and command-specific output in the CLI |
| CLI-05 | `REJECT` | Preserve the existing command-composition/generic-runner boundary |

## R2 intake — dashboard composition and presentation helpers

### Review context

- External model: `Qwen/Qwen3-Coder-Next` through Hugging Face Chat.
- Source bundle: `AGENTS.md`, `README.md`, `pyproject.toml`, `dashboard.py`,
  `presentation.py`, `summaries.py`, and the three corresponding test modules.
- External instruction: analysis only; maximum five evidence-based recommendations;
  preserve the approved visual design and Streamlit behavior.

### Verified R2 baseline and source reliability

- `dashboard.py` is 1,246 lines, not the external report's claimed 2,200-plus
  lines. `presentation.py` is 192 lines and `summaries.py` is 54 lines.
- The supplied dashboard, presentation, and summary tests contain 12 tests, not
  nine. The five dashboard tests inspect source text and theme configuration; they
  do not execute the Streamlit page. The seven helper tests execute deterministic
  behavior in `presentation.py` and `summaries.py`.
- The report's responsibility-map line ranges are materially wrong. Page styling
  alone occupies lines 26–275, settings/storage acquisition begins at line 276,
  and rendering continues through line 1,246. Its compressed ranges cannot be used
  to estimate extraction size or identify dependencies.
- `load_settings` performs local dotenv, TOML, and universe-file reads. It does not
  make a network request. No `st.cache_resource` or `st.cache_data` usage exists in
  the supplied dashboard or elsewhere under `src/stockrank`, contrary to the
  report's assertion that cached storage behavior was evident.
- A 20-iteration local diagnostic of settings loading, idempotent database
  initialization, latest-run lookup, and 50-result loading measured a median of
  approximately 133 ms. Repeated initialization is real but not evidence of a
  user-visible performance problem, and it does not justify caching report data.
- The report contains contradictory conclusions: it labels state caching “do now”
  while ultimately recommending no refactor, describes Streamlit-rendering
  functions as side-effect-free, and claims comprehensive dashboard protection
  despite acknowledging that the page is never executed by its tests.
- Multilingual token substitutions and malformed punctuation do not alter the
  proposals, but reinforce that the prose and confidence ratings are not evidence.
  All recommendations below are decided from repository behavior instead.

### DASH-01 — cache state acquisition and report results

- **Status:** `REJECT`
- **External proposal:** create `dashboard_state.py` and use
  `@st.cache_resource` to cache a tuple containing the latest run and its results by
  database path.
- **External rationale:** settings and storage work allegedly cause repeated network
  and file I/O on every interaction; the cache was described as session-scoped and
  behavior-preserving.
- **Verified evidence:** installed Streamlit 1.62 documents `cache_resource` as a
  global cache by default, shared across users, sessions, and reruns, with no default
  expiry. It is intended for singleton resources; `cache_data` is the corresponding
  data cache. Qwen's sample passes only the database path, ignores its optional
  `run_id`, and therefore cannot detect a newly written latest run.
- **Behavior risk:** the proposal could retain an old run and mutable result list
  after a morning report or research import changes the database. It would also
  remove the current property that every rerun reads the latest stored report. The
  proposed test checks cache identity rather than dashboard freshness and would lock
  in the wrong behavior.
- **Decision:** `REJECT`. Continue reading current report data on each rerun. A much
  narrower cache of only the stateless `Storage` construction/idempotent schema
  initialization may be reconsidered if measured interactive latency becomes a real
  problem, but that would be a performance task—not the proposed state extraction.

### DASH-02 — chart-configuration module and dataclass

- **Status:** `REJECT`
- **External proposal:** create `chart_config.py` with a `ScoreChartConfig` dataclass
  and a generalized bar-chart builder shared by candidate and factor charts.
- **External rationale:** the two charts allegedly duplicate 80 percent of their
  encodings, domains, tooltips, padding, and color logic.
- **Verified evidence:** the candidate chart and per-company factor chart have
  different data shapes, sorting, color behavior, tooltips, labels, and heights.
  Their meaningful overlap is limited to a 0–100 clamped scale, bar corner radii,
  axis posture, and padding. Candidate gradient generation is not duplicated.
- **Decision:** `REJECT`. A configurable dataclass and generalized builder would
  require more parameters than the small shared literal configuration warrants and
  would make the approved chart details harder to audit. Keep both short Altair
  declarations beside the data they visualize.

### DASH-03 — personal-configuration UI module

- **Status:** `REJECT`
- **External proposal:** create `ui_sections.py` for the saved-report configuration
  notice and the personalization expander.
- **External rationale:** the report claims that these sections appear twice and
  duplicate structure and CSS.
- **Verified evidence:** the saved-report notice appears once and conditionally
  explains a mismatch. The personalization expander appears once and contains
  platform-specific instructions. They share neither content nor rendering logic;
  both merely use dashboard-wide styles. A function that calls `st.markdown`,
  `st.expander`, and `st.tabs` is not side-effect-free.
- **Decision:** `REJECT`. Moving these two order-sensitive blocks to a new module
  would relocate, not remove, Streamlit side effects and would obscure the approved
  page order without establishing reuse.

### DASH-04 — preserve existing deterministic helper boundaries

- **Status:** `ACCEPT`
- **External proposal:** keep `ranking_change_summary`, `score_breakdown`, and CSV
  construction in `presentation.py`, and keep sector aggregation/member selection in
  `summaries.py`.
- **Verified evidence:** these functions are deterministic, imported by the
  dashboard, and covered by direct unit tests. Neither helper module imports
  Streamlit or storage.
- **Decision:** `ACCEPT`. These are sound dependency boundaries. This does not accept
  the report's broader claim that no pure formatting helper may ever leave
  `dashboard.py`; final synthesis may consolidate already-pure presentation helpers
  into the existing module without changing rendering order.

### DASH-05 — reject a wholesale controller/view abstraction

- **Status:** `ACCEPT`
- **External proposal:** do not introduce a `DashboardController`, templating layer,
  or general view abstraction around the full Streamlit page.
- **Verified evidence:** rendering order is meaningful in Streamlit, and the current
  page is a single report surface rather than multiple interchangeable views. No
  second consumer exists for its section-level rendering.
- **Decision:** `ACCEPT` the conclusion, not all supporting claims. End users would
  not literally call a controller, external CSS would not require Jinja, and the
  report's memory-bloat argument is unsupported. The justified invariant is simply
  to avoid a broad abstraction with no consumer or demonstrated benefit.

### R2 characterization-test proposals

| ID | Decision | Verified disposition |
|---|---|---|
| DASH-T01 — cache state once per session/rerun | `REJECT` | It would enforce stale-data behavior and conflates one script execution with multiple Streamlit reruns |
| DASH-T02 — exclude ineligible rows from historical top lists | `ACCEPT` | `_ranked_candidates` explicitly owns this contract, but the current ranking-change test uses only eligible rows |
| DASH-T03 — empty sector-leader input | `DEFER` | The current pure iteration naturally returns an empty list; add the edge test only if `summaries.py` is changed |
| DASH-T04 — execute gold-gradient behavior | `MODIFY` | If the pure helper moves or chart styling changes, test count, endpoints, valid hex output, and monotonic lightening rather than only string presence |
| DASH-T05 — exercise every legacy relative-status mapping | `ACCEPT` | The current test covers one mapped value and one pass-through value; the complete finite mapping is cheap to preserve |

### R2 local synthesis note — pure dashboard formatting helpers

The external report overlooked a narrower, evidence-based candidate: `preference_label`,
`score_tier`, `financial_markdown`, and `gold_gradient` are pure formatting functions
defined inside the otherwise executable Streamlit page. They cannot be imported for
ordinary unit tests without running page initialization. During cross-review
synthesis, consider moving only these helpers into the existing `presentation.py`
boundary and adding direct tests. Do not move `metric_help_key`, `accent_notice`, or
`change_badges` merely for line reduction; they are coupled to Streamlit or the
dashboard's HTML/CSS contract.

### R2 decision summary

| ID | Decision | Implementation consequence |
|---|---|---|
| DASH-01 | `REJECT` | Preserve fresh database reads; do not cache the latest run/results as a resource |
| DASH-02 | `REJECT` | Keep the two distinct Altair declarations local and explicit |
| DASH-03 | `REJECT` | Keep the one-off configuration blocks in page order |
| DASH-04 | `ACCEPT` | Preserve the current deterministic presentation and summary boundaries |
| DASH-05 | `ACCEPT` | Do not add a broad controller/view or templating abstraction |

## R3 intake — storage, migrations, and persistence boundaries

### Frozen internal reviewer instruction

Act as an independent, clinical architecture and refactoring reviewer. Analyze the
repository directly but do not edit production code, generate replacement code, add
features, or change persistence behavior. Focus on `storage.py`, its models, all
callers, migration behavior, cleanup behavior, and direct or indirect tests. Preserve
the SQLite schema, stored values, timestamps, ordering, transaction behavior,
cross-platform support, and public command/report/dashboard contracts. File size alone
is not evidence of a problem. Identify at most five cohesive recommendations, cite
exact symbols and evidence, state a proposed boundary, risks, prerequisite tests,
priority, difficulty, and confidence, and explicitly identify code that should stay.
If a finding is a product bug rather than a refactor, label it separately rather than
smuggling a behavior change into the recommendation.

The following reviewer output was frozen before adjudication. `INTAKE` records a
proposal, not approval.

### STORE-01 — explicit schema and ordered migration boundary

- **Status:** `INTAKE`
- **Reviewer proposal:** move current-schema DDL, schema-version inspection, additive
  upgrades, and backfills out of `Storage.initialize` into a narrowly owned schema
  module with explicit ordered migration steps. `Storage.initialize` should delegate
  to that boundary without changing the resulting version-10 schema.
- **Evidence:** `Storage.initialize` spans lines 50–415. It creates the full current
  schema, probes four tables for selected columns, applies conditional `ALTER TABLE`
  statements, runs two data backfills, and unconditionally writes
  `schema_version = 10`. The stored version is never read to select or reject a
  migration path.
- **Proposed interface:** a small migration runner accepting an existing SQLite
  connection, the supported schema version, and an ordered immutable migration
  registry. Keep transaction and connection ownership in `Storage`.
- **Claimed benefit:** make upgrades auditable and testable independently from every
  persistence method, prevent future schema changes from enlarging one 366-line
  method, and establish an explicit response to a database newer than the running
  application.
- **Primary risks:** incorrect version baselines, partial upgrades, changed DDL,
  backfill reordering, or rejection of databases previously tolerated.
- **Prerequisite tests:** exact fresh-schema inventory; idempotent initialization;
  representative legacy upgrades for every existing conditional column/backfill;
  rollback/failure behavior; and a deliberate future-version case.
- **Reviewer rating:** priority high; difficulty 7/10; confidence high.

### STORE-02 — split persistence ownership by cohesive aggregate behind a facade

- **Status:** `INTAKE`
- **Reviewer proposal:** retain the caller-facing `Storage` API initially, but move
  persistence implementations into a small number of cohesive internal aggregates:
  cache/market data, analysis runs and research, SEC filings/facts/financials, and
  provider comparison. Each aggregate should own its SQL and model row conversion.
- **Evidence:** `Storage` contains 48 methods and imports 11 persisted model types.
  The method clusters have few cross-cluster dependencies, while SEC and provider-
  comparison save/load methods individually span 44–110 lines.
- **Proposed interface:** a compatibility facade that delegates to connection-aware
  repository objects or functions. Do not require immediate caller rewrites and do
  not create one module per table or method.
- **Claimed benefit:** reduce merge pressure in one central file and align SQL,
  conversion, and tests with actual persistence aggregates.
- **Primary risks:** transaction-boundary drift, circular imports, a facade that only
  adds forwarding boilerplate, and overlap with the later R4/R5 SEC reviews.
- **Prerequisite tests:** full round trips and negative/immutability behavior for
  every moved aggregate; transaction and connection-closure tests; exact ordering;
  and an unchanged caller-facing API during the first slice.
- **Reviewer rating:** priority medium; difficulty 8/10; confidence medium-high.

### STORE-03 — separate historical-comparison policy from storage queries

- **Status:** `INTAKE`
- **Reviewer proposal:** move the deterministic eligibility decision in
  `run_comparison_eligibility` into the reproducibility/domain boundary. Storage
  should retrieve explicit run metadata and observed membership, then pass those
  values to a pure evaluator. Preserve `previous_comparable_run_assessment` as the
  caller-facing search operation until its consumers are migrated deliberately.
- **Evidence:** lines 782–838 combine SQL reads with completion, chronology,
  point-in-time date, manifest, calculation-contract, and exact-universe policy.
  `reproducibility.py` already owns manifest validation and stable fingerprints.
- **Proposed interface:** typed comparison inputs plus a pure result containing
  eligibility and ordered reasons; no database handle inside the evaluator.
- **Claimed benefit:** make every rejection branch directly testable and keep
  financial-history policy out of the SQLite adapter.
- **Primary risks:** changing reason wording/order, mishandling missing rows, or
  increasing query count while separating retrieval from evaluation.
- **Prerequisite tests:** parameterized coverage of every current rejection reason,
  duplicate-reason behavior, missing runs/manifests, membership mismatches, candidate
  search order, and exact report/dashboard limitation text.
- **Reviewer rating:** priority medium; difficulty 5/10; confidence high.

### STORE-04 — remove or clarify dead and misleading persistence API surface

- **Status:** `INTAKE`
- **Reviewer proposal:** after a global caller audit, remove or deprecate storage
  methods and arguments with no production effect rather than carrying misleading
  compatibility indefinitely.
- **Evidence:** `provider_comparison_full_universe_dates` accepts `timezone_name` but
  never reads it. `previous_run` has no repository caller, and
  `previous_comparable_run` is used by a test but no production caller; production
  uses the assessment-returning variant.
- **Proposed interface:** remove the unused timezone argument from internal callers
  and tests, and either remove the two unused convenience methods or explicitly
  retain and document them as supported API.
- **Claimed benefit:** reduce false signals about timezone conversion and historical
  comparison behavior.
- **Primary risks:** undocumented external Python consumers are possible even though
  this is an application rather than a published storage library.
- **Prerequisite tests:** full caller search, public-documentation search, and the
  complete suite after any signature or method removal.
- **Reviewer rating:** priority low; difficulty 2/10; confidence high.

### STORE-05 — explicit runtime-maintenance plan/apply boundary

- **Status:** `INTAKE`
- **Reviewer proposal:** resolve deferred CLI item CLI-03 by creating a cohesive
  runtime-maintenance boundary that inventories database/runtime sizes and produces
  an immutable cleanup plan before applying it. Keep formatting and confirmation in
  the CLI and database row deletion in storage-owned code.
- **Evidence:** `command_storage_status` and `command_storage_clean` contain runtime
  traversal, time cutoffs, protected filenames, display, and deletion. Only
  `Storage.cleanup_database` has a dry-run/apply test; no test executes filesystem
  selection or deletion. The operation is intentionally destructive only with
  `--apply`.
- **Proposed interface:** typed inventory and cleanup-plan values containing explicit
  validated paths under the configured runtime root, plus separate preview and apply
  operations. Applying a plan must revalidate scope and protected names.
- **Claimed benefit:** make destructive scope testable on Windows and macOS, keep the
  default dry run, and prevent future retention growth from accumulating in CLI glue.
- **Primary risks:** time-of-check/time-of-use drift, symlink/path escape, changed
  cutoff semantics, or making deletion appear safer than it is.
- **Prerequisite tests:** dry-run/apply parity; exact cutoff boundaries; protected
  files; database/WAL size accounting; symlink or resolved-path containment;
  platform timestamp behavior; and no deletion outside a temporary runtime root.
- **Reviewer rating:** priority medium-high; difficulty 5/10; confidence high.

### R3 adjudication baseline

- `storage.py` is 1,748 lines with 48 methods. Its major implementation clusters
  are schema/upgrades, market/cache data, analysis history, SEC persistence,
  provider comparison, and maintenance.
- Storage behavior is exercised outside `tests/test_storage.py`: pipeline,
  reporting, SEC-financial, and provider-comparison tests cover important caller and
  round-trip contracts. Focused adjudication must include those tests rather than
  treating the 13 direct storage tests as the whole persistence surface.
- Git history contains schema versions 1 through 10 across ten schema-changing
  commits. The current initializer does not use that history as an ordered migration
  registry; it conditionally repairs only selected later additions.
- A temporary-database diagnostic changed recorded `schema_version` to `999`, called
  `initialize`, and observed it silently rewritten to `10`. This verifies the future-
  version compatibility risk without touching runtime data.
- Global caller and documentation searches confirm that `timezone_name` is unused
  inside `provider_comparison_full_universe_dates`, `previous_run` has no caller, and
  `previous_comparable_run` has only one test caller. Git history shows the timezone
  argument became obsolete when evidence counting changed from timestamp conversion
  to already-normalized `evidence_date` values.
- The current runtime-file cleanup walks only direct child files in three explicit
  runtime directories and requires `--apply`. No path-escape failure was found, but
  its selection and deletion contracts have no executing tests.

### STORE-01 adjudication — explicit schema and ordered migration boundary

- **Decision:** `MODIFY`
- **Accepted problem:** schema creation, compatibility repair, data backfills, and
  version publication have outgrown `Storage.initialize`. Unconditionally replacing
  a higher version is unsafe, and future changes need a version-aware owner.
- **Modification:** do not begin by inventing clean sequential semantics for every
  historical database. First extract the exact version-10 fresh-schema DDL and
  existing compatibility repairs into `storage_schema.py`, preserve their order,
  and add a version reader that refuses a version newer than the application without
  mutating it. Then use actual historical schemas from Git to characterize supported
  versions 1–9 before converting repairs into an ordered registry.
- **Implementation gate:** fresh version-10 schema inventory must match exactly;
  repeated initialization must be idempotent; representative version-1 through
  version-9 fixtures must retain rows through upgrade; all current backfills must be
  verified; and a version greater than 10 must fail clearly without changing the
  database. No automatic runtime-database upgrade should be tested on another
  machine without a backup.

### STORE-02 adjudication — persistence aggregates behind a facade

- **Decision:** `DEFER`
- **Verified merit:** the method clusters are real, and SEC/provider-comparison row
  conversion accounts for substantial isolated portions of the file.
- **Reason to defer:** R4 and R5 must determine whether SEC transport, refresh,
  calculation, and persistence boundaries should move together or remain separate.
  Choosing repository classes now could create forwarding boilerplate or force those
  later reviews around a premature structure.
- **Synthesis rule:** revisit after R5. If the SEC rounds confirm stable aggregates,
  prefer a few domain persistence modules behind an initially compatible `Storage`
  facade. Do not create one module per table, adopt an ORM, or change callers merely
  to reduce line count.

### STORE-03 adjudication — historical-comparison policy

- **Decision:** `ACCEPT`
- **Verified problem:** `run_comparison_eligibility` combines retrieval with a
  deterministic financial-history policy, while `reproducibility.py` already owns
  manifest validity and calculation-contract identity. Current direct tests cover
  legacy-manifest and membership failures but not every status, chronology,
  contract, and missing-run branch.
- **Approved boundary:** add typed, database-independent comparison inputs and a pure
  evaluator in the reproducibility boundary. Storage remains responsible for
  retrieving rows and observed membership and for searching candidates.
  `previous_comparable_run_assessment` must retain its return shape, candidate order,
  and exact ordered limitation messages for reporting and dashboard consumers.
- **Implementation gate:** characterize every current rejection branch and the
  nearest-candidate search before moving policy. The extraction must not add hidden
  storage reads or change query chronology.

### STORE-04 adjudication — dead and misleading API surface

- **Decision:** `ACCEPT`
- **Approved scope:** remove the unused `timezone_name` parameter and its internal
  caller arguments because stored `evidence_date` is already the counted market-data
  date. Remove `previous_run`, and replace the test-only use of
  `previous_comparable_run` with the assessment API before removing that wrapper.
- **Compatibility finding:** this application is pre-1.0, does not document Storage
  as a public library API, and has no repository consumer for these surfaces. This is
  bounded internal cleanup, not a schema or behavior change.
- **Implementation gate:** retain evidence-date counts, universe/config filtering,
  and historical-comparison selection exactly, and run the full caller/test suite.

### STORE-05 adjudication — runtime maintenance

- **Decision:** `MODIFY`
- **Accepted problem:** destructive file selection is embedded in CLI formatting and
  lacks tests; inventory and cleanup also share a coherent runtime-policy concern.
- **Modification:** extract a small pure planner for the current explicit runtime
  directories, cutoff instant, protected filenames, selected direct-child files,
  and size inventory. Keep database counts and transactional row cleanup in
  `Storage`; keep user-facing output and the `--apply` decision in the CLI. An apply
  helper may delete only the exact planned files after rechecking containment and
  protected names. Do not add recursive deletion or a generalized filesystem
  framework.
- **Resolution of CLI-03:** the R1 deferral is now resolved as `MODIFY` with this
  narrower boundary. Implementation still waits for cross-review synthesis.
- **Implementation gate:** use temporary runtime roots to test preview/apply parity,
  cutoff equality, protected files, direct-child-only behavior, database dry runs,
  Windows/macOS CI, and refusal of out-of-root plan entries.

### R3 non-refactor safety finding — retention validation

- **Status:** `ACCEPT`
- **Finding:** `validate_settings` does not validate `retention.price_history_days`,
  `retention.report_days`, or `retention.temporary_file_days`. Cleanup converts them
  directly into cutoffs. A zero or negative local value can broaden an explicitly
  applied deletion far beyond the intended age policy.
- **Disposition:** treat this as a separate safety fix, not as refactoring. Before
  any maintenance extraction, require positive bounded retention values in settings
  validation and add command-level refusal tests. Preserve dry-run default behavior.

### R3 preserve/do-not-do decisions

- Keep SQLite, foreign-key enforcement, WAL mode, and deterministic connection
  closure; no ORM or database-server dependency is justified.
- Preserve Decimal-as-text storage, ISO date/time representations, explicit JSON
  serialization, row ordering, active/inactive SEC history, immutable financial
  snapshots, and immutable provider-comparison runs.
- Keep one caller-facing `Storage` entry point until R4/R5 and synthesis approve any
  aggregate split.
- Do not combine schema refactoring with a new schema version or data-policy change.
- Do not broaden cleanup into recursive deletion.

### R3 decision summary

| ID | Decision | Implementation consequence |
|---|---|---|
| STORE-01 | `MODIFY` | Extract exact schema ownership first; add safe future-version handling and historically grounded upgrade tests |
| STORE-02 | `DEFER` | Let R4/R5 establish SEC aggregate boundaries before splitting the facade |
| STORE-03 | `ACCEPT` | Plan a pure reproducibility comparison evaluator behind the unchanged assessment API |
| STORE-04 | `ACCEPT` | Remove verified dead methods and the obsolete timezone argument |
| STORE-05 | `MODIFY` | Extract only bounded runtime inventory/planning/apply logic; retain database and CLI ownership |

## Cross-review synthesis

Not started. This section will reconcile duplicated module proposals, dependency
direction, naming, implementation order, and the total amount of justified change
after R1–R5 have all been analyzed.

## Approved implementation queue

Intentionally empty. Production refactoring is prohibited until the review and
approval gates above are complete.

## Implementation evidence

No refactoring has been implemented.
