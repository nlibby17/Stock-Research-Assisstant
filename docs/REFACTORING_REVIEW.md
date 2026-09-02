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
| R1 | CLI commands and orchestration | Qwen3-Coder-Next; superseded by Codex internal two-pass | Re-reviewed; superseding decisions recorded below |
| R2 | Dashboard composition and presentation helpers | Qwen3-Coder-Next; superseded by Codex internal two-pass | Re-reviewed; superseding decisions recorded below |
| R3 | Storage, migrations, and persistence boundaries | Codex internal two-pass | Analyzed; decisions recorded below |
| R4 | SEC transport, identity, and submissions ingestion | Codex internal two-pass | Analyzed; decisions recorded below |
| R5 | SEC financial calculations and refresh orchestration | Codex internal two-pass | Analyzed; decisions recorded below |

Additional rounds require a concrete reason discovered during verification. They are
not created merely to review every small module.

## Original R1 intake — CLI commands and orchestration (superseded)

This external review and its first adjudication are retained as an audit trail. They
are not the final R1 authority: the internal two-pass re-review below supersedes its
recommendations, ratings, and decisions wherever they differ.

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

## R1 re-review — CLI commands and orchestration

### Frozen internal reviewer instruction

Act as an independent, clinical architecture and refactoring reviewer. Analyze the
current repository directly and disregard the original external R1 conclusions. Do
not edit production code, generate replacement code, add features, or change command,
workflow, persistence, provider, scoring, research, configuration, or dashboard
behavior. Focus on `cli.py`, parser wiring, interactive personalization, setup and
configuration checks, runtime maintenance, SEC and provider-shadow orchestration,
status/validation commands, daily/morning composition, direct and indirect callers,
and all relevant tests. Treat the CLI as a legitimate composition and presentation
boundary; file length and imports alone are not defects. Identify at most five
cohesive recommendations with exact symbols and evidence, proposed ownership, risks,
prerequisite characterization tests, priority, difficulty, and confidence. Explicitly
identify code that should remain in the command layer. If a finding is a product,
historical-integrity, destructive-operation, or workflow bug rather than a refactor,
label it separately instead of concealing a behavior change inside structural work.

The following internal reviewer output was frozen before adjudication or
reconciliation with R3-R5. `INTAKE` records a proposal, not approval.

### CLI-RR-01 — extract distinct SEC application operations, not one provider service

- **Status:** `INTAKE`
- **Reviewer proposal:** move the filing-sync, Company Facts sync, and local financial-
  build lifecycles out of their command handlers into three narrowly named application
  operations with distinct typed outcomes. Reuse shared SEC entity-target resolution
  and leave transport, normalization, refresh policy, formulas, SQL, health
  persistence, timing, formatting, and exit-code ownership in their existing proper
  layers. Keep SEC identity health as a small reusable coverage operation only if live
  configuration checking needs the same non-presentation result.
- **Evidence:** `command_sec_filings_sync`, `command_sec_facts_sync`, and
  `command_sec_financials_build` span 152, 285, and 112 lines. Together they combine
  scope validation, dependency construction, universe traversal, partial-failure
  continuation, persistence, coverage/status derivation, provider health, and output.
  Their underlying work is not one lifecycle: filings replace active filing rows,
  Company Facts applies adaptive network refresh and observation history, and the
  financial build is entirely local and appends immutable snapshots.
- **Proposed interface:** one operation and purpose-specific result per lifecycle,
  initially consuming the concrete SEC capability and `Storage` facade. Commands own
  argument parsing, settings/dependency construction, elapsed measurement, provider-
  health writes, human output, and exit-code mapping.
- **Claimed benefit:** make financially meaningful partial-write and continuation
  behavior executable under tests while removing the largest non-presentation blocks
  from the CLI without creating a misleading generic provider abstraction.
- **Primary risks:** changed operation order, target identity expansion, cache bypass,
  per-ticker atomicity, state writes, stored counts, coverage, output order, health, or
  command return codes; concurrent extraction with SEC/storage module moves.
- **Prerequisite tests:** every selected/full/unknown scope; identity and predecessor
  targets; cache/stale/failure paths; exact writes and non-writes; continuation and
  deterministic ordering; coverage/health; output/exit characterization; ranking
  isolation; and full SEC/storage regression coverage.
- **Reviewer rating:** priority high; difficulty 8/10; confidence high.

### CLI-RR-02 — separate provider-shadow execution, evidence policy, and presentation

- **Status:** `INTAKE`
- **Reviewer proposal:** split `command_provider_shadow_run` along its existing three
  responsibilities: a pure promotion-evidence evaluator, a bounded application
  operation that assembles and persists one comparison run, and CLI presentation.
  Keep per-metric SEC/Yahoo comparison formulas in `provider_comparison.py` and retain
  the provider-shadow status command unless later presentation reuse justifies a read
  model.
- **Evidence:** the 229-line handler selects scope; loads stored SEC/Yahoo inputs;
  calculates comparison rows; derives completeness; retrieves and validates the
  linked production run; applies at least ten evidence-rejection rules; constructs and
  saves the run; counts historical evidence; records provider health; emits several
  summaries; and chooses an exit code. Tests cover metric comparison and storage of an
  already built run but do not execute this lifecycle or its qualification decision
  tree.
- **Proposed interface:** a database-independent evidence evaluator receiving explicit
  production-run metadata/results, comparison metadata/rows, expected identity, and
  cutoff policy; plus an operation using concrete storage/calculation dependencies and
  returning the immutable run, ordered comparisons, failures, and summary counts.
  Retrieval, persistence, health, and output must remain visibly separate from the
  pure qualification decision.
- **Claimed benefit:** make promotion evidence auditable and exhaustively testable,
  prevent console code from owning financial-history policy, and isolate comparison
  execution without altering production rankings.
- **Primary risks:** changed evidence-reason precedence/text, chronology, exact-universe
  checks, price-date interpretation, stale classification, run IDs/timestamps,
  persistence order, full-date counts, health status, or ranking isolation.
- **Prerequisite tests:** every qualification/rejection branch; mixed/missing dates and
  results; stale/incomplete rows; full and partial scopes; calculation/persistence
  failures; exact reason order; formula-contract consistency; immutable round trips;
  health/output/exit behavior; and proof that ranking rows remain untouched.
- **Reviewer rating:** priority high; difficulty 7/10; confidence high.

### CLI-RR-03 — introduce a typed personalization proposal before applying local files

- **Status:** `INTAKE`
- **Reviewer proposal:** move deterministic construction of a proposed personalized
  configuration out of `command_configure` into the customization boundary. Represent
  the resolved profile, horizon, risk, weights, thresholds, universe identity/path,
  securities, model identifier, warnings, and validation errors as one typed proposal.
  Keep interactive prompting, confirmation, progress messages, and exit codes in the
  CLI; keep provider-backed metadata enrichment as an explicit pre-proposal input.
- **Evidence:** the 173-line command handles reset, invalid-current fallback,
  interactive and flag input, numeric parsing, universe-file parsing, live Yahoo
  enrichment, ticker checks, deep configuration mutation, model/universe identifiers,
  validation, preview formatting, confirmation, two local-file writes, and a final
  command-to-command configuration check. Only two tests execute the noninteractive
  happy path; interactive, reset, cancellation, invalid input, enrichment failure, and
  write-failure behavior are uncharacterized.
- **Proposed interface:** a pure `CustomizationProposal` builder accepting current
  settings and already resolved user choices/securities, followed by a narrowly owned
  local apply operation. Existing parsing, weighting, identifiers, and serialization
  helpers remain in `customization.py`; no generic wizard framework is warranted.
- **Claimed benefit:** make the proposed effective configuration testable before local
  state changes, reduce branching in the command, and give interactive and
  noninteractive paths one deterministic model.
- **Primary risks:** changed defaulting, float rounding, identifier fingerprints,
  warning/error order, invalid-current recovery, default-universe behavior, backups,
  partial local writes, prompt text/order, or personal-file privacy.
- **Prerequisite tests:** every flag/default/interactive path; reset/cancel; invalid
  numbers/tickers/files; provider enrichment warnings; exact fingerprints and preview;
  no-write-on-invalid/cancel; backup naming; apply failures and recovery; reloaded
  settings equality; and assertions that local files remain ignored and unstaged.
- **Reviewer rating:** priority medium-high; difficulty 6/10; confidence high.

### CLI-RR-04 — extract bounded runtime inventory and cleanup planning

- **Status:** `INTAKE`
- **Reviewer proposal:** move runtime size inventory and file-retention selection from
  `command_storage_status` and `command_storage_clean` into a small runtime-maintenance
  policy boundary. Produce an immutable cleanup plan before applying it. Keep database
  cleanup in storage-owned code and keep the explicit `--apply` decision, paths shown
  to the user, and command output in the CLI.
- **Evidence:** the handlers and size helpers total approximately 102 lines. Database
  cleanup already has a dry-run/apply boundary, while recursive size calculation,
  direct-child file selection, protected filenames, UTC cutoffs, printing, and deletion
  remain in CLI code. No test executes the filesystem-retention behavior.
- **Proposed interface:** typed inventory and cleanup-plan values limited to explicit
  configured runtime subdirectories and resolved paths, plus an apply function that
  revalidates every planned path. Do not add recursive deletion or a generalized
  filesystem framework.
- **Claimed benefit:** make destructive scope, preview/apply parity, and cross-platform
  timestamp/path behavior testable before reorganizing presentation code.
- **Primary risks:** deletion outside the runtime root, time-of-check/time-of-use drift,
  changed direct-child semantics or cutoff equality, symlink handling, protected-file
  removal, or a false impression that preview guarantees later filesystem state.
- **Prerequisite tests:** Windows/macOS path behavior; resolved containment; protected
  names; direct-child-only selection; exact cutoffs; dry-run/apply parity; changed or
  missing files between plan and apply; database preview/apply behavior; and no deletion
  outside a temporary runtime root.
- **Reviewer rating:** priority medium-high; difficulty 5/10; confidence high.

### R1 re-review intake preserve/do-not-do findings

- Keep `command_parser.py` as declarative CLI-surface ownership and retain the handler
  map as the composition root. Do not create decorators, dynamic discovery, or one
  module per command.
- Keep `daily_workflow.py` responsible for generic ordered execution, timing, skip
  handling, and dashboard launch. Keep the actual daily step list at the command
  composition boundary unless a second real workflow proves shared composition.
- Keep `setup-check`, local `config-check`, `validate-latest`, SEC/provider status,
  research import, `run`, dashboard, and morning presentation in CLI code unless a
  separately verified pure policy or reused operation is named. Repeated printing or
  settings/storage initialization alone does not justify a service layer.
- Keep `main()` and `build_parser()` minimal. Do not add a command bus, dependency-
  injection container, universal command-result type, generic provider service, or
  formatter framework.
- Preserve command names/options, stdout/stderr ordering, return codes, daily step
  order, continuation/skip rules, personal-file privacy, current synchronous operation,
  and all ranking/provider isolation guarantees throughout refactoring.

### R1 re-review adjudication baseline

- `cli.py` is 1,757 physical lines with 20 `command_*` handlers occupying 1,511
  lines. Ten handlers exceed 50 lines, but six of those are primarily setup, status,
  validation, or presentation. The four largest genuine application lifecycles are
  Company Facts sync (285 lines), provider-shadow run (229), personalization (173),
  and filing sync (152). This evidence supports targeted boundaries, not a goal of
  making the CLI uniformly thin.
- `command_parser.py` already owns the declarative command surface without importing
  command implementations. `daily_workflow.py` already owns generic step execution,
  timing, skip handling, and dashboard launch. Both are cohesive and have direct
  tests; moving their contents again would fragment working boundaries.
- `tests/test_cli.py` contains nine tests. It executes setup-check, the isolated
  PyArrow check, daily/morning composition, parser wiring, and dashboard shutdown.
  `tests/test_customization.py` adds two executions of the noninteractive configure
  happy path. No test executes config-check, validation, research import, storage
  maintenance, SEC command lifecycles, provider-shadow lifecycle, status commands,
  interactive configuration, reset/cancel, or their failure behavior.
- Static caller inspection found four command-to-command paths:
  `config-check --live` calls `sec-health`; configure calls local config-check after
  reset/save; `run` calls `validate-latest`; and morning deliberately calls daily
  report then dashboard. Only the last is explicitly modeled as a user workflow.
  Command chaining is not automatically wrong, but it can conflate output, side
  effects, and status semantics when a reusable operation/result is absent.
- R3-R5 independently confirm the same bounded operation seams named by CLI-RR-01,
  CLI-RR-02, and CLI-RR-04. They reject a generic provider framework, ORM, command
  bus, or one-file-per-command approach and require characterization before moving
  orchestration.
- A controlled daily-workflow diagnostic left the real `command_run` in place while
  replacing its analysis and validation dependencies. `command_validate` was invoked
  twice: first from the step labelled `Yahoo ranking and base report`, then again from
  the explicit `Final validation` step. This is an actual composition defect, not a
  theoretical concern.
- A controlled legacy-shape diagnostic supplied scoring-quality metadata without a
  data-freshness block. `command_validate` raised `UnboundLocalError` because
  `fundamental_states` is defined only under `if freshness` but used under the
  independent `if scoring_quality` branch.
- A temporary-project diagnostic forced the second personalization-file write to
  fail. `universe.local.csv` remained newly written while
  `preferences.local.toml` did not exist. Reset similarly moves the two files one at
  a time. Per-file replacement is atomic, but the effective two-file customization
  is not an all-or-restored update.

### CLI-RR-01 adjudication — distinct SEC application operations

- **Decision:** `ACCEPT`
- **Verified problem:** the three sync/build handlers own independently testable
  application lifecycles, while their transport, parsing, refresh, calculation, and
  persistence policies already have or will have clearer owners. Combining them into
  one provider service would erase meaningful differences.
- **Approved boundary:** implement the separate filing-sync, Company Facts sync, and
  financial-build operations approved in SEC-04, FIN-02, and FIN-03. Use SEC-03's
  audited entity-target resolver, FIN-01/SEC-05's pure selectors, and the initially
  compatible `Storage` facade. Commands retain parsing, dependency construction,
  timing, provider-health persistence, output, and return-code mapping.
- **Identity-health reuse:** after the R4 capability split, add a small typed SEC
  identity-coverage result only if characterization confirms that both `sec-health`
  and live config-check need the same fetch/match decision. Do not make the coverage
  operation persist health or print. The commands may deliberately present or store
  the result differently.
- **Implementation ordering:** land prerequisite safety fixes and characterization
  tests first, then entity-target/effective-selection policies, then application
  operations, and only later any SEC persistence aggregate. Do not combine operation
  extraction with the provider-module and storage-module moves in one commit.

### CLI-RR-02 adjudication — provider-shadow operation and evidence policy

- **Decision:** `MODIFY`
- **Accepted problem:** comparison execution, promotion-evidence policy, persistence,
  health, and console presentation are genuinely separate concerns in one 229-line
  handler. The evidence decision has enough independent rejection paths to require a
  pure typed evaluator.
- **Modification:** perform this in two slices. First extract and exhaustively test a
  database-independent evidence evaluator in a narrowly named provider-evidence
  boundary. Then extract the comparison-run application lifecycle using the concrete
  comparison functions and `Storage` facade. Keep metric calculations in
  `provider_comparison.py`; keep retrieval/persistence, timing/IDs, health, display,
  and exit-code ownership explicit rather than hiding all of them behind one service.
