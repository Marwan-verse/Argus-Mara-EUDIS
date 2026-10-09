const finite = (value) => typeof value === "number" && Number.isFinite(value);
export const timestamp = (value) =>
  typeof value === "string" && Number.isFinite(Date.parse(value))
    ? Date.parse(value)
    : null;
export const count = (value) => new Intl.NumberFormat("en-GB").format(value);
export const dateFormat = new Intl.DateTimeFormat("en-GB", {
  timeZone: "UTC",
  day: "2-digit",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hourCycle: "h23",
});
export const utc = (value) =>
  timestamp(value) !== null
    ? dateFormat.format(new Date(value)).replace(",", "") + " UTC"
    : "Not yet received";
export const compactUtc = (value) =>
  timestamp(value) !== null
    ? new Date(value).toISOString().slice(11, 19) + " UTC"
    : "Not yet received";
export function ageText(receivedMs, now = Date.now()) {
  if (!finite(receivedMs)) return "—";
  const seconds = Math.max(0, Math.floor((now - receivedMs) / 1000));
  if (seconds < 60) return seconds + " s";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return minutes + " min";
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return hours + " h " + (minutes % 60) + " min";
  return Math.floor(hours / 24) + " d " + (hours % 24) + " h";
}
export const vesselName = (vessel) => vessel.name || "Name unavailable";
export function vesselType(type) {
  if (typeof type === "string" && type.trim()) return type;
  if (!finite(type) || type === 0) return "Type unavailable";
  if (type >= 70 && type <= 79) return "Cargo";
  if (type >= 80 && type <= 89) return "Tanker";
  if (type >= 60 && type <= 69) return "Passenger";
  if (type >= 40 && type <= 49) return "High-speed craft";
  return (
    {
      30: "Fishing",
      31: "Towing",
      32: "Towing",
      33: "Dredging / underwater operations",
      34: "Diving operations",
      35: "Military operations",
      36: "Sailing",
      37: "Pleasure craft",
      50: "Pilot",
      51: "Search and rescue",
      52: "Tug",
      53: "Port tender",
      54: "Anti-pollution",
      55: "Law enforcement",
      58: "Medical transport",
      59: "Noncombatant ship",
    }[type] || "AIS type " + type
  );
}
