export type CatalogAdoptionCommand = {
  request_key: string;
  effective_from: string;
  evidence: string;
};

export type CatalogAdoption = CatalogAdoptionCommand & {
  catalog_adoption_id: number;
  organization_id: number;
  catalog_version: string;
  catalog_source: string;
  catalog_review_state: Record<string, unknown>;
  current_normative_verified: boolean;
  digest: string;
  actor: string;
};

export class CatalogAdoptionApiError extends Error {
  constructor(message: string, readonly known: boolean) { super(message); }
}

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const isoDate = /^\d{4}-\d{2}-\d{2}$/;
const digest = /^[0-9a-f]{64}$/i;

function validDate(value: unknown): value is string {
  if (typeof value !== "string" || !isoDate.test(value)) return false;
  const [year, month, day] = value.split("-").map(Number);
  const parsed = new Date(Date.UTC(year, month - 1, day));
  return parsed.getUTCFullYear() === year && parsed.getUTCMonth() === month - 1 && parsed.getUTCDate() === day;
}

function message(value: unknown, fallback: string) {
  return typeof value === "object" && value !== null && typeof (value as { detail?: unknown }).detail === "string"
    ? (value as { detail: string }).detail : fallback;
}

function text(value: unknown): value is string { return typeof value === "string" && value.trim().length > 0; }

export function parseCatalogAdoption(value: unknown, organizationId: number,
                                     expected?: CatalogAdoptionCommand): CatalogAdoption {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new CatalogAdoptionApiError("Получен некорректный ответ о подтверждении каталога.", false);
  const row = value as Record<string, unknown>;
  if (!Number.isInteger(row.catalog_adoption_id) || (row.catalog_adoption_id as number) <= 0
    || row.organization_id !== organizationId || !text(row.request_key) || !uuid.test(row.request_key)
    || !validDate(row.effective_from) || !text(row.evidence)
    || !text(row.catalog_version) || !text(row.catalog_source) || !row.catalog_review_state
    || typeof row.catalog_review_state !== "object" || Array.isArray(row.catalog_review_state)
    || typeof row.current_normative_verified !== "boolean" || !text(row.digest) || !digest.test(row.digest)
    || !text(row.actor)) throw new CatalogAdoptionApiError("Ответ о подтверждении каталога не прошёл проверку области или состава.", false);
  if (expected && (row.request_key !== expected.request_key || row.effective_from !== expected.effective_from
    || row.evidence !== expected.evidence)) throw new CatalogAdoptionApiError("Сервер вернул подтверждение не для отправленного запроса.", false);
  return row as CatalogAdoption;
}

async function body(response: Response): Promise<unknown> {
  try { return await response.json(); } catch { return null; }
}

export async function listCatalogAdoptions(organizationId: number, fetcher: typeof fetch = fetch) {
  let response: Response;
  try {
    response = await fetcher(`/api/accounting/organizations/${organizationId}/catalog-adoptions`, { cache: "no-store" });
  } catch {
    throw new CatalogAdoptionApiError("Не удалось загрузить подтверждения нормативного каталога.", false);
  }
  const result = await body(response);
  if (!response.ok) throw new CatalogAdoptionApiError(message(result, "Не удалось загрузить подтверждения нормативного каталога."), true);
  if (!Array.isArray(result)) throw new CatalogAdoptionApiError("Список подтверждений каталога имеет неверный формат.", false);
  return result.map((row) => parseCatalogAdoption(row, organizationId));
}

export async function createCatalogAdoption(organizationId: number, command: CatalogAdoptionCommand,
                                            fetcher: typeof fetch = fetch) {
  if (!uuid.test(command.request_key) || !validDate(command.effective_from) || !command.evidence.trim()) {
    throw new CatalogAdoptionApiError("Нужны UUID запроса, дата действия и evidence подтверждения.", true);
  }
  let response: Response;
  try {
    response = await fetcher(`/api/accounting/organizations/${organizationId}/catalog-adoptions`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(command), cache: "no-store",
    });
  } catch {
    throw new CatalogAdoptionApiError("Статус принятия неизвестен: повторите тот же запрос.", false);
  }
  const result = await body(response);
  if (!response.ok) {
    const known = response.status >= 400 && response.status < 500;
    throw new CatalogAdoptionApiError(
      known
        ? message(result, "Подтверждение каталога отклонено.")
        : "Статус принятия неизвестен: сервер не подтвердил сохранение. Повторите тот же запрос.",
      known,
    );
  }
  return parseCatalogAdoption(result, organizationId, command);
}

export function newCatalogAdoptionRequestKey(): string | null {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") return crypto.randomUUID();
  return null;
}
