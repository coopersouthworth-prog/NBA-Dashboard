// Formatting helpers. Times show in the viewer's own time zone.

export function formatGameDay(isoDate) {
  if (!isoDate) return "Today";
  // Noon avoids the date shifting a day in time zones behind UTC.
  return new Date(`${isoDate}T12:00:00`).toLocaleDateString(undefined, {
    weekday: "long", month: "long", day: "numeric",
  });
}

export function formatTipoff(isoTime) {
  if (!isoTime) return "";
  const d = new Date(isoTime);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
}

export function formatClock(isoTime) {
  if (!isoTime) return "";
  return new Date(isoTime).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
}

export function timeAgo(isoTime) {
  if (!isoTime) return "";
  const minutes = Math.round((Date.now() - new Date(isoTime).getTime()) / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  return `${days}d ago`;
}

export const pct = (x, digits = 0) =>
  x === null || x === undefined ? "–" : `${(x * 100).toFixed(digits)}%`;
