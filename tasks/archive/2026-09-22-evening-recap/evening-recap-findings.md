# Findings

- `deliveries.render_snapshot` sends raw notes under `Sin estructurar` when `parsed_data` is absent.
- The daily editor appends one raw line per selected fact; each time entry is a distinct fact. Repeated entries for the same task are therefore repeated in the sent text.
- The daily send action queues immediately without showing the actual rendered message. `DailyEditRequest` can save notes, but the Discord body has no editor.
- Scheduled `morning` and `evening` are separate policies, renderers and local times. No code path converts a daily closing into a morning occurrence. Existing policy configuration needs separate state inspection to explain an observed morning delivery.
- Read-only production check by the parent task found no morning/evening policy or occurrence for this user on 21–22 September. The cited daily was manually sent at 21:54 Madrid time on 21 September; the durable sent receipt is unchanged.
- Existing unparsed dailys with canonical source snapshots can be grouped without rewriting stored data. Where snapshots are absent, only the old generated row syntax can be grouped confidently; lines without an explicit client remain General.
- Preview GET and send POST share the daily owner/admin authorization. Custom content requires the preview revision, and a sent daily rejects a new custom body.