- **Formula-contract gate:** FIN-SAFE-02 must define missing, mixed, and unsupported
  SEC formula-contract behavior before the evaluator can qualify promotion evidence.
  That approved behavior fix is not part of merely relocating existing code.
- **Implementation gate:** characterize every evidence reason and precedence, exact
  run/result identity, chronology, stale/incomplete cases, partial failures, stored
  rows, health, output, return codes, and ranking isolation before either extraction.

### CLI-RR-03 adjudication — typed personalization proposal and apply boundary

- **Decision:** `MODIFY`
- **Accepted problem:** deterministic proposal construction is obscured by prompts,
  provider enrichment, previews, confirmation, writes, and follow-up command output.
  Interactive and noninteractive modes should converge on one validated effective
  proposal before touching local files.
- **Modification:** add a typed pure proposal builder in `customization.py` using
  already resolved choices and securities. Keep parsing helpers, weights,
  fingerprints, and serializers there; keep interactive input, file/flag collection,
  provider-enrichment progress, confirmation, final presentation, and exit codes in
  `cli.py`. Add one narrowly scoped apply/reset boundary for the two private local
  files rather than a generic wizard, settings service, or I/O transaction framework.
- **Privacy and compatibility:** preserve exact local paths, TOML/CSV formats,
  fingerprints, backup naming or an explicitly migrated equivalent, Git ignore
  protections, project-default behavior, and safe updates on Windows/macOS 11/current
  macOS. Never stage generated personal files in refactoring commits.
- **Implementation gate:** first add the complete behavior matrix from CLI-RR-03,
  including reloading the effective settings after a proposed apply. Resolve
  CLI-RR-SAFE-03 in a distinct approved safety slice before moving write ownership.

### CLI-RR-04 adjudication — bounded runtime maintenance

- **Decision:** `MODIFY`
- **Accepted problem:** filesystem selection for a destructive command belongs in a
  testable policy rather than being interleaved with printing and deletion.
- **Modification:** adopt STORE-05's narrower resolution. Extract a pure planner for
  the existing explicit runtime directories, cutoffs, protected filenames,
  direct-child candidates, and size inventory. Keep database counts/transactional
  cleanup in `Storage`, user-visible preview and `--apply` in the CLI, and revalidate
  containment/protected names immediately before applying the exact plan.
- **Safety gate:** implement R3's positive bounded retention validation first. The
  extraction may not add recursion, broaden deletion scope, follow unsafe symlinks,
  or claim that a preview guarantees unchanged filesystem state at apply time.
- **Implementation gate:** use only temporary runtime roots for the full cross-platform
  test matrix listed in CLI-RR-04 and STORE-05 before moving production code.

### R1 re-review non-refactor safety findings

#### CLI-RR-SAFE-01 — daily report validates the same run twice

- **Status:** `ACCEPT`
- **Finding:** `command_run` calls `command_validate`, while `command_daily_report`
  invokes `command_run` as step 6 and `command_validate` again as step 8. The ranking
  step therefore includes an undocumented validation and the final validation repeats
  it. The shadow skip decision also receives the combined analysis-plus-validation
  return code rather than an unambiguous base-ranking result.
- **Disposition:** define and test one base-analysis command outcome and one final
  validation in the daily workflow. Preserve the convenient standalone `stockrank
  run` contract intentionally—either it retains one post-run validation through a
  wrapper or its documented behavior is explicitly revised with user approval. Decide
  shadow-skip semantics against the actual completed production-run state, not an
  accidental double command call. Preserve the visible eight-step ordering unless a
  separately approved workflow change says otherwise.

#### CLI-RR-SAFE-02 — legacy validation can reference uninitialized freshness state

- **Status:** `ACCEPT`
- **Finding:** `fundamental_states` is initialized only when the stored run contains a
  nonempty `runtime.data_freshness` mapping, but it is printed whenever independent
  `runtime.scoring_quality` metadata exists. A legacy, partial, or manually repaired
  run with the latter but not the former raises `UnboundLocalError` instead of
  reporting limited freshness evidence.
- **Disposition:** make the two optional metadata sections independent and initialize
  their display state safely. Add tests for neither block, each block alone, both
  blocks, malformed/empty mappings, legacy manifests, and current completed runs.
  Missing historical evidence must remain labelled unavailable or limited rather than
  fabricated.

#### CLI-RR-SAFE-03 — personalization updates can leave a mixed local state

- **Status:** `ACCEPT`
- **Finding:** configuring a custom universe writes `universe.local.csv` before
  `preferences.local.toml`. Failure on the second write leaves only the first change
  active; reset can similarly stop after moving one of two files. A subsequent config
  check may detect a fingerprint mismatch, but the requested update was not
  all-or-restored and the direct command can propagate the write exception.
- **Disposition:** stage and validate both proposed file contents before replacing
  either effective file. Apply or reset them through a bounded best-effort transaction
  that restores the prior pair if a later replacement fails, reports recovery clearly,
  and never deletes backups needed for repair. Test failures at every staging,
  replacement, backup, rollback, and reload point on Windows and macOS. Keep local
  files ignored and never infer that filesystem replacement is globally atomic.

### R1 re-review preserve/do-not-do decisions

- Keep the CLI as the application composition and human presentation boundary. It is
  acceptable for it to import many subsystems and contain concise status formatting.
- Keep parser declaration, generic daily execution, dashboard launch, small run and
  research-import wrappers, setup probes, status commands, and command-specific output
  where they are unless an approved operation/policy above removes real logic from
  them.
- Do not extract shared print loops, settings/storage bootstrap, universal scope
  parsing, status formatting, or integer exit codes merely because text repeats.
  Repetition with different financial meaning is safer than a generic abstraction.
- Do not create a command base class, command bus, service container, universal result,
  one file per command, or generic provider/workflow/configuration framework.
- Do not change public command names/options, workflow order, provider access,
  persistence semantics, scoring, research, dashboard behavior, or stdout/stderr as
  incidental consequences of reducing `cli.py` line count.

### R1 re-review decision summary

| ID | Decision | Implementation consequence |
|---|---|---|
| CLI-RR-01 | `ACCEPT` | Use three distinct SEC application operations already bounded by R4/R5; no generic provider service |
| CLI-RR-02 | `MODIFY` | Extract pure evidence policy first, then the comparison-run lifecycle; apply formula-contract gate |
| CLI-RR-03 | `MODIFY` | Build one typed customization proposal and bounded private-file apply/reset path; keep interaction in CLI |
| CLI-RR-04 | `MODIFY` | Use R3's narrow runtime planner/apply boundary and safety checks |

These decisions supersede CLI-01 through CLI-05 for final synthesis. Where the
original review happened to agree, the internal evidence above—not the external
model's count, risk, or confidence claims—is the authority.

## Original R2 intake — dashboard composition and presentation helpers (superseded)

This external review and its first adjudication are retained as an audit trail. They
are not the final R2 authority: the internal two-pass re-review below supersedes its
recommendations, ratings, and decisions wherever they differ.

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

## R2 re-review — dashboard composition and presentation helpers

### Frozen internal reviewer instruction

Act as an independent, clinical architecture and refactoring reviewer. Analyze the
current repository directly and disregard the original external R2 conclusions. Do
not edit production code, generate replacement code, redesign the approved dashboard,
add features, cache report state, or change ranking, research, historical-comparison,
SEC, provider-shadow, configuration, storage, or Streamlit behavior. Focus on
`dashboard.py`, `presentation.py`, `summaries.py`, Streamlit/theme configuration,
dashboard data acquisition and provenance, deterministic transformations, section
rendering and rerun order, direct and indirect consumers, and all relevant tests.
Treat ordered Streamlit rendering as legitimate side-effectful presentation and file
length as evidence only when a cohesive boundary exists. Identify at most five
recommendations with exact symbols and evidence, proposed ownership, risks,
prerequisite characterization tests, priority, difficulty, and confidence. Explicitly
identify code and visual behavior that should remain. If a finding is a point-in-time,
provenance, safety, or product-meaning bug rather than a refactor, label it separately
instead of hiding changed behavior inside structural work.

The following internal reviewer output was frozen before adjudication or
reconciliation with R1 and R3-R5. `INTAKE` records a proposal, not approval.

### DASH-RR-01 — add an uncached dashboard read-state boundary with explicit provenance

- **Status:** `INTAKE`
- **Reviewer proposal:** load and normalize the page's stored-report data and current-
  installation diagnostics through one read-only dashboard state boundary before
  rendering. Use separate typed report-bound and installation-current portions so a
  field cannot silently inherit the wrong universe, model, cutoff, or provider-
  comparison context. Read fresh state on every Streamlit rerun; do not add
  `st.cache_resource` or `st.cache_data` for latest-run/results data.
- **Evidence:** initial acquisition at lines 276–300 loads settings, latest run,
  results, comparable history, research, market context, and several JSON documents.
  Later rendering performs additional storage reads for each candidate's filings,
  five provider-health records, each active-universe SEC financial snapshot, and the
  latest active-universe provider-shadow run/rows/evidence count. Rendering code
  therefore owns query selection, JSON interpretation, cutoff choice, and display.
- **Proposed interface:** a command-independent `DashboardState` loader accepting
  explicit settings/storage dependencies and returning immutable or read-only typed
  report state, candidate/evidence data, comparison state, and diagnostics with an
  explicit provenance/cutoff label. Rendering receives this state and performs no
  database queries. Existing `Storage` remains the caller-facing persistence facade.
- **Claimed benefit:** make the data contract executable without Streamlit, prevent
  report/active-state mixing, preserve fresh reruns, and give all later rendering
  sections one auditable input snapshot.
- **Primary risks:** stale state through accidental caching, changed latest-run or
  previous-run selection, extra queries, loss of row ordering/types, eagerly loading
  expensive collapsed sections, changed missing/legacy behavior, or falsely claiming
  a transactionally consistent snapshot across independent storage calls.
- **Prerequisite tests:** no-run, failed/incomplete/legacy/current runs; exact result
  order and membership; research/no research; comparable/no-comparable history;
  malformed/empty optional JSON; filing cutoffs; active/stored configuration mismatch;
  latest versus report-linked diagnostics; query/call inventory; fresh state after a
  database update; and no network access or Streamlit import in the loader.
- **Reviewer rating:** priority high; difficulty 7/10; confidence high.

### DASH-RR-02 — consolidate deterministic display transformations in existing helpers

- **Status:** `INTAKE`
- **Reviewer proposal:** move only deterministic, Streamlit-free presentation and
  summary logic out of the executable dashboard into the existing
  `presentation.py`/`summaries.py` boundaries. Promote the existing private eligible-
  candidate selector for dashboard reuse and extract stable label, tier, escaping,
  gradient, factor-row, freshness-row, and provider-comparison summary transforms.
  Keep HTML structures tied to CSS classes and all `st.*` calls in rendering code.
- **Evidence:** `preference_label`, `score_tier`, `financial_markdown`, and
  `gold_gradient` are pure but cannot be imported without executing page setup and
  storage reads. Candidate selection duplicates `presentation._ranked_candidates`.
  Factor rows, freshness rows, provider-health labels, comparison-by-metric/sector
  rows, and material-row sorting are deterministic inline transformations. Existing
  presentation and sector helpers are Streamlit/storage-free and directly tested.
- **Proposed interface:** a small number of named functions returning primitive or
  typed view rows. Extend the existing helper modules according to meaning; do not
  create a generic formatter, chart-config object, or one helper per expression.
- **Claimed benefit:** directly test financial labels and display calculations,
  eliminate one real candidate-selection duplication, and leave Streamlit sections
  focused on order and layout without coupling pure logic to page execution.
- **Primary risks:** subtly changing eligible ordering/limits, legacy status mapping,
  percentages, missing-value labels, score contribution text, gradient endpoints,
  classification counts, or HTML/Markdown escaping behavior.
- **Prerequisite tests:** eligible/ineligible/tie/order/limit behavior; every legacy
  status mapping; label and currency escaping; zero/one/many gradient values and exact
  endpoints; sparse component/freshness data; all comparison classes; material sort
  ties and missing differences; and unchanged CSV/sector/helper tests.
- **Reviewer rating:** priority medium-high; difficulty 5/10; confidence high.

### DASH-RR-03 — organize ordered rendering behind an explicit page entry point

- **Status:** `INTAKE`
- **Reviewer proposal:** replace the 102-statement executable module body with an
  explicit page entry point and a bounded set of side-effectful section-render
  functions called in the current order. Keep them in the dashboard presentation
  boundary initially; split a separate section module only if the resulting function
  signatures remain cohesive. Keep the approved CSS/theme local and explicit rather
  than introducing a controller, templating engine, or generic component framework.
- **Evidence:** after initial state acquisition and seven local helpers, top-level
  rendering includes a 47-line run-details block, 106-line candidate block, 130-line
  per-candidate research loop, 51-line historical-change block, approximately 190
  lines of quality/provider/financial diagnostics, and a 143-line provider-shadow
  block. Their display order is meaningful, but their dependencies are currently
  implicit shared module variables.
- **Proposed interface:** `main()` performs page configuration, fresh state loading,
  empty-state handling, and one ordered `render_dashboard(state, active_settings)`
  call. Section functions receive only the state/configuration they display and
  return no domain decisions. Keep one visible call sequence as the page-order
  contract. The large CSS string may become one named local theme constant, but no
  external asset/package-data move is required merely to reduce lines.
- **Claimed benefit:** make page order and section dependencies reviewable, reduce
  hidden cross-section variables, enable component execution under Streamlit's test
  harness, and lower merge pressure without pretending side effects are pure.
- **Primary risks:** `set_page_config` no longer running first, changed Streamlit rerun
  or expander/tab behavior, lost `st.stop`, altered section order/visibility, widget
  identity changes, CSS/theme drift, overly broad function parameters, or a new module
  that merely relocates the page.
- **Prerequisite tests:** no-run stop behavior; exact major-section order and labels;
  warning/demo/configuration notices; candidate/no-candidate paths; research present/
  absent; comparison present/limited; diagnostics expanders; chart fixed scales and
  tooltips; platform instructions; dashboard shutdown integration; and manual visual
  comparison of the two documented screenshots at representative widths.
- **Reviewer rating:** priority medium-high; difficulty 7/10; confidence high.

### DASH-RR-04 — replace source-text assertions with executed dashboard contracts

- **Status:** `INTAKE`
- **Reviewer proposal:** before structural changes, establish an executed Streamlit
  characterization layer using the installed `streamlit.testing.v1.AppTest` and
  deterministic temporary report state. Retain a few narrow static assertions only
  for CSS/theme tokens or prohibitions that the harness cannot observe. Do not use
  screenshot pixel matching as the main regression test.
- **Evidence:** all five tests in `test_dashboard_visuals.py` read source text or theme
  TOML; a single 71-line test asserts implementation substrings, statement ordering,
  function locations, and absence of other substrings. It never executes the page.
  The seven presentation/summary tests cover pure helpers well but cannot detect a
  Streamlit exception, missing section, incorrect expander/tab/metric output, or
  report/diagnostic state mismatch. The installed Streamlit version provides both
  `AppTest.from_file` and `AppTest.from_function`.
- **Proposed interface:** reusable temporary dashboard-state fixtures plus executed
  smoke/semantic tests for visible elements, notices, candidate paths, and failure-
  free rendering. Test pure transforms outside Streamlit. Preserve only targeted
  source/theme tests for gold color tokens, fixed chart interaction policy, hidden
  toolbar configuration, and other contracts unavailable through AppTest.
