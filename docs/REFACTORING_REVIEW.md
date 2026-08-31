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
| R2 | Dashboard composition and presentation helpers | Qwen3-Coder-Next | Pending |
| R3 | Storage, migrations, and persistence boundaries | Qwen3-Coder-Next | Pending |
| R4 | SEC transport, identity, and submissions ingestion | Qwen3-Coder-Next | Pending |
| R5 | SEC financial calculations and refresh orchestration | Qwen3-Coder-Next | Pending |

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

## Cross-review synthesis

Not started. This section will reconcile duplicated module proposals, dependency
direction, naming, implementation order, and the total amount of justified change
after R1–R5 have all been analyzed.

## Approved implementation queue

Intentionally empty. Production refactoring is prohibited until the review and
approval gates above are complete.

## Implementation evidence

No refactoring has been implemented.
