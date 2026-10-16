export const permissionDetails = {
  "map.view": ["View map", "Map, AIS, layers, weather, measurements and local notes."],
  chat: ["Team chat", "Join permitted rooms and send encrypted chat after peer verification."],
  ping: ["Map pings", "Share temporary map annotations in a verified room."],
  "contact.share": ["Contacts & reports", "Share selected contacts and submit analyst vessel reports."],
  "evidence.share": ["Evidence & satellite", "Use evidence tools, SAR plans and configured satellite analysis."],
  "alert.review": ["Review alerts", "Review simulated incident findings and their explanations."],
  "response.review": ["Review responses", "Review and approve simulated response options. No operational tasking."],
};
export const groupDescriptions = {
  observer: "Read-only map access. No rooms, messaging or incident review.",
  user: "Operator: map, encrypted team chat, pings, contacts and vessel reports.",
  analyst: "Operator tools plus evidence, satellite tools and incident review.",
  intelligence: "All seven tools, including simulated response review.",
  "response-coordinator": "Operator tools plus incident and simulated response review; no evidence tools.",
};