- **Claimed benefit:** allow behavior-preserving refactors without tests failing only
  because code moved, while catching actual page crashes and missing or reordered
  content that source scanning cannot detect.
- **Primary risks:** brittle coupling to Streamlit internals, slow tests, accidental
  reads of real runtime data, insufficient chart/CSS visibility in AppTest, and false
  confidence if manual visual QA is removed.
- **Prerequisite tests:** prove fixtures use temporary storage/configuration; bound
  execution time; cover current/no/legacy/partial states; ensure no network calls;
  retain direct helper tests; and document which visual contracts still require
  browser/manual verification on Windows and macOS.
- **Reviewer rating:** priority high; difficulty 6/10; confidence high.

### R2 re-review intake preserve/do-not-do findings

- Keep fresh database reads on every Streamlit rerun. Do not cache the latest run,
  results, research, comparison, or diagnostics without a separately measured and
  correctly invalidated performance requirement.
- Keep the approved single-page order, visual hierarchy, gold/navy palette, fixed
  noninteractive charts, tooltips, compact keys, platform-specific personalization
  instructions, research expanders/tabs, diagnostics disclosure, CSV download, and
  hidden Deploy control.
- Keep `presentation.py` and `summaries.py` deterministic and free of Streamlit and
  storage. Keep Altair chart declarations and CSS-coupled HTML near rendering unless a
  second real visual consumer establishes a stable abstraction.
- Do not add a dashboard controller, template engine, global session-state model,
  generic UI/component framework, generalized chart builder, or one module per visual
  section.
- Preserve stored-run scoring/universe meaning, comparison eligibility, point-in-time
  filing rules, provider/shadow isolation, missing/legacy disclosures, and the rule
  that the dashboard never mutates research, rankings, or provider evidence.

### R2 re-review adjudication baseline

- `dashboard.py` remains 1,246 physical lines. It contains a 249-line inline style
  block, seven local helper functions, and 102 top-level statements. After state
  acquisition, major executable blocks include 106 lines for top candidates, 130 for
  per-company research, 51 for historical changes, approximately 190 for quality/
  SEC diagnostics, and 143 for provider-shadow diagnostics. The page order is valid;
  implicit data dependencies across that module body are the maintainability issue.
- `presentation.py` and `summaries.py` are cohesive deterministic boundaries with
  four and three direct tests. They import neither Streamlit nor storage. The
  dashboard duplicates their candidate filtering and keeps several other pure
  transforms inside an import-time executable page, which prevents ordinary unit
  import and reuse.
- The five dashboard-specific tests do not run Streamlit. They inspect theme TOML
  and source substrings; one 71-line test asserts implementation text, code order,
  helper location, and absence of other strings. A behavior-preserving function or
  module move would fail many assertions while a runtime exception inside the page
  could pass them. The installed Streamlit version provides `AppTest.from_file` and
  `AppTest.from_function`, so an executed characterization seam is available without
  adding a dependency.
- Current dashboard loading makes no network request and has no Streamlit cache.
  Every rerun reads `latest_run` and its stored results again. This is the correct
  freshness default and must survive any state extraction.
- Core ranking, research, market, and historical-comparison sections use the latest
  stored run and mostly use that run's stored configuration. The diagnostics portion
  instead iterates the active settings universe for financial snapshots, loads the
  latest provider health globally, and selects the latest provider-shadow run using
  the active comparison config and active universe name. Those records can postdate
  or differ from the report shown at the top; a configuration-mismatch notice does
  not identify the provenance of each diagnostic section.
- Financial snapshot rows use the latest snapshot per active ticker without the
  displayed run's completion cutoff. Provider-shadow runs persist an
  `analysis_run_id`, but the dashboard does not select by that link. The existing
  storage lookup also lacks an `analysis_run_id` filter. Resolving report-linked
  versus installation-current views therefore requires an explicit product decision
  and a bounded storage query, not just moving the existing lines.
- Candidate filing selection uses the run's `completed_at` when present. When it is
  missing, `available_at=None` means `effective_filings` applies no cutoff and selects
  the latest stored filings. The caption still claims filings were filtered to the
  run's completion time. `reporting.py` uses the same pattern, so the fix must be
  shared rather than allowing dashboard and Markdown report semantics to diverge.
- When no result is eligible, the dashboard says no company met both score and
  coverage thresholds. Eligibility also includes the stored minimum price and
  20-day average-dollar-volume rules, so the message can state the wrong reason for
  an empty list even though exact per-result eligibility reasons are stored.

### DASH-RR-01 adjudication — uncached report and diagnostics state

- **Decision:** `MODIFY`
- **Accepted problem:** query selection, JSON parsing, cutoff choice, current-versus-
  stored configuration, and display are interleaved. A render function should not
  decide which historical or active financial evidence it is showing.
- **Modification:** use two explicit read models rather than one monolithic state
  object: a report-bound state keyed by the displayed `run_id`, and an installation-
  current diagnostics state keyed by the active configuration. A small containing
  value may carry both with distinct provenance labels. Each loader uses concrete
  `Settings`/`Storage`, performs no writes or network access, and is called fresh on
  every rerun. Rendering performs no ad hoc storage reads.
- **Consistency rule:** bind report results, research, comparison history, filings,
  and any report-linked shadow evidence to stored run identity and explicit cutoffs.
  Keep genuinely current provider health or Step 2.4 progress only when it is clearly
  labelled as installation-current with checked time, universe, and policy version.
  Do not imply one multi-call storage read is transactionally atomic; preserve stable
  IDs and report any unavailable/mismatched portion.
- **Performance rule:** no `st.cache_resource`/`st.cache_data` for mutable report or
  diagnostics state. If later profiling finds real latency, optimize storage queries
  or use explicit version-aware invalidation in a separate performance change.
- **Implementation gate:** resolve DASH-RR-SAFE-01 and DASH-RR-SAFE-02 first as
  approved meaning fixes, then characterize the exact query/call inventory and every
  current/legacy/mismatch state before extracting loaders.

### DASH-RR-02 adjudication — deterministic presentation transformations

- **Decision:** `MODIFY`
- **Accepted problem:** pure view calculations inside an executable Streamlit module
  are difficult to import and test, and eligible-candidate selection is genuinely
  duplicated.
- **Modification:** make the existing candidate selector a tested public helper and
  move `preference_label`, `score_tier`, `financial_markdown`, `gold_gradient`, and
  stable factor/freshness/comparison row transforms into the existing deterministic
  presentation/summary boundary according to meaning. Keep `metric_help_key` and
  `accent_notice` with Streamlit rendering. Keep `change_badges`, candidate/market
  table HTML, chart declarations, and other CSS-coupled structures local until a
  second real renderer proves a reusable contract.
- **Boundary rule:** do not convert every dictionary into a dataclass or create a
  generic formatter/chart configuration layer. Typed values are justified at the
  loader/section boundary; simple display rows may remain ordinary mappings where
  their shape is directly tested.
- **Implementation gate:** add all finite legacy-label, candidate ordering, sparse
  data, comparison aggregation, and gradient tests before moving helpers. Preserve
  exact CSV bytes, sector summaries, score-breakdown semantics, percentages,
  missing-value language, and gold endpoints.

### DASH-RR-03 adjudication — explicit page entry and section rendering

- **Decision:** `ACCEPT`
- **Verified problem:** ordered rendering is spread across shared top-level variables,
  making dependencies and page execution difficult to characterize. This is a real
  boundary even though each section remains intentionally side-effectful.
- **Approved boundary:** add one entry point that runs page configuration first,
  loads fresh typed state, handles the no-run stop, and calls a short visible sequence
  of section-render functions in the approved order. Begin with functions in the
  dashboard presentation module and explicit parameters. Create a separate section
  module only if signatures remain cohesive after state/view-model extraction; do not
  move hundreds of lines merely to make the original file shorter.
- **Style decision:** retain the approved CSS/theme as one explicit local presentation
  asset or constant. Moving it to packaged data creates unnecessary distribution
  risk; tokenizing every color/spacing literal creates unnecessary indirection. Any
  style extraction must preserve the current theme and browser behavior exactly.
- **Implementation gate:** land DASH-RR-04's executed characterization first. Preserve
  `set_page_config` ordering, `st.stop`, major section order, tabs/expanders, widget
  identity, fixed chart scales, tooltips, notices, download behavior, and responsive
  appearance. Finish with manual browser comparison against both README screenshots.

### DASH-RR-04 adjudication — executed Streamlit characterization

- **Decision:** `ACCEPT`
- **Verified problem:** current source scanning protects implementation placement,
  not dashboard execution. It is inadequate as the primary safety net for the state
  and rendering extractions now justified.
- **Approved boundary:** build temporary deterministic report-state fixtures and use
  `AppTest.from_function` once the explicit render seam exists. Cover visible semantic
  elements, notices, empty/current/legacy paths, expanders/tabs, metrics, and absence
  of uncaught exceptions without touching real runtime data or the network. Keep
  direct pure-helper tests and a narrow set of static theme/CSS prohibitions where
  AppTest cannot observe browser styling or Altair interaction.
- **Test migration rule:** add executed tests before deleting any source assertion.
  Retain a source/static check only when its user-visible or safety contract is named;
  do not preserve line-order or helper-location assertions after equivalent executed
  coverage exists. Screenshot review supplements tests but does not become flaky
  pixel-diff CI.
- **Implementation gate:** prove fixture isolation, execution time, deterministic
  widget identity, and no network calls. Run the executed suite on Windows, macOS,
  and Linux CI before completing the rendering split.

### R2 re-review non-refactor safety findings

#### DASH-RR-SAFE-01 — distinguish stored-report evidence from current diagnostics

- **Status:** `ACCEPT`
- **Finding:** the dashboard presents one stored ranking run but later selects SEC
  financial rows, provider health, provider-shadow results, evidence counts, and
  universe membership through the active installation. After a profile/universe
  change or an independently run SEC command, those sections can describe different
  scopes or times without one explicit boundary explaining the difference.
- **Disposition:** define every section as either report-bound or installation-current.
  Report-bound data must use the displayed run's recorded membership and time/policy
  identity; provider-shadow evidence shown as belonging to that report must be selected
  through `analysis_run_id`. Installation-current health/progress may remain useful,
  but must state its checked time, active universe/config version, and mismatch with
  the displayed report. Add a storage lookup by analysis-run link only if required by
  this approved contract. Never silently substitute active state for missing stored
  evidence.

#### DASH-RR-SAFE-02 — do not show unbounded filings for a run with no completion time

- **Status:** `ACCEPT`
- **Finding:** passing `available_at=None` for a run lacking `completed_at` selects the
  latest stored SEC filings even though the dashboard and Markdown report claim the
  list was filtered to the run's completion time. Later filings can therefore appear
  inside an incomplete/legacy run's research evidence.
- **Disposition:** require an aware recorded completion cutoff before displaying
  run-qualified filings. If no defensible cutoff exists, withhold the filing list and
  show an explicit historical limitation; do not invent one from the current clock or
  silently use all filings. Apply the same rule through a shared pure filing-selection
  policy in dashboard and reporting. Test before/at/after cutoff, missing completion,
  date-only availability, legacy runs, and no-filing behavior.

#### DASH-RR-SAFE-03 — empty candidate explanation omits liquidity eligibility

- **Status:** `ACCEPT`
- **Finding:** the no-candidate message says no company met score and coverage
  thresholds, but stored eligibility also requires the configured minimum price and
  20-day average-dollar-volume floor. An empty list caused entirely by liquidity is
  therefore described incorrectly.
- **Disposition:** state that no company met all stored candidate eligibility rules
  and summarize the applicable score, coverage, price, and liquidity thresholds or
  aggregate stored eligibility reasons compactly. Use the displayed run's recorded
  policy and reasons, not active settings. Preserve the rule that the list is not
  padded and add score-, coverage-, price-, volume-, and mixed-failure tests.

### R2 re-review preserve/do-not-do decisions

- Preserve fresh uncached reruns, the current single-page order, stored-run candidate
  policy, exact comparison eligibility, research/filing separation, provider-shadow
  isolation, and all missing/legacy disclosures.
- Preserve the approved visual system: dark navy surfaces, gold positive accent,
  purple download action, blue informational notices, restrained warning/error colors,
  fixed noninteractive charts, consistent help keys/tooltips, compact diagnostics,
  responsive tables, and hidden deployment control.
- Keep Altair definitions and CSS-coupled custom HTML explicit near rendering. Do not
  generalize the two different charts or manufacture a component library for one page.
- Keep `presentation.py` and `summaries.py` deterministic and storage/Streamlit-free.
  Keep storage SQL in the storage boundary and application/provider policy out of
  rendering.
- Do not add global/session caches, a controller, template engine, generic view model
  framework, widget registry, one module per section, browser automation dependency,
  or screenshot pixel comparisons as a refactoring side effect.

### R2 re-review decision summary

| ID | Decision | Implementation consequence |
|---|---|---|
| DASH-RR-01 | `MODIFY` | Load fresh report-bound and installation-current read states separately with explicit provenance |
| DASH-RR-02 | `MODIFY` | Consolidate only stable Streamlit-free transforms in existing helper modules; keep CSS-coupled rendering local |
| DASH-RR-03 | `ACCEPT` | Add an explicit page entry point and ordered section functions without a controller/framework |
| DASH-RR-04 | `ACCEPT` | Establish executed AppTest characterization before structural dashboard changes |

These decisions supersede DASH-01 through DASH-05 and the original R2 test
dispositions for final synthesis. The original section remains only as an audit
record; the internal evidence and safety findings above are authoritative.

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

## R4 — SEC transport, identity, and submissions ingestion

### Frozen internal reviewer instruction

Act as an independent, clinical architecture and refactoring reviewer. Analyze the
repository directly but do not edit production code, generate replacement code, add
features, or change provider, cache, filing, persistence, or point-in-time behavior.
Focus on SEC JSON transport, cache handling, company identity, audited predecessor
overrides, submissions ingestion, filing normalization and selection, their CLI and
storage callers, and all direct or indirect tests. Treat Company Facts calculation and
refresh policy as R5 scope except where a shared R4 boundary would constrain it.
Preserve official SEC-only access, declared identity, throttling, retry and stale-cache
policy, canonical filing URLs, amendment handling, timestamps, ordering, active-history
semantics, and cross-platform support. File size alone is not evidence of a problem.
Identify at most five cohesive recommendations, cite exact symbols and evidence, state
a proposed boundary, risks, prerequisite tests, priority, difficulty, and confidence,
and explicitly identify code that should stay. If a finding is a product bug rather
than a refactor, label it separately rather than smuggling a behavior change into the
recommendation.

The following reviewer output was frozen before adjudication. `INTAKE` records a
proposal, not approval.

### SEC-01 — decompose the SEC provider by cohesive capability behind a compatibility facade

- **Status:** `INTAKE`
- **Reviewer proposal:** keep `stockrank.data.sec` as the caller-facing import facade,
  but move implementation into cohesive transport/cache, identity/configuration,
  submissions, and Company Facts modules. R4 should establish only the first three;
  the Company Facts destination and any shared domain types must be finalized with R5.
- **Evidence:** `src/stockrank/data/sec.py` is 1,143 lines and grew in three distinct
  provider milestones. `SecClient` occupies lines 245–442, identity and override logic
  occupies lines 118–183 and 445–530, submissions occupies lines 533–835, and Company
  Facts configuration/normalization occupies lines 186–242 and 838–1,143. These
  clusters have clear one-way dependencies but currently share one edit surface.
