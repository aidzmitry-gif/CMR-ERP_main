import { InvoiceError, type Allocation, type Availability, type InvoiceLine } from "./invoice-issuance-api";

export type ReservationPreview = { organization_id: number; deal_id: number; document_id: number; document_version: number; content_sha256: string; lines: InvoiceLine[]; availability: Availability };
export async function previewReservation(dealId: string, documentId: number, organizationId: number, version: number, digest: string): Promise<ReservationPreview> {
  const response = await fetch(`/api/sales/deals/${dealId}/documents/${documentId}/reservation-preview`, {
    method: "POST", cache: "no-store", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ organization_id: organizationId, expected_document_version: version, expected_content_sha256: digest }),
  });
  if (!response.ok) throw new InvoiceError(`Просмотр резерва недоступен (${response.status}). Проверьте юрлицо и состояние счёта.`);
  const v: unknown = await response.json();
  const decimal = (n: unknown) => typeof n === "string" && /^-?\d{1,12}(?:\.\d{1,2})?$/.test(n);
  if (!object(v) || v.deal_id !== Number(dealId) || v.document_id !== documentId || v.organization_id !== organizationId
    || v.document_version !== version || v.content_sha256 !== digest || !hash(digest) || !Array.isArray(v.lines) || !v.lines.length
    || !v.lines.every((line, i) => object(line) && line.line_no === i + 1 && typeof line.name === "string" && typeof line.sku_code === "string" && typeof line.unit === "string" && decimal(line.qty) && Number(line.qty) > 0)
    || !object(v.availability) || v.availability.organization_id !== organizationId || v.availability.source !== "wms_physical"
    || !Array.isArray(v.availability.rows) || !v.availability.rows.every(row => object(row) && typeof row.sku_code === "string"
      && typeof row.warehouse === "string" && row.warehouse.trim() && decimal(row.reserved)
      && (row.free === null || decimal(row.free)) && (row.physical === null || decimal(row.physical)))) {
    throw new InvoiceError("Просмотр не соответствует исходному счёту или данным склада.");
  }
  return v as ReservationPreview;
}

export type ReservationCommand = {
  organization_id: number; expected_document_version: number; expected_content_sha256: string;
  request_key: string; allocations: Allocation[]; evidence: string; journal_complete: true;
};
export type PendingReservation = { dealId: string; documentId: number; command: ReservationCommand; body: string };
const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);
const hash = (v: unknown) => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
const key = (deal: string, doc: number) => `erp-late-reservation-v1:${deal}:${doc}`;
function validate(p: PendingReservation) {
  if (!/^[1-9]\d*$/.test(p.dealId) || !Number.isSafeInteger(Number(p.dealId)) || !Number.isSafeInteger(p.documentId) || p.documentId < 1
    || !object(p.command) || !hash(p.command.expected_content_sha256) || p.body !== JSON.stringify(p.command)) {
    throw new InvoiceError("Сохранённый запрос резерва повреждён. Требуется сверка счёта.");
  }
}
export function saveReservation(p: PendingReservation) {
  validate(p);
  try { sessionStorage.setItem(key(p.dealId, p.documentId), JSON.stringify(p)); }
  catch { throw new InvoiceError("Не удалось сохранить запрос. Резерв не отправлен."); }
}
export function loadReservation(dealId: string, documentId: number): PendingReservation | null {
  const raw = sessionStorage.getItem(key(dealId, documentId));
  if (!raw) return null;
  try {
    const p = JSON.parse(raw) as PendingReservation;
    validate(p);
    if (p.dealId !== dealId || p.documentId !== documentId) throw new Error();
    return p;
  } catch { throw new InvoiceError("Сохранённый запрос резерва повреждён. Требуется сверка счёта."); }
}
export async function submitReservation(p: PendingReservation): Promise<void> {
  validate(p);
  // Persist before sending; every failure retains exactly the same command.
  saveReservation(p);
  try {
    const response = await fetch(`/api/sales/deals/${p.dealId}/documents/${p.documentId}/reservation`, {
      method: "POST", cache: "no-store", headers: { "Content-Type": "application/json" }, body: p.body,
    });
    if (!response.ok) throw new Error(`Сервер вернул ${response.status}.`);
    const result: unknown = await response.json();
    if (!object(result) || !hash(result.reservation_digest) || typeof result.replayed !== "boolean" || !object(result.document)) throw new Error();
    const doc = result.document;
    if (doc.id !== p.documentId || doc.version !== p.command.expected_document_version
      || doc.content_sha256 !== p.command.expected_content_sha256 || doc.kind !== "invoice"
      || doc.reserve_mode !== "on_order" || doc.reserve_status !== "reserved") throw new Error();
    const readback = await fetch(`/api/sales/deals/${p.dealId}/documents`, { cache: "no-store" });
    if (!readback.ok) throw new Error();
    const rows: unknown = await readback.json();
    if (!Array.isArray(rows) || !rows.some(row => object(row) && row.id === p.documentId
      && row.version === doc.version && row.content_sha256 === doc.content_sha256 && row.kind === "invoice"
      && row.reserve_mode === "on_order" && row.reserve_status === "reserved")) throw new Error();
    sessionStorage.removeItem(key(p.dealId, p.documentId));
  } catch {
    throw new InvoiceError("Резерв не подтверждён. Исходный запрос сохранён: повторите его для сверки результата.", undefined, true);
  }
}
