// Брендинг печатных форм (лого/печать/подпись) — вынесен из api.ts отдельным файлом,
// как contracts-api.ts: api.ts периодически держит параллельная полоса (hotspot), общий
// файл конфликтует. Ходят через тот же /api-прокси, что и остальные клиентские вызовы.

/** Изображения брендинга для печатных форм счёта/договора. Все поля nullable — честное
 *  отсутствие: нет изображения → на форме ничего не рисуем (см. CompanyBranding на бэке). */
export interface Branding {
  logo_data_url: string | null;
  stamp_data_url: string | null;
  signature_data_url: string | null;
}

/** Все три изображения брендинга (GET /branding). Ошибка/недоступность бэка → все null. */
export async function fetchBranding(): Promise<Branding> {
  try {
    const res = await fetch("/api/sales/branding", { cache: "no-store" });
    if (!res.ok) return { logo_data_url: null, stamp_data_url: null, signature_data_url: null };
    return (await res.json()) as Branding;
  } catch {
    return { logo_data_url: null, stamp_data_url: null, signature_data_url: null };
  }
}

/**
 * Частичное обновление брендинга (PUT /branding): передаём ТОЛЬКО меняемые ключи —
 * бэк обновляет лишь непустые, остальные не трогает (по одному изображению за раз).
 * `true` при res.ok.
 */
export async function updateBranding(
  patch: Partial<Pick<Branding, "logo_data_url" | "stamp_data_url" | "signature_data_url">>,
): Promise<boolean> {
  try {
    const res = await fetch("/api/sales/branding", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    });
    return res.ok;
  } catch {
    return false;
  }
}