- **Proposed interface:** a thin `sec.py` re-export facade preserving every current
  public name; internal modules may depend on a small shared errors/value module and
  the transport client, but transport must not import provider-specific parsers.
- **Claimed benefit:** reduce merge pressure and make the transport, identity,
  submissions, and later Company Facts responsibilities independently reviewable
  without forcing caller rewrites.
- **Primary risks:** circular imports, broken type identity or monkeypatch paths,
  accidental public-API loss, and duplicating shared date/accession helpers.
- **Prerequisite tests:** import-compatibility inventory; all SEC transport, submissions,
  Company Facts, reporting, dashboard, storage, and CLI tests; Windows/macOS CI; and an
  explicit assertion that existing public imports resolve to the same objects.
- **Reviewer rating:** priority high; difficulty 6/10; confidence high.

### SEC-02 — give the on-disk SEC JSON cache an explicit private boundary

- **Status:** `INTAKE`
- **Reviewer proposal:** move cache path derivation, record encoding/decoding, metadata
  validation, freshness calculation, and atomic replacement out of `SecClient` into a
  small SEC-specific private cache component. Keep retry, throttling, allowed-host
  checks, headers, and live requests in `SecClient`; do not create a generic application
  caching framework.
- **Evidence:** `SecClient.get_json` coordinates live transport while `_cache_path`,
  `_read_cache`, `_write_cache`, and `_is_fresh` implement a compressed disk-record
  format. The writer records `schema_version = 1`, but the reader does not inspect it,
  and cache-format failures are intentionally converted to misses.
- **Proposed interface:** an injected private cache store returning either a validated
  `SecJsonDocument` or a cache miss, plus an atomic write operation. `SecClient` remains
  the sole owner of fresh-versus-stale fallback policy and the public `get_json` result.
- **Claimed benefit:** make cache-format compatibility and corruption behavior directly
  testable while leaving network policy readable and unchanged.
- **Primary risks:** changing silent-miss behavior, freshness boundaries, compression,
  filenames, replacement atomicity, stale fallback, or adding unnecessary abstraction.
- **Prerequisite tests:** current gzip compatibility; source-URL mismatch; corrupt,
  missing, unsupported-schema, malformed-time, and write-failure records; exact TTL
  boundary; stale fallback limit; forced refresh; and identical cache filenames.
- **Reviewer rating:** priority medium; difficulty 4/10; confidence medium-high.

### SEC-03 — centralize audited SEC entity-target resolution

- **Status:** `INTAKE`
- **Reviewer proposal:** create a pure entity-target resolver that combines the SEC
  identity index with configured, evidence-backed predecessor CIKs and returns an
  immutable primary-plus-predecessor target for each configured ticker. Preserve the
  existing TOML format and official-SEC evidence requirement.
- **Evidence:** `command_sec_filings_sync` lines 727–757 and
  `command_sec_facts_sync` lines 942–984 independently fetch/index identities, load
  overrides, report missing tickers, synthesize predecessor `SecCompanyIdentity`
  values, and suppress a duplicate primary CIK. This duplicated rule feeds both R4
  filings and R5 Company Facts.
- **Proposed interface:** a deterministic resolver accepting normalized configured
  tickers, parsed identities, and audited override values and returning ordered entity
  targets plus explicit unresolved-ticker results. Network access, storage, and output
  formatting remain outside it.
- **Claimed benefit:** prevent filing and fact ingestion from drifting on predecessor
  handling and give a financially meaningful identity rule direct tests.
- **Primary risks:** changed ordering or names, incorrect deduplication, hiding partial
  failures, or applying an override to the wrong normalized ticker.
- **Prerequisite tests:** primary-only, primary repeated in overrides, multiple ordered
  predecessors, ticker alias normalization, unresolved primary, invalid CIKs, and exact
  parity between filings and Company Facts target lists.
- **Reviewer rating:** priority high; difficulty 4/10; confidence high.

### SEC-04 — extract a filings-sync application operation from CLI presentation

- **Status:** `INTAKE`
- **Reviewer proposal:** resolve the filings portion of deferred CLI item CLI-01 by
  moving the per-universe SEC filing synchronization operation out of
  `command_sec_filings_sync`. The command should parse arguments, invoke the operation,
  record or present its typed result at an explicitly chosen boundary, and map the
  result to the current exit code and text.
- **Evidence:** `command_sec_filings_sync` lines 688–839 selects tickers, constructs SEC
  dependencies, resolves entity targets, fetches every CIK, deduplicates filings,
  replaces active storage state, evaluates effective filings, calculates coverage and
  cache diagnostics, records provider health, formats output, and decides the exit
  code. No command-level test executes this behavior; current tests stop at the daily
  workflow's mocked handler sequence.
- **Proposed interface:** an injected operation with explicit settings/targets,
  clock/force/since inputs, SEC gateway, and filing repository dependencies, returning
  an immutable per-ticker and aggregate result. Keep argparse and human-readable output
  in the CLI and keep SQL/transaction ownership in storage.
- **Claimed benefit:** make partial failure, stale fallback, replacement, coverage, and
  health semantics characterizable without a live network or console capture.
- **Primary risks:** changed per-ticker continuation, partial-write behavior, health
  status, request/cache counts, failure ordering, exit codes, or excessive protocols
  and data classes.
- **Prerequisite tests:** current output/exit characterization; selected versus full
  universe health; missing identity; predecessor merge/deduplication; per-CIK and
  per-ticker failure continuation; stale snapshots; storage replacement arguments;
  annual/quarterly coverage; empty results; and deterministic failure ordering.
- **Reviewer rating:** priority high; difficulty 7/10; confidence high.

### SEC-05 — separate reusable filing-selection policy from network-backed ingestion

- **Status:** `INTAKE`
- **Reviewer proposal:** move the deterministic `effective_filings` policy to a pure
  submissions-domain function or service rather than requiring reporting, dashboard,
  status, and CLI callers to reach it through the network-backed `SecSubmissions`
  class. Keep columnar payload normalization with submissions ingestion unless further
  evidence justifies another parser object.
- **Evidence:** `SecSubmissions.effective_filings` lines 792–835 performs no I/O and is
  called from CLI status/sync, reporting, and dashboard code using the class itself.
  In contrast, `_parse_columnar` is used only by `fetch` and shares the configured form
  allowlist, identity, source, and fetch metadata.
- **Proposed interface:** a typed pure function accepting filings and an optional aware
  availability cutoff, with a compatibility static wrapper during migration if needed.
- **Claimed benefit:** put amendment/period/point-in-time selection in an explicitly
  reusable policy boundary without over-fragmenting ingestion parsing.
- **Primary risks:** changed grouping key, cutoff semantics, timezone validation,
  tie-breaking, result ordering, or two competing public entry points.
- **Prerequisite tests:** unamended and amended periods; later non-amendment replacement;
  missing report and acceptance dates; aware cutoff before/at/after acceptance; naive
  cutoff rejection; accession tie-break; multiple forms and periods; and exact ordering.
- **Reviewer rating:** priority medium-high; difficulty 3/10; confidence high.

### R4 adjudication baseline

- `data/sec.py` has 18 public top-level names and four cohesive capability clusters,
  but current repository callers consistently import them through
  `stockrank.data.sec`. A compatibility facade is therefore feasible and necessary;
  a caller-wide import rewrite is not justified.
- Git history confirms that identity/transport, submissions, and Company Facts arrived
  as three separate provider milestones. The current one-way dependency direction is
  sound: identity, submissions, and Company Facts consume `SecClient`; transport does
  not know their payload rules.
- The focused R4 dependency suite passed 66 tests across SEC transport, submissions,
  Company Facts, refresh, financials, storage, reporting, dashboard visuals, and CLI.
  Direct command coverage does not execute the filing-sync lifecycle; CLI tests mock
  the handler while checking only daily-workflow sequencing.
- Filing and Company Facts commands independently implement the same primary-plus-
  predecessor identity expansion. The behavior is financially meaningful because the
  configured predecessor CIKs extend the filing/fact history attributed to one ticker.
- `effective_filings` is pure and has four non-ingestion consumers, while columnar
  normalization is private to `SecSubmissions.fetch`. This supports extracting the
  selection policy but not manufacturing a second parser abstraction.
- A temporary-cache diagnostic wrote a correctly compressed record with
  `schema_version = 999` and a timestamp one year in the future. The current reader
  accepted it, and `_is_fresh` classified it as fresh. This confirms the cache metadata
  issue independently of any proposed module split.
- `SecSubmissions.fetch` validates the payload shape but does not verify the root
  payload's `cik` against the requested identity. `SecCompanyFacts.fetch` already
  performs the equivalent integrity check.
- `validate_settings` does not validate SEC numeric limits, cache TTLs, history years,
  filing forms, or the approved identity URL. `setup-check` validates only the user
  agent; local `config-check` can therefore report valid before an SEC constructor or
  override loader rejects the configuration during the daily workflow.

### SEC-01 adjudication — provider capability modules behind a facade

- **Decision:** `MODIFY`
- **Accepted problem:** transport/cache, identity/overrides, submissions, and Company
  Facts are genuine cohesive clusters with stable one-way dependencies. Keeping all of
  them in one growing file creates an avoidable shared edit surface.
- **Modification:** do not perform an R4-only partial file shuffle. Finalize the shared
  errors/value types and Company Facts destination during R5, then execute one staged
  split behind an unchanged `stockrank.data.sec` re-export facade. Preserve class and
  dataclass identity, current constructor signatures, exception types, and monkeypatch
  paths. Internal modules may be narrowly named; do not create a generic provider
  framework or one file per class.
- **Relationship to STORE-02:** this does not approve moving SEC SQL out of `Storage`.
  The provider split and persistence-aggregate decision remain separate until R5 and
  cross-review synthesis establish the full dependency direction.
- **Implementation gate:** freeze the public-symbol inventory; add import-compatibility
  tests; run every direct and indirect SEC consumer; and require Windows/macOS CI before
  deleting the original implementations from the facade.

### SEC-02 adjudication — private SEC cache boundary

- **Decision:** `MODIFY`
- **Accepted problem:** the compressed cache record is a distinct persistence format,
  and its codec/metadata rules should be directly testable. The unused schema marker
  proves that the format is not currently self-validating.
- **Modification:** extract only SEC-specific path/codec/read/write behavior inside the
  transport capability established by SEC-01. Keep TTL freshness, force behavior,
  stale-on-error eligibility, retry, and final `SecJsonDocument` construction in
  `SecClient`, where the live-versus-cache policy can be read as one operation. Do not
  introduce a general cache framework, alternate backend protocol, or dependency-
  injection layer without a second real implementation.
- **Implementation gate:** first characterize current filenames, gzip bytes, atomic
  replacement, silent corruption-as-miss behavior, exact TTL/stale boundaries, and
  write failures. The extraction must not rename existing cache files or trigger a
  network redownload solely because code moved.

### SEC-03 adjudication — audited entity-target resolution

- **Decision:** `ACCEPT`
- **Verified problem:** filing and Company Facts orchestration can drift because each
  independently combines normalized SEC identities with the same ordered predecessor
  override policy.
- **Approved boundary:** add a pure entity-target resolver in the identity capability.
  It receives already parsed identities and already validated overrides and returns
  ordered immutable targets plus explicit unresolved tickers. Override-file syntax,
  CIK, reason, and official-evidence validation stay with the configuration loader;
  the resolver must not duplicate those validations or perform network/storage work.
- **Implementation gate:** characterize primary and predecessor ordering, duplicate
  suppression, alias normalization, unresolved tickers, and exact parity between the
  filings and Company Facts target sets before replacing either command's loop.

### SEC-04 adjudication — filings-sync application operation

- **Decision:** `MODIFY`
- **Accepted problem:** the filing-sync command combines a substantial testable
  application lifecycle with console presentation, and current tests do not execute
  that lifecycle. This resolves the filings portion of CLI-01.
- **Modification:** extract one narrowly named filings-sync operation after its command
  behavior is characterized. It may use the concrete SEC gateway and existing Storage
  facade rather than adding speculative repository protocols. The operation owns
  per-ticker fetch/deduplication and the existing per-ticker storage replacement,
  returning ordered per-ticker outcomes and aggregate coverage/status data. The CLI
  retains argument parsing, human-readable formatting, provider-health persistence,
  and exit-code mapping.
- **Preserved failure contract:** one failed CIK currently prevents replacement for
  that ticker but does not roll back already completed tickers. That partial-write and
  continuation behavior must remain explicit; a refactor may not silently make the
  full universe atomic or overwrite a failed ticker with an empty result.
- **Implementation gate:** add command characterization tests for every prerequisite in
  SEC-04, including exact provider-health rows and partial-scope status, before moving
  the loop. Keep R3's caller-facing `Storage` facade during this extraction.

### SEC-05 adjudication — pure effective-filing selection policy

- **Decision:** `ACCEPT`
- **Verified problem:** amendment, reporting-period, availability-cutoff, and ordering
  policy is pure domain logic but is exposed as a static method on a network-backed
  ingestion class. Current direct tests cover only a later amendment and one cutoff.
- **Approved boundary:** add one pure, typed selection function in the submissions
  domain and migrate CLI, reporting, dashboard, and R5 callers to it. A temporary
  `SecSubmissions.effective_filings` compatibility wrapper is acceptable during the
  same migration, but synthesis must choose one final public entry point rather than
  retain duplicates indefinitely. Keep `_parse_columnar` with ingestion.
- **Implementation gate:** characterize the grouping key, missing dates, aware cutoff
  boundary, naive rejection, later non-amendment filings, accession tie-break, forms,
  periods, and ordering exactly before extraction.

### R4 non-refactor safety findings

#### SEC-SAFE-01 — validate SEC cache metadata before freshness decisions

- **Status:** `ACCEPT`
- **Finding:** `_read_cache` ignores the written schema version and accepts naive or
  future `fetched_at` values. A naive value can raise during comparison with the aware
  UTC clock; a future value can remain fresh far beyond the configured TTL and stale
  ceiling.
- **Disposition:** treat unsupported schema, malformed or naive timestamps, and
  unreasonably future timestamps as cache misses before any freshness calculation.
  Define and test any small clock-skew tolerance explicitly. Preserve silent recovery
  from corrupt local cache files and never convert this into use of unvalidated data.

#### SEC-SAFE-02 — verify submissions payload identity

- **Status:** `ACCEPT`
- **Finding:** the root submissions payload contains a CIK, but `SecSubmissions.fetch`
  does not verify it. A wrong or cross-wired payload would be normalized under the
  requested identity and could produce canonical URLs and stored rows for the wrong
  issuer.
- **Disposition:** require a numeric root payload CIK matching the requested padded CIK
  before parsing or storing filings. Add missing, invalid, and mismatched cases. Apply
  the check only to the root document because paginated history files do not carry the
  same root metadata.

#### SEC-SAFE-03 — complete local SEC configuration validation

- **Status:** `ACCEPT`
- **Finding:** local configuration checks omit the SEC settings consumed by client,
  identity, and submissions constructors, and malformed entity-override TOML or file
  errors are not consistently wrapped as `SecConfigurationError`. A user can receive a
  valid local check and then encounter an avoidable runtime traceback or step failure.
