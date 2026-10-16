import type { FunnelStage } from "@/lib/types";

/** Универсальный клиент воронки ERP-модулей: ходит на бэкенд через прокси `/api`. */

/** Ошибка чтения не является подтверждённой пустой доской. */
export async function fetchFunnelBoard(boardPath: string): Promise<FunnelStage[]> {
  const res = await fetch(`/api${boardPath}`, { cache: "no-store" });
  if (!res.ok) throw new Error("Не удалось загрузить доску");
  const data = (await res.json()) as { stages?: FunnelStage[] } | null;
  if (!Array.isArray(data?.stages)) throw new Error("Некорректный ответ доски");
  return data.stages;
}

/** Создать карточку (`POST /api{createPath}`). Возвращает true при успехе. */
export async function createFunnelCard(
  createPath: string,
  payload: Record<string, unknown>,
): Promise<boolean> {
  try {
    const res = await fetch(`/api${createPath}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    return res.ok;
  } catch {
    return false;
  }
}

/** Сменить стадию карточки (`PATCH /api{patchPath}/{id}` с телом `{stage}`). */
export async function moveFunnelCard(
  patchPath: string,
  id: number,
  stage: string,
): Promise<boolean> {
  try {
    const res = await fetch(`/api${patchPath}/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ stage }),
    });
    return res.ok;
  } catch {
    return false;
  }
}
