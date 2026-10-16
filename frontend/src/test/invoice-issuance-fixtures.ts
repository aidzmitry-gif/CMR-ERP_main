import { prepareCommand, type Availability, type InvoiceInput, type InvoicePreview, type InvoiceResult } from "@/lib/invoice-issuance-api";

export const input: InvoiceInput = { organization_id: 7, currency: "BYN", document_date: "2026-09-10", valid_until: "2026-09-15", pricing: [{ item_id: 11, unit_price_net: "100.00", vat_rate: "0.00" }], pricing_evidence: "Согласовано явно" };
export function preview(): InvoicePreview & { availability: Availability } {
  return { ...input, deal_id: 1, document_id: null, document_version: 1, basis_digest: "a".repeat(64), amount: "200.00",
    seller: { name: "Точный продавец", unp: "123", currency: "BYN", address: "Адрес", account: "СЧЁТ", bank: "БАНК", bik: "БИК", director: "Директор" },
    seller_profile: { profile_id: 4, revision: 1, digest: "b".repeat(64), effective_from: "2026-01-01" },
    buyer: { counterparty_id: 9, revision: 1, name: "Связанный покупатель", unp: "456", requisites: { address: "Адрес покупателя" }, requisites_digest: "c".repeat(64) },
    lines: [{ line_no: 1, item_id: 11, sku_code: "SKU", name: "Товар", unit: "шт", qty: "2.00", price: "100.00", vat_rate: "0.00", net: "200.00", tax: "0.00", total: "200.00", currency: "BYN" }],
    availability: { organization_id: 7, source: "wms_physical", rows: [{ sku_code: "SKU", warehouse: "W", physical: "3.00", reserved: "1.00", free: "2.00" }], basis_by_warehouse: { W: { version: "d".repeat(64), cutoff: 12 } } } };
}
export const result: InvoiceResult = { document: { id: 22, kind: "invoice", number: "ERP-INV-22", status: "issued", onec_ref: null, amount: 200, valid_until: "2026-09-15", reserve_status: "reserved", original_state: "issued", version: 1, content_sha256: "e".repeat(64) }, status: "issued", organization_id: 7, document_version: 1, content_sha256: "e".repeat(64), reservation_digest: "f".repeat(64), replayed: false };
export const response = (value: unknown, status = 200) => ({ ok: status < 400, status, json: async () => value });
export const command = () => prepareCommand("1", undefined, input, preview(), [{ line_no: 1, warehouse: "W", qty: "2.00" }], "Проверен журнал");