- **Disposition:** add side-effect-free SEC settings validation for the approved URL,
  request limits, timeout/retries/backoff, positive cache/stale windows, positive
  history years, and nonempty filing forms. Wrap override read/parse failures with a
  concise SEC configuration error. Keep live coverage checks separate from local
  validation and do not require network access for `config-check`.

### R4 non-refactor diagnostic finding — document counts are labeled as requests

- **Status:** `ACCEPT`
- **Finding:** `SecSubmissionSnapshot.request_count` is `len(documents)`, including
  cache hits, while filing-sync output labels it `Requests`. It is a document-check
  count, not the number of HTTP attempts; retries are also not represented. The
  Company Facts command already uses the clearer label `SEC documents checked` and
  derives network downloads by subtracting cache hits.
- **Disposition:** rename the internal field or at minimum the filing-sync output and
  typed result to `documents_checked`, while preserving the numerical value and health
  cache-hit calculation. Do not claim to expose HTTP-attempt telemetry unless the
  transport explicitly records it.

### R4 preserve/do-not-do decisions

- Keep official SEC HTTPS host restrictions, declared user agent, rate limit, retry
  set/backoff, stale-cache disclosure, and maximum-stale ceiling.
- Keep canonical archive URL construction, unsafe-path rejection, current/history
  intersection, accession deduplication, point-in-time timestamps, amendment handling,
  deterministic ordering, and per-ticker active/inactive storage semantics.
- Keep identity and submissions parsing strict and loud; do not substitute partial or
  guessed issuer identities when the SEC payload is malformed.
- Keep the current requests library and synchronous morning-run model. No asynchronous
  client, background service, generic provider framework, ORM, or cache dependency is
  justified by R4.
- Do not combine the structural extraction with TTL, retry, rate-limit, filing-form,
  history-window, or provider-health policy changes.

### R4 decision summary

| ID | Decision | Implementation consequence |
|---|---|---|
| SEC-01 | `MODIFY` | Stage cohesive SEC modules only after R5 fixes shared types; preserve `stockrank.data.sec` as a compatibility facade |
| SEC-02 | `MODIFY` | Extract only the SEC disk-record codec/store; keep freshness and fallback policy in `SecClient` |
| SEC-03 | `ACCEPT` | Add one pure primary-plus-predecessor entity-target resolver shared by filings and Company Facts |
| SEC-04 | `MODIFY` | Extract a bounded filings-sync operation after command characterization; avoid speculative protocols |
| SEC-05 | `ACCEPT` | Move effective-filing selection to one pure domain entry point; keep parsing with ingestion |

## R5 — SEC financial calculations and refresh orchestration

### Frozen internal reviewer instruction

Act as an independent, clinical architecture and refactoring reviewer. Analyze the
repository directly but do not edit production code, generate replacement code, add
features, change a formula, change a provider or concept mapping, or alter point-in-
time, persistence, refresh, ranking, or shadow-evidence behavior. Focus on Company
Facts normalization and effective selection, adaptive refresh policy and state,
financial period construction and formulas, immutable snapshot creation, SEC fact and
snapshot persistence, Company Facts/financial CLI orchestration, shadow-comparison
consumers, and all direct or indirect tests. Reconcile R4's deferred Company Facts
module boundary, R1's deferred SEC command boundary, and R3's deferred SEC persistence
aggregate without presuming that every large file should be split. Preserve exact
Decimal calculations, missing/invalid/excluded states, source lineage, formula and
configuration fingerprints, historical records, failure continuation, and production-
ranking isolation. Identify at most five cohesive recommendations, cite exact symbols
and evidence, state a proposed boundary, risks, prerequisite tests, priority,
difficulty, and confidence, and explicitly identify code that should stay. If a
finding is a product or historical-integrity bug rather than a refactor, label it
separately instead of hiding a behavior change inside structural work.

The following reviewer output was frozen before adjudication. `INTAKE` records a
proposal, not approval.

### FIN-01 — finalize a Company Facts capability and pure effective-fact policy

- **Status:** `INTAKE`
- **Reviewer proposal:** complete the Company Facts portion of R4's provider split by
  moving concept configuration and Company Facts normalization into one cohesive
  capability and exposing effective-fact/restatement selection as a pure domain
  function. Keep `stockrank.data.sec` as the compatibility facade.
- **Evidence:** `load_sec_concept_specs`, `SecConceptSpec`,
  `SecCompanyFactsSnapshot`, and `SecCompanyFacts` occupy lines 96–115, 186–242, and
  838–1,143 of `data/sec.py`. `SecCompanyFacts.effective_facts` performs no I/O but is
  called by financial calculations and CLI status/sync code through the network-
  backed class, mirroring the R4 effective-filings dependency.
- **Proposed interface:** a Company Facts adapter/configuration module consuming the
  R4 transport and identity types, plus one pure typed selector accepting facts and an
  optional aware cutoff. Re-export existing public names while callers migrate.
- **Claimed benefit:** finish the provider capability split with a clear dependency
  direction and make correction/restatement selection independently testable and
  reusable by calculation and historical-vintage work.
- **Primary risks:** changed concept priority, context key, availability cutoff,
  restatement order, duplicate behavior, public imports, or circular dependencies.
- **Prerequisite tests:** current normalization/conflict fixtures plus multiple units,
  aliases, amendment order, identical acceptance times, accession tie-breaks, missing
  acceptance timestamps, aware cutoff boundaries, naive rejection, and facade import
  compatibility.
- **Reviewer rating:** priority high; difficulty 5/10; confidence high.

### FIN-02 — extract the Company Facts synchronization operation from the CLI

- **Status:** `INTAKE`
- **Reviewer proposal:** resolve the Company Facts portion of CLI-01 by moving the
  per-universe adaptive synchronization lifecycle out of `command_sec_facts_sync` into
  a narrowly named application operation returning typed per-ticker and aggregate
  results. Reuse R4's approved entity-target resolver and the existing pure refresh
  policy rather than creating a generic provider service.
- **Evidence:** `command_sec_facts_sync` lines 875–1,159 selects scope; constructs SEC,
  concept, identity, override, refresh-policy, and storage dependencies; fingerprints
  state; decides refresh/reuse; fetches and deduplicates multiple CIKs; replaces facts;
  conditionally writes refresh state; computes coverage/timing/health; formats output;
  and maps an exit code. No command-level test executes this lifecycle.
- **Proposed interface:** an operation accepting an explicit clock, scope, force/history
  inputs, Company Facts gateway, current filing/fact/state repository operations, and
  refresh policy. It returns ordered outcomes, coverage, stale/date-only diagnostics,
  refresh reasons, and timing-neutral counters. Keep argparse and console formatting in
  CLI code and SQL ownership in storage.
- **Claimed benefit:** directly test the adaptive refresh and partial-failure contract
  without live SEC traffic or a 285-line command handler.
- **Primary risks:** changing the refresh decision order, raw-cache bypass, stale-state
  handling, per-CIK atomicity, fact keys, observation history, partial writes, coverage,
  health status, or output order.
- **Prerequisite tests:** every refresh reason; primary/predecessor merge; missing
  filings; reuse without writes; stale snapshot behavior; changed/identical fact
  observations; state write only after a non-stale successful batch; per-CIK failure;
  partial versus full scope health; exact counters; output/exit characterization; and
  deterministic failure ordering.
- **Reviewer rating:** priority high; difficulty 8/10; confidence high.

### FIN-03 — extract a financial-snapshot build operation from CLI presentation

- **Status:** `INTAKE`
- **Reviewer proposal:** resolve the local-financial portion of CLI-01 by moving
  universe traversal, fact loading, snapshot calculation/persistence, and aggregate
  coverage into a command-agnostic operation. Keep `SecFinancialCalculator` focused on
  one ticker and keep the command responsible for argument parsing, display, health
  recording, and exit-code mapping.
- **Evidence:** `command_sec_financials_build` lines 1,219–1,330 selects scope and cutoff,
  loads facts, calls the calculator, appends immutable snapshots, calculates 11 coverage
  measures/exclusions, records health, formats warnings, and asserts ranking isolation.
  Tests exercise the calculator and storage separately but not this application
  lifecycle.
- **Proposed interface:** an operation with explicit cutoff, selected securities,
  calculator, clock/ID boundary, and snapshot repository, returning ordered snapshots,
  failures, coverage, and scope status. Snapshot metadata generation may be injected or
  wrapped so formula outputs remain deterministic under test.
- **Claimed benefit:** characterize multi-ticker failure/append behavior and keep local
  calculation orchestration independent from console presentation.
- **Primary risks:** changing immutable append behavior, snapshot IDs/times, company or
  sector attribution, coverage keys, formula version, health, failure continuation, or
  accidentally reading/writing production ranking rows.
- **Prerequisite tests:** full/partial/unknown scope; no facts; calculator and persistence
  failures; sparse/invalid/excluded metrics; exact coverage; immutable append order;
  cutoff parsing; formula manifest propagation; provider-health row; output/exit code;
  and proof that ranking tables are untouched.
- **Reviewer rating:** priority medium-high; difficulty 6/10; confidence high.

### FIN-04 — split period construction from metric formulas through a period ledger

- **Status:** `INTAKE`
- **Reviewer proposal:** split `sec_financials.py` into a period-normalization module and
  a metric-formula module. Build an immutable per-concept period ledger once, containing
  annual, discrete-quarter, YTD, TTM, and instant observations, then calculate growth,
  FCF, margins, ROE, and current ratio from that ledger instead of repeatedly invoking
  `_annual`, `_quarters`, `_ttm`, and `_period_value`.
- **Evidence:** `sec_financials.py` is 729 lines. `build_snapshot` recomputes the same
  period transforms in base metrics, growth, four FCF periods, four margin periods,
  FCF-margin lineage, and ROE. Period construction and metric formulas are conceptually
  distinct even though both are currently pure.
- **Proposed interface:** an internal immutable `FinancialPeriodBook` produced from
  effective facts and consumed by formula functions. Preserve `SecFinancialCalculator`
  as the caller-facing API and keep exact observations/lineage accessible.
- **Claimed benefit:** compute each period interpretation once, prevent different
  formulas from drifting on period selection, and make period construction directly
  testable.
- **Primary risks:** a large high-risk rewrite, changed restatement/quarter selection,
  loss of Decimal or lineage fidelity, eager derivation of unused periods, circular
  types, and abstraction overhead with no second consumer.
- **Prerequisite tests:** exhaustive golden outputs for every current metric/quality/
  reason/lineage field; 52/53-week and non-calendar years; reported-versus-derived
  quarter precedence; gap/unit failures; cumulative shares and prohibited EPS
  subtraction; comparison tolerances; negative/zero denominators; sector exclusions;
  and stored snapshot equality before and after extraction.
- **Reviewer rating:** priority medium; difficulty 9/10; confidence medium.

### FIN-05 — make the SEC formula manifest an explicit transitive contract

- **Status:** `INTAKE`
- **Reviewer proposal:** replace the single-file self-hash in `formula_manifest` with an
  explicit, stable formula-contract manifest that covers every source/policy dependency
  capable of changing a financial snapshot, while retaining the semantic formula
  version and stored full fingerprint.
- **Evidence:** `formula_manifest` lines 74–85 hashes `sec_financials.py` only. Snapshot
  output also depends on `SecCompanyFacts.effective_facts` in `data/sec.py`, concept
  normalization/configuration, and model shapes outside that file. Conversely, a
  comment or formatting-only edit inside `sec_financials.py` changes the fingerprint.
  R4/R5 module extraction would otherwise change or weaken the current fingerprint
  depending on where helpers move.
- **Proposed interface:** a versioned manifest builder with an explicit ordered source
  registry and stable policy definitions, analogous to the ranking calculation
  contract. Store both semantic version and implementation/policy fingerprints; never
  recompute or overwrite manifests on old snapshots.
- **Claimed benefit:** make formula identity survive structural refactoring without
  omitting transitive calculation dependencies or pretending one semantic version has
  an unexplained implementation.
- **Primary risks:** accidental formula-version bump, platform-dependent source hashes,
  omitted dependencies, noisy fingerprints, invalidating old snapshots, or coupling
  SEC formulas to unrelated ranking code.
- **Prerequisite tests:** newline/platform stability; dependency-order stability;
  sensitivity to each formula/selection dependency; insensitivity to unrelated files;
  exact round-trip storage; old-manifest readability; and an explicit version-bump rule
  distinguishing structural from semantic calculation changes.
- **Reviewer rating:** priority high; difficulty 5/10; confidence high.

### R5 adjudication baseline

- `sec_refresh.py` is a cohesive 131-line pure-policy module. Its policy object,
  fingerprints, filing-date helper, and refresh decision function have one clear
  purpose and should stay together rather than be absorbed into a generic service.
- `sec_financials.py` is 729 lines, but size alone overstates its structural problem.
  Its period helpers and formulas are deterministic, use exact `Decimal` arithmetic,
  preserve source lineage, and have one production consumer through
  `SecFinancialCalculator`. The largest untested boundary is the surrounding command
  lifecycle, not the pure formula module.
- `command_sec_facts_sync` is approximately 285 lines and combines target resolution,
  adaptive-refresh decisions, provider calls, fact and observation persistence,
  refresh-state writes, coverage, health, diagnostics, and console output.
  `command_sec_financials_build` is approximately 112 lines and combines local fact
  loading, calculation, immutable snapshot persistence, aggregate coverage, health,
  and presentation. Existing CLI tests mock these handlers rather than execute either
  lifecycle.
- Storage maintains both the latest normalized Company Facts rows and immutable fact
  observations. Production financial calculation reads only the latest normalized
  rows; the observation history currently has no production reader. A controlled
  diagnostic stored a value observed on 2025-02-21 and a correction to the same fact
  key observed on 2026-02-21, then built a snapshot with a 2025-12-31 cutoff. The
  calculator selected the later corrected value. Filing acceptance was filtered by
  the cutoff, but the time when that correction became locally available was not.
- `formula_manifest` hashes only `sec_financials.py`. Snapshot results also depend on
  Company Facts effective-selection policy and configured concept mappings, while
  comment, formatting, newline, or boundary-only changes inside that single file can
  alter its fingerprint.
- Provider-shadow construction selects the latest SEC snapshot available at its
  cutoff and records its snapshot ID, but qualification does not require one approved
  SEC formula version/manifest across the full universe. A partial rebuild can
  therefore compare a mixture of old and current snapshot contracts without making
  that mixture disqualifying.
- A refresh-policy diagnostic supplied a `last_successful_refresh_at` one day in the
  future. The current policy returned `refresh=False`. Stored timestamps are also
  converted with `astimezone(UTC)` without first rejecting naive values. The three
  adaptive-refresh configuration values are constructed in the CLI but are not
  covered by local `validate_settings` checks.
- Focused R5 tests cover Company Facts normalization, refresh-policy reasons,
  individual financial calculations, persistence, and comparison classification.
  They do not yet characterize the two complete command lifecycles, historical fact
  vintages, mixed formula contracts, or several denominator/period edge cases.

### FIN-01 adjudication — Company Facts capability and pure selection policy

- **Decision:** `ACCEPT`
- **Verified problem:** Company Facts configuration, normalization, snapshot types,
  and effective selection form a cohesive capability distinct from transport,
  identity, and submissions. `effective_facts` is pure domain policy but is exposed
  through the network-backed `SecCompanyFacts` class to financial and CLI consumers.
- **Approved boundary:** complete the R4 staged provider split with a Company Facts
  capability that consumes the shared transport and identity types. Add one typed,
  pure effective-fact selector and retain an unchanged `stockrank.data.sec`
  compatibility facade while imports migrate. Keep concept configuration and payload
  normalization with this capability; do not create one module per type.
