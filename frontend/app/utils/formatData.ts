const numberFormatter = new Intl.NumberFormat("en-US", {
  maximumFractionDigits: 1,
});

export function formatDataDate(value?: string | null): string {
  if (!value) return "Not available";

  const date = new Date(`${value.slice(0, 10)}T00:00:00Z`);
  if (Number.isNaN(date.getTime())) return "Not available";

  return new Intl.DateTimeFormat("en-US", {
    month: "long",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  }).format(date);
}

export function formatIsoDateInTimeZone(
  date: Date,
  timeZone: string,
): string {
  if (Number.isNaN(date.getTime())) return "";

  const parts = new Intl.DateTimeFormat("en-US", {
    day: "2-digit",
    month: "2-digit",
    timeZone,
    year: "numeric",
  }).formatToParts(date);
  const values = Object.fromEntries(
    parts.map(({ type, value }) => [type, value]),
  );
  const { day, month, year } = values;
  return year && month && day ? `${year}-${month}-${day}` : "";
}

export function formatDataNumber(value?: number | null): string {
  return typeof value === "number"
    ? numberFormatter.format(value)
    : "Not available";
}
