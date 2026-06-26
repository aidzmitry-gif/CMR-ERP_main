/**
 * Канон стадий воронки продаж — единый фронтовый источник (SALES-43).
 * Зеркало backend `modules/sales/stages.py` (Сделки 2.0, цена ДО встречи):
 * id / title / color и порядок = колонки канбана. Держать синхронным с бэком.
 *
 * NB: legacy-набор (new/qual/prop/appr/won) ещё живёт в board.ts (STAGE_PROBABILITY)
 * и mock-data.ts (STAGES) и залочен board.test.ts — их миграция на этот канон —
 * отдельный шаг (демо-фикстуры + тест). Здесь — источник для карточки сделки.
 */
export interface SalesStage {
  id: string;
  title: string;
  color: string;
}

/** Все 11 стадий (9 прогрессия + 2 терминала-отказа); порядок = бэк stages.py. */
export const SALES_STAGES: SalesStage[] = [
  { id: "new", title: "Новая заявка", color: "#3B82F6" },
  { id: "qual", title: "Квалифицирован", color: "#8B5CF6" },
  { id: "price_req", title: "Цена запрошена", color: "#F59E0B" },
  { id: "has_price", title: "Есть цена", color: "#EAB308" },
  { id: "meeting", title: "Встреча назначена", color: "#14B8A6" },
  { id: "invoice", title: "Счёт отправлен", color: "#0EA5E9" },
  { id: "protected", title: "Счёт защищён", color: "#6366F1" },
  { id: "contract", title: "Договор/предоплата", color: "#10B981" },
  { id: "won", title: "Успех", color: "#22C55E" },
  { id: "cond_lost", title: "Условный отказ", color: "#F97316" },
  { id: "lost", title: "Отказ", color: "#EF4444" },
];

/** Терминальные стадии (сделка закрыта; cond_lost — реанимируемый, НЕ терминал). */
export const TERMINAL_STAGES: ReadonlySet<string> = new Set(["won", "lost"]);

/** Линейная прогрессия для степпера: new → … → won (без терминалов-отказа). */
export const PROGRESSION_STAGES: SalesStage[] = SALES_STAGES.filter(
  (s) => s.id !== "cond_lost" && s.id !== "lost",
);

/** id → стадия (валидация / UI-заголовок). */
export const STAGE_BY_ID: Record<string, SalesStage> = Object.fromEntries(
  SALES_STAGES.map((s) => [s.id, s]),
);

/** Индекс стадии в линейной прогрессии (−1 для терминалов-отказа / неизвестной). */
export function progressionIndex(stageId: string): number {
  return PROGRESSION_STAGES.findIndex((s) => s.id === stageId);
}