- **Implementation gate:** add the full normalization, tie-break, multi-unit,
  amendment, cutoff, naive-time, and compatibility tests listed in FIN-01 before
  moving code. FIN-SAFE-01 must define historical observation-time semantics before
  the selector is advertised or reused as a complete point-in-time policy.

### FIN-02 adjudication — Company Facts synchronization operation

- **Decision:** `MODIFY`
- **Accepted problem:** the current command hides a substantial application lifecycle
  whose refresh, partial-failure, persistence, and state-write contracts cannot be
  tested without console orchestration.
- **Modification:** extract one narrowly named Company Facts synchronization operation
  after command characterization. Reuse SEC-03's entity-target resolver, the concrete
  Company Facts adapter, `CompanyFactsRefreshPolicy`, and the existing caller-facing
  `Storage` facade. Do not introduce speculative gateway/repository protocols, a
  generic provider service, or timing internals in the returned domain result. The
  operation owns ordered per-ticker decisions, fetch/deduplication, fact/observation
  persistence, and successful refresh-state updates. The CLI retains settings and
  dependency construction, argument parsing, elapsed-time measurement, human-readable
  output, provider-health persistence, and exit-code mapping.
- **Preserved failure contract:** a failed CIK must not replace that ticker's facts or
  advance its successful refresh state, but already completed tickers remain written
  and later tickers continue. A reused ticker must not create replacement writes.
  Raw-cache bypass, stale-cache disclosure, unmatched accessions, coverage counters,
  and deterministic ordering remain unchanged.
- **Implementation gate:** execute every prerequisite in FIN-02 as command and
  operation characterization tests before extraction. Apply SEC-SAFE-01 through
  SEC-SAFE-03 and FIN-SAFE-03 first or in a separately approved behavior-fix slice;
  do not hide those changes in the file move.

### FIN-03 adjudication — financial-snapshot build operation

- **Decision:** `MODIFY`
- **Accepted problem:** multi-ticker traversal, local fact loading, immutable snapshot
  appends, failure continuation, and aggregate coverage are application orchestration,
  not console presentation or one-ticker financial calculation.
- **Modification:** extract one financial-snapshot build operation using the concrete
  calculator and existing `Storage` facade. It receives an already resolved scope and
  explicit cutoff and returns ordered snapshots, failures, and coverage. Keep
  `SecFinancialCalculator` responsible for one ticker and keep parsing, timing,
  provider-health persistence, output, and exit-code mapping in the CLI. An explicit
  snapshot metadata factory or clock may be added only where it makes IDs/timestamps
  deterministic in tests; do not turn every dependency into an interface.
- **Preserved behavior:** continue after a per-ticker calculation or persistence
  failure, append rather than mutate historical snapshots, retain exact company and
  sector attribution, propagate the exact formula manifest, and never read or write
  production ranking rows.
- **Implementation gate:** characterize full/partial/unknown scope, no-fact behavior,
  calculation and save failures, snapshot ordering, exact coverage/status, health,
  output/exit codes, and ranking isolation. Resolve FIN-SAFE-01 and FIN-SAFE-02 before
  treating historical or shadow evidence from the extracted operation as qualified.

### FIN-04 adjudication — proposed period-ledger split

- **Decision:** `REJECT`
- **Reason:** the proposal replaces a cohesive, deterministic formula engine with a
  new intermediate abstraction and a high-risk rewrite without a demonstrated second
  consumer, correctness defect, or material performance problem. The repeated period
  helper calls over one 50-stock morning universe do not justify changing how every
  metric obtains its periods and lineage. A 729-line file is not by itself evidence
  that `FinancialPeriodBook` would be clearer.
- **What remains valid:** missing formula and period edge-case tests are real coverage
  gaps. Add targeted tests for negative capital expenditure, zero/nonpositive or
  misaligned denominators, ROE equity constraints, TTM gaps/units, diluted-EPS
  non-subtraction, reported-versus-derived quarter precedence, and comparable-period
  duration before any formula-adjacent extraction.
- **Revisit trigger:** reconsider an internal period representation only if a second
  real calculator/consumer appears, profiling identifies period reconstruction as a
  meaningful bottleneck, or verified formula drift cannot be safely fixed through the
  existing helpers. Do not create it as a line-count reduction exercise.

### FIN-05 adjudication — explicit transitive formula contract

- **Decision:** `MODIFY`
- **Accepted problem:** the current self-hash is simultaneously incomplete and noisy.
  It omits effective-fact selection and concept policy that can change a snapshot, yet
  changes for comments, formatting, or a behavior-preserving file move.
- **Modification:** preserve the semantic formula version and every stored historical
  manifest. Define an explicit ordered dependency registry for deterministic
  calculation and selection policy, and record the configured concept-policy
  fingerprint separately from the implementation fingerprint. The registry must be
  narrow, platform-stable, and insensitive to unrelated files and structural moves.
  It must not hash ranking code, provider orchestration, storage mechanics, or raw
  personal configuration.
- **Version rule:** a change to metric meaning, period selection, quality/exclusion
  semantics, or lineage interpretation requires a reviewed semantic formula-version
  change. A verified behavior-preserving refactor may change implementation identity
  without claiming a new formula. Old snapshots remain readable with their original
  version and manifest and are never silently rewritten.
- **Implementation gate:** add the stability, sensitivity, round-trip, old-manifest,
  and explicit version-rule tests from FIN-05. FIN-SAFE-02 must use the resulting
  contract rather than merely checking that some manifest is present.

### Resolution of deferred STORE-02 — SEC persistence aggregate

- **Decision:** `MODIFY`
- **Verified boundary:** filings, current Company Facts, immutable fact observations,
  refresh state, and financial snapshots form a cohesive SEC persistence cluster, but
  provider ingestion and formula modules must not own SQL or database connections.
- **Approved direction:** after STORE-01 establishes schema/migration ownership, an
  internal SEC persistence aggregate may own these tables and queries behind the
  unchanged caller-facing `Storage` facade. Stage the move by table cluster and retain
  existing transaction, replacement, append, ordering, and row-conversion behavior.
- **Not approved:** no ORM, generic repository framework, public caller rewrite,
  independent database, or relocation of SQL into `data/sec.py`, `sec_refresh.py`, or
  `sec_financials.py`. Cross-review synthesis will place this work relative to FIN-02
  and FIN-03 so orchestration extraction does not depend on two simultaneous boundary
  changes.

### R5 non-refactor safety findings

#### FIN-SAFE-01 — reconstruct fact vintages for historical cutoffs

- **Status:** `ACCEPT`
- **Finding:** immutable observation history preserves later corrections, but a
  historical `--as-of` financial build reads only the latest normalized fact row.
  The calculator can therefore use a value first observed after the requested cutoff,
  even when its SEC filing acceptance predates the cutoff. This does not invalidate a
  current-date morning snapshot, but it makes the historical cutoff incomplete as a
  point-in-time guarantee.
- **Disposition:** define and implement a storage/domain query that reconstructs each
  stable fact key from the latest eligible observation with `observed_at <= cutoff`,
  then applies effective-fact/restatement selection. If no eligible observation exists,
  omit or explicitly limit the metric rather than backfill later knowledge. Legacy
  seed observations are known only from their seed observation time and must not be
  treated as historically available before that date. Add correction, amendment,
  legacy-seed, exact-boundary, and no-eligible-vintage tests. Implement this as a
  separately reviewed behavior/data-integrity fix, not as part of a refactoring move.

#### FIN-SAFE-02 — require one formula contract for qualified shadow evidence

- **Status:** `ACCEPT`
- **Finding:** a full-universe shadow comparison can consume SEC snapshots carrying
  different or unsupported formula versions/manifests after a partial build. Snapshot
  IDs preserve traceability, but the evidence classifier does not make the mixed
  calculation contract disqualifying.
- **Disposition:** define the approved SEC formula contract for a comparison run and
  require every included SEC snapshot to match it. Missing, mixed, or unsupported
  contracts must produce explicit nonqualification and diagnostics, never silent
  promotion evidence. Store or derive the exact contract set used by the run, and
  report actual versions/manifests rather than only the current code constant. Keep
  this isolated from production ranking until the existing promotion gate is met.

#### FIN-SAFE-03 — validate adaptive-refresh timestamps and configuration

- **Status:** `ACCEPT`
- **Finding:** refresh state and latest-filing timestamps are converted to UTC without
  explicitly rejecting naive datetimes, and a future successful-refresh timestamp can
  suppress refreshes until the local clock catches up. The adaptive full-refresh,
  filing-window, and retry values are not checked by local configuration validation.
- **Disposition:** require aware timestamps at the policy boundary; treat materially
  future refresh state as invalid and refresh rather than reuse, with any small clock-
  skew tolerance explicit and tested. Add side-effect-free validation for all three
  adaptive settings using the same bounds accepted by `CompanyFactsRefreshPolicy`.
  Preserve the current seven-day safety refresh and recent-filing follow-up defaults;
  this finding does not authorize a policy-interval change.

### R5 preserve/do-not-do decisions

- Keep exact `Decimal` arithmetic, deterministic period ordering, source fact IDs and
  accession lineage, reported-versus-derived quality states, sector exclusions,
  missing/invalid reasons, and immutable financial snapshot history.
- Keep Company Facts normalization strict, its configured concept/member priority,
  stable fact keys, current-row replacement plus observation history, and explicit
  stale-cache diagnostics.
- Keep `sec_refresh.py` as a small pure-policy module and keep the period/formula
  helpers together in `sec_financials.py` unless FIN-04's concrete revisit trigger is
  met.
- Keep SEC financial calculation local, synchronous, and isolated from production
  rankings. No background service, async fetch fan-out, ORM, generic provider
  framework, alternate data source, formula/scoring change, or automatic provider
  promotion is justified by R5.
- Do not combine historical-vintage repair, formula-contract qualification, refresh
  validation, module extraction, and persistence splitting in one implementation
  commit merely because they touch the same subsystem.

### R5 decision summary

| ID | Decision | Implementation consequence |
|---|---|---|
| FIN-01 | `ACCEPT` | Complete the Company Facts capability behind the SEC facade and expose one pure selector |
| FIN-02 | `MODIFY` | Extract a bounded facts-sync operation after characterization; retain concrete gateways and CLI presentation |
| FIN-03 | `MODIFY` | Extract the local financial-build lifecycle while keeping one-ticker calculation and health/output ownership clear |
| FIN-04 | `REJECT` | Keep the cohesive formula engine; add missing edge-case tests instead of a speculative period ledger |
| FIN-05 | `MODIFY` | Define a stable transitive formula contract with separate semantic, implementation, and concept identities |
| STORE-02 | `MODIFY` | Permit an internal SEC persistence aggregate only behind `Storage` and after schema ownership is extracted |

## Cross-review synthesis

Completed on 2026-08-31 from the internally adjudicated R1–R5 decisions. The
external-model R1 and R2 proposals remain above as audit history, but their internal
re-reviews are authoritative. This synthesis approves no production change by
itself; it defines the bounded program that must be approved before implementation.

### Synthesis outcome

The review found justified refactoring, but it did **not** justify a broad rewrite.
The correct program is to repair verified behavior and data-integrity defects first,
establish executable characterization, extract a small number of pure policies and
application operations, and only then split the large modules behind compatible
facades. File length is not an implementation goal.

The program is divided into five work packages and 27 independently reviewable
substeps. Several substeps are test-only or narrow safety changes; they are not 27
large features. Each substep is intended to become one local checkpoint unless its
gate explicitly requires a tests-first checkpoint. Nothing in this program changes
the production ranking model, promotes SEC data, expands the universe, or adds a new
provider.

### Resolved cross-review boundaries

| Concern | Final owner and boundary |
|---|---|
| Command parsing, dependency construction, timing, health persistence, user output, and exit codes | `cli.py`; concise composition and presentation remain valid CLI responsibilities |
| Filing sync, Company Facts sync, financial build, and provider-shadow execution | Four distinct application operations; no generic provider service, command bus, or universal result |
| Provider comparison calculations | `provider_comparison.py`; calculation formulas do not move into evidence or orchestration code |
| Provider promotion-evidence policy | A pure typed evaluator in a narrowly named provider-evidence boundary, followed later by a separate comparison-run operation |
| SEC transport and cache policy | SEC transport capability; private cache codec/path handling may move, but freshness, force, retry, and stale fallback remain visible in `SecClient` |
| SEC identity, submissions, and Company Facts | Cohesive capability modules behind the unchanged `stockrank.data.sec` facade and unchanged public symbol identity |
| Effective filing/fact and entity-target policy | Pure typed SEC domain functions; parsing, configuration validation, and network work remain outside them |
| SEC SQL | An internal SEC persistence aggregate may eventually own it, but only behind the caller-facing `Storage` facade and only after schema ownership and operation extraction |
| Schema and migrations | `storage_schema.py`; exact current-schema ownership precedes any new schema version or persistence split |
| Runtime cleanup | Pure bounded planner plus exact-plan apply helper; CLI keeps preview/confirmation and `Storage` keeps database cleanup |
| Personalization | Pure proposal construction in `customization.py`, bounded two-file apply/reset, and CLI-owned interaction |
| Dashboard data | Fresh uncached report-bound and installation-current read models with explicit provenance; rendering performs no storage reads |
| Dashboard transformations | Only stable Streamlit-free logic moves to existing `presentation.py` or `summaries.py`; CSS-coupled HTML, charts, and notices stay near rendering |
| Dashboard rendering | One page entry point and a short ordered sequence of section functions; no controller, component framework, or one-module-per-section design |
| SEC financial formulas | `sec_financials.py` remains cohesive; no `FinancialPeriodBook` or line-count-driven formula rewrite |

Default module names are descriptive rather than architectural commitments:
`storage_schema.py`, `storage_sec.py`, `provider_evidence.py`,
`runtime_maintenance.py`, `dashboard_state.py`, and narrowly named SEC operation and
capability modules. A name may change during implementation when the dependency
direction is clearer, but the approved ownership above may not change without a new
ledger decision.

### Dependency order

The mandatory dependency direction is:

1. verified behavior and trust-boundary repairs;
2. schema ownership and formula/evidence contracts;
3. executable characterization and pure policies;
4. provider capability and application-operation extraction;
5. persistence and dashboard structural decomposition;
6. compatibility cleanup only after all consumers have migrated.

This order resolves the R1–R5 overlaps:

- SEC commands use the pure entity/effective-selection policies before their loops
  move into application operations;
- the SEC provider modules move behind the existing facade separately from command
  operations, and the operations continue to use the `Storage` facade;
- the SEC persistence aggregate comes last, so an operation never changes provider,
  application, and SQL boundaries in one commit;
- exact schema ownership and historical migration tests precede any schema version
  used to record stronger provider-evidence metadata;
- the explicit formula contract precedes both the historical-vintage repair and the
  qualified shadow-evidence gate;
- dashboard execution is characterized before render restructuring, and provenance
  meaning is corrected before read-state loaders are extracted.

### Proposed bounded implementation program

The difficulty rating is 1–10. Reasoning recommendations use the application's
available Light, Medium, High, and Extra High settings. Extra High remains reserved
for exceptional work with several interacting architectural, safety, or financial-
integrity risks.

#### Work package 1 — correctness and trust-boundary baseline

