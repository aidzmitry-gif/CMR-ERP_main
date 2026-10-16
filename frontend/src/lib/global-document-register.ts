import { registerId } from "./document-register-api";

export type RegistryRow = { id: number; organization_id: number; source: "1c" | "erp"; kind: string; number: string; date: string | null; amount: string | null; currency: string | null; status: string; revision: number; client: { id: number; name: string } | null; deal_id: number | null; original_available: boolean };
export type RegistryPage = { organization_id: number; source: "1c" | "erp"; page: number; limit: number; total: number; pages: number; items: RegistryRow[]; kinds: string[] };
export type SourcePreview = { id: number; organization_id: number; source: "1c"; number: string | null; kind: string; date: string | null; amount: string | null; currency: string | null; status: "SOURCE_ONLY"; revision: number; client: RegistryRow["client"]; explanation: string; source_sha256: string; source_guid: string; native_posted: false; original_available: false; holds: string[]; line_page: number; line_pages: number; line_total: number; lines: { name: string; fields: Record<string, string> }[] };
export const DOCUMENT_KINDS: Record<string, string> = { invoice: "Счёт", contract: "Договор", order: "Заказ", Document_ЗаказКлиента: "Заказ клиента", Document_СчетНаОплатуКлиенту: "Счёт на оплату клиенту", Document_РеализацияТоваровУслуг: "Реализация товаров и услуг", Document_ТранспортнаяНакладная: "Транспортная накладная", Document_ПриобретениеТоваровУслуг: "Приобретение товаров и услуг", Document_СчетФактураВыданный: "Счёт-фактура выданный", Document_СчетФактураПолученный: "Счёт-фактура полученный" };
export const kindTitle = (kind: string) => DOCUMENT_KINDS[kind] ?? kind.replace(/^Document_/, "").replace(/([а-яё])([А-ЯЁ])/g, "$1 $2");
function object(value: unknown): value is Record<string, unknown> { return typeof value === "object" && value !== null && !Array.isArray(value); }
const id = (value: unknown): value is number => Number.isSafeInteger(value) && Number(value) > 0;
const nullableString = (value: unknown) => value === null || typeof value === "string";
function invalid(): never { throw new Error("ERP вернула некорректные данные реестра."); }
async function read(path: string, signal: AbortSignal) {
  const response = await fetch(path, { cache: "no-store", signal });
  if (!response.ok) {
    if (response.status === 401) throw new Error("Сессия завершилась. Войдите в ERP снова.");
    if (response.status === 403) throw new Error("Нет доступа к документам выбранной организации. Импорт без связей со сделками недоступен при личной видимости.");
    if (response.status === 404) throw new Error("Документ не найден в выбранной организации.");
    if (response.status === 409) throw new Error("Требуется сверка связи организации или целостности исходного документа.");
    throw new Error("Не удалось загрузить документы. Обновите список.");
  }
  return response.json() as Promise<unknown>;
}
function party(value: unknown) { return value === null || (object(value) && id(value.id) && typeof value.name === "string"); }
function row(value: unknown, org: string, source: string): value is RegistryRow {
  return object(value) && id(value.id) && value.organization_id === Number(org) && value.source === source && typeof value.kind === "string"
    && typeof value.number === "string" && nullableString(value.date) && nullableString(value.amount) && nullableString(value.currency)
    && typeof value.status === "string" && id(value.revision) && party(value.client) && (value.deal_id === null || id(value.deal_id)) && typeof value.original_available === "boolean";
}
export async function loadRegistry(org: string, source: "1c" | "erp", page: number, filters: { q: string; kind: string; date_from: string; date_to: string; limit: number }, signal: AbortSignal): Promise<RegistryPage> {
  if (!registerId(org) || !id(page)) invalid();
  const params = new URLSearchParams({ source, page: String(page), limit: String(filters.limit), q: filters.q, kind: filters.kind, date_from: filters.date_from, date_to: filters.date_to });
  const value = await read(`/api/sales/organizations/${org}/document-registry?${params}`, signal);
  if (!object(value) || value.organization_id !== Number(org) || value.source !== source || value.page !== page || value.limit !== filters.limit
    || !Number.isSafeInteger(value.total) || Number(value.total) < 0 || !id(value.pages) || !Array.isArray(value.items) || !value.items.every(item => row(item, org, source))
    || value.items.length > filters.limit || !Array.isArray(value.kinds) || !value.kinds.every(kind => typeof kind === "string")) invalid();
  return value as RegistryPage;
}
export async function loadSourcePreview(org: string, docId: number, linePage: number, signal: AbortSignal): Promise<SourcePreview> {
  if (!registerId(org) || !id(docId) || !id(linePage)) invalid();
  const value = await read(`/api/sales/organizations/${org}/document-registry/source/${docId}?line_page=${linePage}`, signal);
  if (!object(value) || value.organization_id !== Number(org) || value.id !== docId || value.source !== "1c" || value.status !== "SOURCE_ONLY"
    || value.native_posted !== false || value.original_available !== false || !nullableString(value.number) || typeof value.kind !== "string"
    || !nullableString(value.date) || !nullableString(value.amount) || !nullableString(value.currency) || !id(value.revision) || !party(value.client)
    || typeof value.explanation !== "string" || typeof value.source_sha256 !== "string" || !/^[0-9a-f]{64}$/.test(value.source_sha256)
    || typeof value.source_guid !== "string" || value.line_page !== linePage || !id(value.line_pages) || !Number.isSafeInteger(value.line_total) || Number(value.line_total) < 0
    || !Array.isArray(value.holds) || !value.holds.every(item => typeof item === "string")
    || !Array.isArray(value.lines) || !value.lines.every(item => object(item) && typeof item.name === "string" && object(item.fields) && Object.values(item.fields).every(field => typeof field === "string"))) invalid();
  return value as SourcePreview;
}
