# Claude Code Project Guidance

@AGENTS.md

When the user asks to **run the daily report**, **run the morning report**, or uses
similar wording, read `CODEX.md` and `docs/DAILY_WORKFLOW.md`, then complete the
full two-part agent-assisted workflow: run the deterministic report once, research
the current top candidates, fill and import `runtime/reports/research_template.json`,
confirm `Qualitative research=imported` for the same run, and only then open the
dashboard. A separate Markdown research preview does not populate the dashboard.

If the user explicitly requests only the deterministic or base report, do not add
qualitative research. Never connect to a broker, place a trade, or present a ranking
as certainty.