| ID | Scope | Difficulty | Reasoning | Acceptance gate |
|---|---|---:|---|---|
| S1.1 | Fix the daily workflow's duplicate validation and the legacy validation `UnboundLocalError` | 6 | High | Standalone `run` intentionally retains one validation; `daily-report` performs one base analysis and one final validation; all optional metadata combinations and shadow-skip states pass |
| S1.2 | Validate positive bounded retention, all local SEC settings, and adaptive-refresh settings; wrap override file/TOML failures | 5 | High | `config-check` rejects every invalid local value without network access; cleanup refuses unsafe retention before planning or deletion |
| S1.3 | Make the two private personalization files an all-applied-or-restored update/reset | 7 | High | Staging, replacement, backup, rollback, and reload failures leave the prior effective pair restored where possible and provide a clear recovery result on Windows and macOS |
| S1.4 | Harden SEC cache metadata, submissions CIK identity, refresh timestamps, and the misleading request-count label | 7 | High | Unsupported/malformed/naive/future cache metadata becomes a silent miss; wrong root CIK is rejected; invalid/future refresh state refreshes; output says `documents checked` without changing its value |
| S1.5 | Establish an isolated executed dashboard baseline, then fix missing-cutoff filing disclosure and the incomplete no-candidate explanation | 7 | High | Temporary fixtures touch no runtime/network state; current/no-run/legacy paths execute; report and dashboard withhold unbounded filings and use stored score, coverage, price, and liquidity rules |
| S1.6 | Correct dashboard report-bound versus installation-current provenance | 8 | Extra High | Report evidence uses stored membership/cutoffs and `analysis_run_id`; current diagnostics state checked time, active universe/config/policy, and mismatches; missing report evidence is never replaced with current data |

S1.1 adopts the recommended command contract: `stockrank run` remains the convenient
analysis-plus-one-validation command, while the eight-step daily workflow invokes a
base-analysis path in step 6 and validates once in step 8. The shadow step is skipped
unless step 6 produced a completed production run, rather than inheriting a combined
analysis-and-validation integer accidentally.

S1.5 may begin with an `AppTest.from_file` characterization against a disposable
project root if the current top-level page cannot yet be called directly. It migrates
to the approved function-based seam in S5.3. Executed tests must be added before any
equivalent source-string assertion is removed.

#### Work package 2 — persistence and financial-evidence integrity

| ID | Scope | Difficulty | Reasoning | Acceptance gate |
|---|---|---:|---|---|
| S2.1 | Extract exact version-10 fresh-schema ownership and refuse future versions | 8 | Extra High | Fresh schema inventory is byte-for-policy equivalent, repeated initialization is idempotent, and a version above 10 fails without changing the database |
| S2.2 | Build historically grounded version-1-through-9 fixtures and convert compatibility repairs into an ordered migration registry | 9 | Extra High | Representative historical rows and every current backfill survive each supported upgrade; another machine's runtime database is never used without a backup |
| S2.3 | Add the missing formula and period edge-case characterization rejected as justification for a period-ledger rewrite | 7 | High | Negative capex, denominator/alignment constraints, ROE equity, TTM gaps/units, diluted EPS, quarter precedence, and comparable-duration cases are explicit and deterministic |
| S2.4 | Define the transitive SEC formula contract with separate semantic version, implementation fingerprint, and concept-policy fingerprint | 8 | Extra High | Identity is platform-stable, sensitive only to approved calculation/selection dependencies, round-trips through snapshots, reads old manifests, and is unchanged by structural file moves |
| S2.5 | Reconstruct fact vintages for historical cutoffs | 10 | Extra High | Values come only from observations known at or before the cutoff; correction, amendment, seed, exact-boundary, and no-eligible-vintage cases pass; current ranking rows remain untouched |
| S2.6 | Record and enforce one supported formula contract for each qualified provider-shadow run through a pure evidence evaluator | 9 | Extra High | A narrow post-S2.2 schema evolution records the exact contract set when derivation is insufficient; missing/mixed/unsupported contracts are diagnostic and nonqualifying; every evidence reason and precedence is tested |

S2.5 is a data-integrity correction, not a cosmetic refactor. Because observation-
time selection changes point-in-time calculation semantics, it requires an explicit
reviewed formula-version decision before implementation. Old snapshots remain
readable and are never rewritten.

S2.6 creates a second explicit approval decision. Existing shadow runs were created
before concept-policy identity and the complete transitive contract were recorded.
The conservative recommendation is to keep those runs visible as legacy evidence but
not count them toward the strengthened Step 2.4B gate. Do not silently grandfather or
rewrite them. This can reduce the local qualifying-date count and require collecting
new full-universe market dates; the user must approve that consequence before S2.6.

#### Work package 3 — pure policies and small testable seams

| ID | Scope | Difficulty | Reasoning | Acceptance gate |
|---|---|---:|---|---|
| S3.1 | Extract the pure historical-comparison eligibility evaluator and remove only verified dead Storage API | 6 | High | Exact candidate order and limitation precedence remain unchanged; no hidden reads are introduced; obsolete timezone and test-only wrappers are gone |
| S3.2 | Extract bounded runtime inventory/planning/apply policy | 6 | High | Temporary-root tests prove preview/apply parity, cutoff equality, protected names, direct-child scope, containment recheck, dry-run behavior, and unsafe-plan refusal |
| S3.3 | Add one entity-target resolver plus one final effective-filing and one effective-fact selector | 8 | Extra High | Primary/predecessor parity, deduplication, unresolved identities, amendment/restatement ties, cutoffs, units, and naive-time rejection are characterized before callers migrate |
| S3.4 | Add the typed pure customization proposal builder | 5 | Medium | Interactive and noninteractive inputs produce the same validated proposal/fingerprints; effective settings reload after apply; provider progress and prompts remain in CLI |
| S3.5 | Move only stable deterministic dashboard transforms to existing pure helpers | 5 | Medium | Candidate ordering, finite legacy labels, sparse rows, comparison aggregation, CSV bytes, score breakdowns, percentages, and gold endpoints remain exact |

Every extraction in this package retains its current caller-facing API until all
callers have migrated. Temporary wrappers may exist within a substep but may not
survive the final closeout without an identified compatibility consumer.

#### Work package 4 — SEC capabilities and application operations

| ID | Scope | Difficulty | Reasoning | Acceptance gate |
|---|---|---:|---|---|
| S4.1 | Split SEC transport and its private cache codec/store behind the existing facade | 8 | Extra High | Public symbol inventory, class identity, monkeypatch paths, cache filenames/bytes, atomic replacement, TTL boundaries, stale fallback, retries, and no-redownload behavior remain exact |
| S4.2 | Split identity, submissions, and Company Facts capabilities behind the same facade | 9 | Extra High | Constructors, exceptions, normalization, ordering, canonical URLs, overrides, and every direct/indirect import remain compatible on Windows and macOS |
| S4.3 | Extract the filing-sync application operation | 7 | High | Command output/health/exit characterization passes; a failed CIK does not replace that ticker, completed tickers stay written, and later tickers continue |
| S4.4 | Extract the Company Facts synchronization operation | 8 | Extra High | Ordered refresh/reuse decisions, raw-cache bypass, observations, unmatched accessions, state writes, partial failure, stale disclosure, and coverage remain exact |
| S4.5 | Extract the financial-snapshot build operation | 9 | Extra High | Scope/cutoff, per-ticker continuation, immutable append, snapshot order, lineage, coverage, formula contract, health, output, and production-ranking isolation remain exact |
| S4.6 | Extract the provider-shadow comparison-run operation after the S2.6 evidence evaluator | 8 | Extra High | Run/result identity, chronology, storage, partial failures, health, output, return codes, evidence decisions, and ranking isolation remain exact |

Each application-operation substep begins by executing the complete command
characterization listed in its R1/R4/R5 adjudication. The command keeps dependency
construction, timing, provider-health persistence, presentation, and return-code
mapping. No speculative interfaces are added merely to make the operation testable.

#### Work package 5 — final structural decomposition and closeout

| ID | Scope | Difficulty | Reasoning | Acceptance gate |
|---|---|---:|---|---|
| S5.1 | Move the cohesive SEC table/query cluster into an internal aggregate behind `Storage` | 9 | Extra High | Move one table cluster at a time; transactions, replacement/append behavior, observation history, ordering, row conversion, and every caller remain unchanged |
| S5.2 | Extract fresh uncached report-bound and installation-current dashboard read models | 8 | Extra High | Rendering performs no storage reads; provenance, unavailable/mismatch states, query inventory, and lack of cache remain explicit and tested |
| S5.3 | Add the explicit dashboard page entry and ordered section functions | 7 | High | Page config is first; no-run stop, section order, tabs/expanders, widget identity, fixed charts, tooltips, notices, download, theme, and responsive appearance match executed tests and both README screenshots |
| S5.4 | Remove temporary wrappers and obsolete source assertions, update documentation, and perform the final no-change audit | 4 | Medium | Only wrappers with no consumer are removed; executed coverage exists first; public/import inventory, commands, private-file exclusions, full tests, CI, and manual Windows/macOS dashboard/morning checks pass |

S5.1 deliberately follows the application-operation extractions. The operations use
one stable `Storage` facade while SQL moves behind it, preventing a simultaneous CLI,
provider, orchestration, and persistence rewrite. S5.3 begins with functions in the
existing dashboard module; a new section module is allowed only if the final function
signatures demonstrate one cohesive boundary.

### Approval and stop gates

1. **Gate G0 — synthesis approval:** no production implementation begins until the
   user approves this ordered program. Documentation-only review checkpoints may be
   committed locally before that approval.
2. **Gate G1 — correctness review:** stop after Work package 1. Run focused and full
   deterministic tests, cross-platform CI, a disposable-data daily workflow, and a
   user-visible dashboard review before touching formula or schema contracts.
3. **Gate G2 — formula/evidence decision:** stop after S2.4. Present the exact semantic
   formula-version change required by S2.5 and the expected Step 2.4B evidence-count
   consequence of S2.6. Obtain explicit user approval before either change.
4. **Gate G3 — boundary review:** stop after Work package 3. Confirm the final public
   symbol inventory and proposed module import graph before moving provider code.
5. **Gate G4 — operation review:** stop after Work package 4. Require full tests and
   CI plus real `morning` verification on Windows and the supported macOS 11 path
   before moving SEC SQL or restructuring dashboard rendering.
6. **Gate G5 — final review:** after Work package 5, compare behavior, performance,
   reports, dashboard screenshots, setup paths, docs, and Git privacy. Push only with
   explicit user authorization.

At any gate, a newly discovered product or financial-integrity defect pauses the
refactor. It is documented and adjudicated as a separate behavior change rather than
being hidden inside the active structural substep.

### Per-substep implementation contract

Every substep must:

1. start from a clean or fully understood worktree and name the exact accepted ledger
   decisions it implements;
2. add failing regression tests for behavior fixes, or passing characterization tests
   before structural movement;
3. touch only one approved boundary and preserve unrelated user changes;
4. run focused tests, then the required broader suites in proportion to risk;
5. inspect staged files and prove that `.env`, `config/*.local.*`, `runtime/`, caches,
   databases, reports, logs, and secrets are absent;
6. record results and any deviation in this ledger;
7. stop for user review before a checkpoint commit when the substep changes visible
   behavior, schema, formula identity, dashboard appearance, or runtime compatibility.

Network/live-provider tests are never a substitute for deterministic fixtures and
are run only when the approved gate requires them. Runtime databases from another
computer are not modified for migration testing without a backup and explicit user
participation.

### Traceability from R1–R5

| Authoritative decision | Planned substep(s) |
|---|---|
| CLI-RR-01 / SEC-04 / FIN-02 / FIN-03 | S3.3, S4.3–S4.5 |
| CLI-RR-02 | S2.6, S4.6 |
| CLI-RR-03 | S1.3, S3.4 |
| CLI-RR-04 / STORE-05 | S1.2, S3.2 |
| CLI-RR-SAFE-01 / SAFE-02 / SAFE-03 | S1.1, S1.3 |
| DASH-RR-01 / SAFE-01 | S1.6, S5.2 |
| DASH-RR-02 | S3.5 |
| DASH-RR-03 / DASH-RR-04 | S1.5, S5.3–S5.4 |
| DASH-RR-SAFE-02 / SAFE-03 | S1.5 |
| STORE-01 | S2.1–S2.2 |
| STORE-02 | S5.1 |
| STORE-03 / STORE-04 | S3.1 |
| R3 retention safety | S1.2 |
| SEC-01 / SEC-02 | S4.1–S4.2 |
| SEC-03 / SEC-05 / FIN-01 | S3.3, S4.2 |
| SEC-SAFE-01 / SAFE-02 / SAFE-03 / diagnostic | S1.2, S1.4 |
| FIN-04 | S2.3; formula engine otherwise stays intact |
| FIN-05 | S2.4 |
| FIN-SAFE-01 / SAFE-02 / SAFE-03 | S1.2, S1.4, S2.5–S2.6 |

### Global no-change list

- No production scoring-model, weights, candidate thresholds, production provider
  precedence, or automatic provider promotion changes.
- No universe expansion, dynamic-universe implementation, backtest, broker
  connection, trading action, background process, or new paid/free provider.
- No alteration of command names/options, eight-step morning order, report content,
  dashboard design, stdout/stderr, exit codes, or timing labels except the explicitly
  approved correctness and diagnostic fixes above.
- No rewriting of historical runs, financial snapshots, provider-comparison rows, or
  personal runtime state to make a refactor appear compatible.
- No ORM, database server, async SEC client, cache library, generic provider service,
  service container, command framework, dashboard controller/component system, or
  one-file-per-command/section structure.
- No formula-engine decomposition unless FIN-04's concrete revisit trigger occurs.
- No mutable dashboard cache and no pixel-diff screenshot CI.
- No cleanup expansion beyond explicit direct-child runtime directories and no
  staging of private local configuration or runtime artifacts.

## Supplemental post-synthesis size review — Gemini

On 2026-09-01, the user supplied a lightweight external review that identified
`storage.py`, `cli.py`, and `dashboard.py` as large modules worth examining. It
proposed storage submodules, separate command handlers, and a secondary dashboard
review. These are size-based prompts for review, not evidence of a new defect.

- The CLI suggestion is already covered by R1 and S3/S4: characterize commands first,
  then extract only the distinct SEC, financial, provider-shadow, and customization
  operations. Parsing already lives in `command_parser.py`; interaction, dependency
  construction, output, and exit codes deliberately remain at the CLI boundary.
- The storage suggestion is already covered by R3, S2.2, and S5.1: establish explicit
  schema ownership, then move one cohesive SEC table/query cluster behind the
  compatible `Storage` facade. The project has no ORM layer, and a broad split of
  connections, queries, and file I/O is not approved.
- The dashboard suggestion is already covered by R2 and S5.2/S5.3: create tested
  report-bound/current read models and an explicit ordered page entry with cohesive
  section functions while preserving Streamlit behavior and the approved design.

**Disposition:** `ALREADY COVERED`; no new work package or substep is added. The
approved plan continues to treat file length as a review signal, not a line-count
reduction target.

## Approved implementation queue

