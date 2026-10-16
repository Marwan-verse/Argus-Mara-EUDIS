# Reports and decision records

**Where:** **Report vessel** on a vessel card, **Report** in incident review,
and the decision-log shield button.

| Feature | What it does |
|---|---|
| Manual vessel report | Choose a category and write a reason. **Other** is supported; blank reasons cannot be submitted. |
| Reported vessels | Groups reports by vessel and provenance, showing author, UTC time, position and full reason. |
| Local or team report | Create a local report, or share with the current verified SOC session when permitted. |
| Draft with AI | Suggests a report from the available evidence pack; code validates it and can fall back to a template. |
| Check report | Checks facts against the evidence; configured AI can also flag unsupported meaning or omissions. |
| Save PDF | Saves an analyst report with source facts, labels and check status. PDF pages are images. |
| Signed decision log | Records analyst decisions; **Verify** checks signatures and the record chain for changes. |
| Other exports | Exercise HTML evidence, investigation JSON and seabed-plan GeoJSON are available in their respective panels. |

The analyst edits and reviews drafts before submission. AI does not set threat
levels or send reports. AI assistance needs its configured service. Failed
sharing retains the draft. Manual reports are bounded and session-local unless
exported; the signed decision log is a separate local record.

[Report assistant](../21-report-assistant.md) · [All categories](README.md)
