# Repository Guidance for AI Agents

Read `README.md`, `docs/DAILY_WORKFLOW.md`, and `docs/ROADMAP.md` before operating or
changing this project. Follow the roadmap sequence and acceptance gates. Preserve
unrelated user changes and inspect `git status` before editing.

Use `stockrank config-check` to inspect the effective per-computer profile and
universe. Personal files under `config/*.local.*` are private local state: preserve
them, never stage them, and do not assume another clone uses the same settings.

All deterministic financial calculations belong in tested Python code. AI-assisted
work is limited to current-source qualitative research and must keep facts,
calculations, expectations, interpretation, and speculation clearly separated.
Never substitute demo data for live data, conceal stale or missing values, connect
to a broker, place trades, or portray a ranking as certainty.

Run relevant tests and verify that `.env`, `runtime/`, databases, caches, reports,
logs, and secrets are not staged before any user-authorized commit.
