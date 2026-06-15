// Чистая логика для экрана версионных справочников SCD2 (курсы/НДС).
// Без React-зависимостей — тестируется отдельно.

export type VersionStatus = "current" | "planned" | "archived";

// start_date > today → ещё не началась; (end_date=null || end_date>today) → действует сейчас; иначе → закрыта.
// Порядок проверок важен: planned проверяем до null-check end_date.
export function versionStatus(
  row: { start_date: string; end_date: string | null },
  today: string, // YYYY-MM-DD
): VersionStatus {
  if (row.start_date > today) return "planned";
  if (row.end_date === null || row.end_date > today) return "current";
  return "archived";
}

/** YYYY-MM-DD → DD.MM.YYYY; null → '—'. */
export function formatDate(d: string | null): string {
  if (!d) return "—";
  const [y, m, day] = d.split("-");
  return `${day}.${m}.${y}`;
}
