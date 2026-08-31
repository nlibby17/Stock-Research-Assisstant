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
| R1 | CLI commands and orchestration | Qwen3-Coder-Next | Received; intake recorded below |
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

### CLI-01 — provider health and SEC sync orchestration

- **Status:** `INTAKE`
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
- **Decision:** pending.

### CLI-02 — provider-promotion evidence classification

- **Status:** `INTAKE`
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
- **Decision:** pending.

### CLI-03 — storage inspection and cleanup

- **Status:** `INTAKE`
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
- **Decision:** pending.

### CLI-04 — configuration validation formatting

- **Status:** `INTAKE`
- **External proposal:** create `stockrank/validation.py` to centralize conversion of
  settings validation warnings/errors into user-facing output.
- **Named scope:** `command_setup_check` and `command_config_check`.
- **External rationale:** allegedly duplicated validation and formatting could drift.
- **External rating:** later; difficulty 2/10; medium confidence.
- **Verification required:** compare the commands' actual purposes and output
  contracts, inspect existing validation ownership in `config.py`, and reject the
  extraction if it only moves a few lines without creating a coherent abstraction.
- **Decision:** pending.

### CLI-05 — daily and morning workflow definitions

- **Status:** `INTAKE`
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
- **Decision:** pending.

### R1 external preserve/do-not-do recommendations

These are also proposals awaiting verification:

- Keep `command_parser.py` and `daily_workflow.py` structurally unchanged.
- Keep `main()` and `build_parser()` as minimal CLI wiring.
- Keep small PyArrow, size-formatting, file-size, and interactive-prompt helpers in
  `cli.py`.
- Keep `command_research_import` in `cli.py`.
- Do not create one module per command.
- Do not change scoring logic, workflow order, or skip behavior during this work.

## Cross-review synthesis

Not started. This section will reconcile duplicated module proposals, dependency
direction, naming, implementation order, and the total amount of justified change
after R1–R5 have all been analyzed.

## Approved implementation queue

Intentionally empty. Production refactoring is prohibited until the review and
approval gates above are complete.

## Implementation evidence

No refactoring has been implemented.
