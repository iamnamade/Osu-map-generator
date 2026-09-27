export function formatTimeMs(valueMs: number): string {
  const totalMilliseconds = Math.max(0, Math.round(valueMs));
  const totalSeconds = Math.floor(totalMilliseconds / 1000);
  const minutes = Math.floor(totalSeconds / 60)
    .toString()
    .padStart(2, "0");
  const seconds = (totalSeconds % 60).toString().padStart(2, "0");
  const milliseconds = (totalMilliseconds % 1000).toString().padStart(3, "0");
  return `${minutes}:${seconds}.${milliseconds}`;
}

export function formatClockTimeMs(valueMs: number): string {
  const totalSeconds = Math.max(0, Math.floor(valueMs / 1000));
  const minutes = Math.floor(totalSeconds / 60)
    .toString()
    .padStart(2, "0");
  const seconds = (totalSeconds % 60).toString().padStart(2, "0");
  return `${minutes}:${seconds}`;
}

export function formatSignedNumber(value: number, digits = 0): string {
  return `${value >= 0 ? "+" : ""}${value.toFixed(digits)}`;
}

export function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, value));
}

export function escapeHtml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}