Gate G0 was approved by the user on 2026-08-31 after review of the bounded S1-S5
program, approval/stop gates, and per-substep contract. S1.1 through S1.5 were
implemented and accepted by the user on 2026-09-01. The pre-S1.6 agent-research
workflow correction passed its two-machine user retest on 2026-09-01. S1.6 was
implemented and accepted after user-visible dashboard review on 2026-09-02. Gate G1
passed on 2026-09-02 after the full deterministic suite, three-platform CI, a clean
disposable-data daily workflow, and that dashboard review all succeeded. S2.1 is now
implemented, accepted, and checkpointed as `31958b5`. A separately approved dashboard
organization change was accepted after user-visible review on 2026-09-02. S2.2 is
now the next planned substep but remains inactive until explicitly started. Later
substeps enter one at a time after the preceding acceptance gate is recorded; approval
of the program is not blanket approval to implement all 27 substeps without review.

## Implementation evidence

### S1.1 — daily workflow validation correctness

- **Status:** implemented and accepted on 2026-09-01.
- **Test-first evidence:** focused tests failed against the prior implementation for
  the missing base-analysis seam, duplicate workflow validation, scoring-only legacy
  metadata, malformed optional mappings, and malformed nested values.
- **Implementation:** the private base-analysis command now reports whether its exact
  stored run completed; standalone `run` adds one post-run validation, while
  `daily-report` uses the base outcome in step 6 and validates once in step 8. The
  shadow step therefore skips only when that production ranking did not complete.
  Optional freshness and scoring-quality mappings are parsed independently, malformed
  legacy values are safely ignored or labelled unavailable, and current-run output
  order is preserved.
- **Verification:** 26 focused CLI tests passed; the full deterministic suite passed
  150 tests with two expected platform-specific skips. Ruff and `git diff --check`
  passed.
- **Scope:** no public commands/options, step order, provider access, scoring,
  formulas, schema, persistence format, research behavior, or dashboard behavior
  changed.

### S1.2 — bounded retention and complete local SEC validation

- **Status:** implemented and accepted on 2026-09-01.
- **Test-first evidence:** the prior implementation accepted zero, negative, and
  unbounded retention days; had no complete local SEC/adaptive-refresh validator;
  allowed cleanup planning to start without a command-level refusal; and exposed raw
  file/TOML exceptions from SEC policy files.
- **Implementation:** retention day settings must be integers from 1 through 36,500,
  and `storage-clean` refuses invalid configuration before opening storage or planning
  deletion. Local `setup-check` and `config-check` now validate the SEC identity URL,
  request limits, retry/backoff, cache and stale windows, filing history/forms,
  Company Facts history/core concepts, all three adaptive-refresh settings, stale
  fallback flag, and policy paths without network access. Missing or malformed SEC
  policy files produce concise `SecConfigurationError` diagnostics.
- **Verification:** 84 focused configuration/SEC/CLI tests passed; the active
  installation's local `config-check` passed; the full deterministic suite passed
  184 tests with two expected platform-specific skips. Ruff and `git diff --check`
  passed.
- **Scope:** no cleanup expansion, deletion execution, provider request, SEC cache
  behavior, formula, schema, scoring, ranking, or dashboard behavior changed.

### S1.3 — all-applied-or-restored local personalization

- **Status:** implemented and accepted on 2026-09-01; milestone cross-platform CI
  remains pending.
- **Test-first evidence:** controlled failures against the prior implementation
  confirmed that the universe and preferences files were independent writes and
  that a second-file failure could leave a mixed active configuration.
- **Implementation:** `configure` now stages and locally validates every proposed
  file before changing either active file. Update and reset use one bounded
  best-effort transaction: prior files are moved to unique backups, any later
  backup/replacement/reload failure restores the prior pair where possible, and an
  incomplete rollback produces an explicit `RECOVERY REQUIRED` diagnostic with the
  preserved recovery locations. First-time failures restore the prior absent state,
  and command-level failures return a concise error instead of a traceback.
- **Verification:** 59 focused customization/CLI tests passed, including controlled
  failures at both staging, backup, and replacement positions plus reset, reload,
  first-save, and rollback-failure cases. The full deterministic Windows suite
  passed 198 tests with two expected platform-specific skips. Ruff, local
  `config-check`, and `git diff --check` passed. The same filesystem-neutral tests
  will run on macOS and Linux in the S1 milestone CI push.
- **Scope:** no profile formulas, universe membership rules, scoring, provider
  access, schema, runtime data, or dashboard behavior changed. Personal files,
  backups, and recovery artifacts remain ignored local state.

### S1.4 — SEC cache, identity, refresh-time, and count-label hardening

- **Status:** implemented and accepted on 2026-09-01; milestone cross-platform CI
  remains pending.
- **Test-first evidence:** controlled cache records proved that unsupported or
  missing schema versions and materially future timestamps were accepted, while a
  naive timestamp raised during freshness comparison. A mismatched root submissions
  CIK was accepted, future refresh state suppressed refresh, and the filing command
  described document checks as requests.
- **Implementation:** SEC cache reads now require the supported schema, matching
  source URL, parseable aware timestamp, and a timestamp no more than five minutes
  ahead of the local clock; invalid metadata is a silent cache miss. Root submissions
  must identify the requested CIK. Adaptive-refresh state, stored latest-filing time,
  and current latest-filing time must be aware and cannot exceed the same explicit
  five-minute clock-skew allowance; invalid values force a raw-cache-bypassing
  refresh. Submission snapshots and command output now call the unchanged count
  `documents_checked`, and both SEC sync commands use one exact document/cache/network
  label.
- **Verification:** 93 focused SEC/cache/submissions/refresh/CLI tests passed. The
  clean-environment full deterministic Windows suite passed 213 tests with two
  expected platform-specific skips. Ruff and `git diff --check` passed; milestone
  CI will execute the same tests on Windows, macOS, and Linux.
- **Scope:** no SEC request rate, retry policy, refresh interval, document count,
  provider source, formula, schema, scoring, ranking, runtime data, or dashboard
  behavior changed.

### S1.5 — executed dashboard baseline and bounded historical disclosure

- **Status:** implemented and accepted on 2026-09-01; milestone cross-platform CI
  remains pending.
- **Characterization evidence:** `AppTest.from_file` now executes the dashboard
  against disposable project roots for no-run, current completed-run, legacy
  missing-cutoff, and empty-candidate states. The fixtures create only temporary
  configuration and database state, make no network requests, and do not touch the
  installation's runtime data. Equivalent source assertions were updated only after
  this executed baseline existed.
- **Implementation:** one shared pure disclosure policy now requires a recorded,
  timezone-aware run completion cutoff before SEC filings can appear in either the
  Markdown report or dashboard. Missing or naive cutoffs withhold the filing list and
  state the historical limitation; aware cutoffs preserve timestamp and date-only
  availability rules. One shared candidate-policy formatter now uses the displayed
  run's stored score, coverage, price, and 20-day dollar-volume thresholds. Empty
  candidate lists state all four rules, summarize stored exclusion counts, and never
  substitute the installation's current thresholds for an incomplete legacy run.
- **Verification:** 25 focused presentation/report/dashboard tests passed, including
  before/at/after cutoff, date-only availability, missing and naive cutoff, no-filing,
  legacy-policy, and score/coverage/price/liquidity/mixed candidate failures. A live
  local browser check rendered the current dashboard with all four stored entry rules
  and no browser errors. The full deterministic Windows suite passed 228 tests with
  two expected platform-specific skips. Ruff and `git diff --check` passed.
- **Scope:** no provider requests, SEC synchronization, filing storage, schema,
  formula, scoring result, candidate eligibility decision, universe membership,
  historical row, or runtime data changed.

### Pre-S1.6 correction — agent research import finalization

- **Status:** implemented, verified, and accepted on 2026-09-01.
- **Finding:** a fresh Codex project generated and previewed a separate research
  Markdown file without populating the dashboard. Codex automatically discovers the
  concise repository `AGENTS.md`, but the complete two-part report workflow lived in
  `CODEX.md` without an instruction requiring Codex to read it. The dashboard reads
  research imported for the exact analysis run; an arbitrary Markdown file is not an
  import artifact.
- **Implementation:** `AGENTS.md` now routes daily and morning requests to the Codex
  playbook and defines import as a completion requirement. `CODEX.md` uses the single
  `daily-report` orchestrator, requires the generated JSON template and preserved
  `run_id`, prohibits treating a previewed Markdown draft as completion, requires the
  import success message, validates the same run, and opens the dashboard only after
  import. The agent-neutral workflow carries the same JSON-only warning. Reasoning
  labels now match Light, Medium, High, and Extra High. `validate-latest`
  reports `Qualitative research=imported` or `not imported` for its exact latest run
  without making optional research a deterministic-run failure.
- **Verification:** 35 focused CLI and public-repository contract tests passed. The
  active installation displayed the new exact-run research status without modifying
  its runtime data. The full deterministic Windows suite passed 231 tests with two
  expected platform-specific skips. Ruff and `git diff --check` passed. The user then
  ran the full agent-assisted report on both the primary PC and a fresh laptop
  installation; both dashboards populated the imported qualitative-research section.
- **Scope:** no research schema, import validation, dashboard query, scoring, formula,
  provider access, universe membership, database schema, historical row, or runtime
  data changed.

### S1.6 — dashboard report and current-diagnostics provenance

- **Status:** implemented on 2026-09-01 and accepted after user-visible dashboard
  review on 2026-09-02; Gate G1 milestone checks remain pending.
- **Test-first evidence:** disposable dashboard fixtures reproduced three unsafe
  cases: an active-universe ticker appearing in an older report's SEC snapshot table,
  a historical-as-of snapshot built only after report completion replacing evidence
  that existed at the cutoff, and a newer provider comparison linked to another
  analysis being presented beneath the displayed report. A missing linked comparison
  also disappeared without explaining that current evidence had been withheld.
- **Implementation:** Step 2.4A now selects only stored result membership and requires
  both the snapshot's data cutoff and actual build time to be at or before the
  displayed run's aware completion time. Missing completion or snapshot evidence is
  stated and never replaced with current rows. Step 2.4B selects report evidence only
  through the persisted `analysis_run_id`; its stored universe, scope, policy, and
  completion time are displayed. Provider health and promotion-date progress remain
  useful installation-current diagnostics, but now state their checked time, active
  universe, scoring configuration, policy, link status, and report mismatches. A
  narrow optional storage filter supports the persisted analysis-run link without a
  schema change or cache.
- **Verification:** 39 focused dashboard/storage/SEC-financial/provider-comparison
  tests passed, including exact membership, both financial cutoffs, linked versus
  newer-unrelated shadow runs, active/stored configuration and policy mismatches,
  missing-cutoff disclosure, and missing-linked-evidence non-substitution. The full
  deterministic Windows suite passed 234 tests with two expected platform-specific
  skips. Ruff and `git diff --check` passed. A live local browser review showed the
  current installation's exact report-bound SEC and provider-comparison identities,
  active diagnostics timestamps/configuration/policy, and matching link status with
  no browser or server errors; the user accepted the result.
- **Scope:** no live provider request, stored row, schema, formula, scoring, ranking,
  candidate eligibility, universe membership, evidence qualification, command, or
  dashboard visual theme changed. The later typed read-model and rendering
  extractions remain S5.2 and S5.3.

### Gate G1 — Work package 1 correctness review

- **Status:** passed on 2026-09-02; S2.1 may begin only after explicit user approval.
- **Deterministic tests:** the S1.6 milestone verification completed the full Windows
  suite with 234 passing tests and two expected platform-specific skips. Ruff and
  `git diff --check` also passed.
- **Cross-platform CI:** GitHub Actions run `33590150597` for commit `d39a0e4` passed
  the Python 3.12 jobs on `ubuntu-latest`, `windows-latest`, and `macos-latest`.
- **Disposable daily workflow:** the active source was run from an explicit temporary
  installation root containing disposable copies of configuration, the database,
  and provider cache. All eight deterministic steps completed without touching the
  primary runtime. Run `b320baa5-6fa4-490c-b204-df6c6dc64c64` completed for all 50
  stocks with 50 usable prices, 17 eligible candidates, zero ranking warnings, and
  exact final validation. SEC identity and filing health were healthy, financial
  snapshots were usable for 50/50 companies, and linked provider-shadow evidence was
  complete and qualified for the full 50-stock universe.
- **Dashboard review:** the user-visible S1.6 review verified the report-bound versus
  installation-current distinctions and was accepted before this gate run.
- **Outcome:** Work package 1's workflow and provenance changes are accepted as the
  behavioral baseline. No formula or schema contract was changed during G1.

### S2.1 — exact version-10 schema ownership and future-version refusal

- **Status:** implemented and accepted on 2026-09-02; checkpoint `31958b5` was pushed
  before any S2.2 work.
- **Test-first evidence:** the frozen fresh-schema inventory and repeated-initializer
  tests passed against the prior implementation, while a database marked version 11
  was silently rewritten to version 10 and failed the new non-mutation assertion.
- **Implementation:** `storage_schema.py` now owns the exact version-10 DDL, existing
  compatibility-repair order and backfills, stored-version inspection, version
  publication, and the SEC observation-record encoding shared by live writes and
  legacy seeding. `Storage.initialize` remains the caller-facing transaction and
  connection boundary and delegates through that owner. The existing schema and
  provider-link constants remain import-compatible from `storage.py`.
- **Safety behavior:** a stored version above 10 raises a clear error before current
  DDL, repairs, backfills, or version publication run. The deterministic fixture
  proves the future-only table, row, and version marker remain logically unchanged.
- **Verification:** the normalized fresh-schema object list and SQL fingerprint are
  identical to the frozen version-10 baseline; repeated initialization produces the
  same schema and logical dump. All 44 focused storage, pipeline, reporting,
  reproducibility, provider-comparison, and SEC-financial tests passed. The full
  suite passed 237 tests with two expected platform-specific skips. Full Ruff lint,
  changed-file formatting, bytecode compilation, and `git diff --check` passed.
- **Scope:** no new schema version, ordered historical migration registry, stored
  runtime row, formula, scoring rule, provider behavior, command, report, or dashboard
  behavior changed. Historical versions 1 through 9 remain the separate S2.2 scope;
  no active runtime database was used for migration testing.

### Approved inter-substep dashboard organization

- **Status:** separately approved, implemented, and accepted after user-visible review
  on 2026-09-02; authorized as one bundled checkpoint before S2.2.
- **Test-first evidence:** a page-order contract failed because no outer Advanced
  section existed and personalization still appeared near the top of the report. A
  separate market-context ordering test initially failed because no deterministic
  leadership-order helper existed.
- **Implementation:** stock-facing market, candidate, comparison, research, filing,
  and ranking-change content remains directly visible. The independent `Personalize
  ranking and universe` expander now sits near the bottom immediately above one
  collapsed `Advanced` expander. Run details, data-quality warnings and peer samples,
  per-stock freshness, provider diagnostics, isolated Step 2.4A/2.4B evidence, and
  stored profile/scoring configuration retain their existing inner expanders inside
  Advanced. The top warning now tells users to open Advanced for details. Market
  Overview uses its already stored three-month return as the primary display order,
  one-month return and ticker as deterministic tie-breakers, and places unavailable
  values last without changing the stored mapping.
- **Verification:** 29 dashboard visual, executed Streamlit, presentation, and summary
  tests passed across current, legacy, no-run, and missing-evidence fixtures. The new
  contracts verify the outer ordering, every technical section's placement, market
  leadership order, missing-value handling, and input non-mutation. The full suite
  passed 239 tests with two expected platform-specific skips.
- **Scope:** no calculation, stored data, query, provider access, ranking, candidate,
  research, diagnostic content, or visual theme changed; this is page organization
  only and remains separate from the S2 persistence work.
