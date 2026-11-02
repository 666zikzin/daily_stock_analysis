# Stock report cost controls

DSA runs after US trading sessions, normally Shanghai Tuesday–Saturday06:30. Holidays skip model generation rather than re-analyzing stale sessions. TradingAgents normally runs Saturday05:30, targeting07:00. If Friday is a regular US exchange holiday, its weekly run shifts to Shanghai Friday morning after Thursday's session. Calendar candidates run Friday/Saturday but only the due date executes paid analysis or sends a report. Four weekly reports and22 DSA reports are monthly budget approximations, not exact quotas.

GitHub scheduled delivery can be delayed. Manual workflow_dispatch remains available for extra analysis approved by the user; there is no automatic paid event rerun. Manual DSA force_run retains its existing meaning.

The companion Google script checks actual Gmail receipts, expects TA only on its weekly due date and compares fresh same-day pairs (including approved extra runs). No older TA is silently reused. A no-model public Google News RSS filter can send one daily candidate-event digest to the existing receiver. Candidates are not independently verified facts; obvious investment-opinion titles are excluded, seen titles are deduplicated, and feed failure generates an explicit notice. The event filter covers the current report company list, not every user holding or every material event. It never dispatches a workflow. User confirmation is required before any paid extra run.

The Aliyun watchdog's required workflows and Shanghai trigger days must be updated together with GitHub and Gmail monitoring. It checks execution status, not delivery. Keep the old configuration until the coordinated rollout is ready. Usual regular NYSE holidays are supported; unexpected exchange closures require a calendar update.

Rollback: restore prior workflows, runner and cloud monitoring code together; set Google REPORT_CADENCE=daily and EVENT_REMINDERS=off. No keys or model routing change in this update.
