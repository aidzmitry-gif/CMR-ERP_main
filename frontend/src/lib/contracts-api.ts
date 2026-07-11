// Слайс 7 (варианты договора с доски): хелперы шаблонов договора (SALES-53) вынесены
// из api.ts отдельным файлом — api.ts периодически держит параллельная полоса, и общий
// файл конфликтует. Ходят через тот же /api-прокси, что и остальные клиентские вызовы
// (см. api.ts) — прокси сам пробрасывает роль из cookie и статус/тело ответа как есть.
import type { DealDoc } from "./api";

/** Активный шаблон договора (SALES-53) — выбор в мини-секции «Договор» drawer'а сделки. */
export interface ContractTemplate {
  id: number;
  code: string;
  name: string;
}

/** Активные шаблоны договора (GET /contract-templates). Ошибка/недоступность бэка → []. */
export async function fetchContractTemplates(): Promise<ContractTemplate[]> {
  try {
    const res = await fetch("/api/sales/contract-templates", { cache: "no-store" });
    if (!res.ok) return [];
    return (await res.json()) as ContractTemplate[];
  } catch {
    return [];
  }
}

/** Итог подготовки договора по шаблону: сообщение для тоста (симметрично DocIssueResult
 *  из api.ts) + сам документ — сразу доступен без похода в fetchDocuments, если понадобится. */
export interface PrepareContractResult {
  ok: boolean;
  message: string;
  doc?: DealDoc;
}

/**
 * Подготовить договор по шаблону (SALES-53): POST /deals/{id}/contract.
 * 409 — по сделке уже есть активный (не отклонённый) договор; читаем `detail` с бэка
 * и показываем как есть (тот же паттерн чтения detail, что deleteStage в api.ts).
 */
export async function prepareContract(
  dealId: string,
  templateCode: string,
): Promise<PrepareContractResult> {
  try {
    const res = await fetch(`/api/sales/deals/${encodeURIComponent(dealId)}/contract`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ template_code: templateCode, requested_by: "Менеджер" }),
    });
    if (!res.ok) {
      const body = (await res.json().catch(() => ({}))) as { detail?: string };
      return { ok: false, message: body.detail ?? "⚠️ Не удалось подготовить договор" };
    }
    const doc = (await res.json()) as DealDoc;
    return { ok: true, message: `✅ Договор ${doc.number} отправлен на согласование`, doc };
  } catch {
    return { ok: false, message: "⚠️ Не удалось подготовить договор" };
  }
}

/** Итог отправки пакета клиенту (симметрично {@link PrepareContractResult}). */
export interface SendPackageResult {
  ok: boolean;
  message: string;
}

/**
 * Отправить клиенту пакет «счёт + договор» одной записью (слайс 8, SALES-53 C.4):
 * POST /deals/{id}/send-package. Требует последний ПРОВЕДЁННЫЙ/оплаченный счёт И
 * ПРОВЕДЁННЫЙ (согласованный) договор — иначе 409; читаем `detail` с бэка как есть
 * (тот же паттерн, что {@link prepareContract}).
 */
export async function sendPackage(dealId: string): Promise<SendPackageResult> {
  try {
    const res = await fetch(`/api/sales/deals/${encodeURIComponent(dealId)}/send-package`, {
      method: "POST",
    });
    if (!res.ok) {
      const body = (await res.json().catch(() => ({}))) as { detail?: string };
      return { ok: false, message: body.detail ?? "⚠️ Не удалось отправить пакет" };
    }
    return { ok: true, message: "✅ Пакет отправлен: счёт + договор" };
  } catch {
    return { ok: false, message: "⚠️ Не удалось отправить пакет" };
  }
}
