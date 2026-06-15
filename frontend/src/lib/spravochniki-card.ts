import type { CounterpartyAlias } from "@/lib/reference-data";

/** Group aliases by source name for display in the Golden Record section. */
export function groupAliasesBySource(
  aliases: CounterpartyAlias[],
): Record<string, CounterpartyAlias[]> {
  const result: Record<string, CounterpartyAlias[]> = {};
  for (const alias of aliases) {
    if (!result[alias.source]) result[alias.source] = [];
    result[alias.source].push(alias);
  }
  return result;
}

/** Format ISO timestamp to DD.MM.YYYY using UTC date parts to avoid TZ drift. */
export function formatAuditDate(isoTs: string): string {
  const d = new Date(isoTs);
  return [
    String(d.getUTCDate()).padStart(2, "0"),
    String(d.getUTCMonth() + 1).padStart(2, "0"),
    String(d.getUTCFullYear()),
  ].join(".");
}
