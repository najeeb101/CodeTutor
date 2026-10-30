// Small helpers shared by the dashboard tables.

export function formatWhen(iso: string | null): string {
  if (iso === null) return "–";
  return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export function formatNumber(value: number | null): string {
  return value === null ? "–" : value.toFixed(2);
}
