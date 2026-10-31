import { hash } from "@/lib/expense-control-api";
import type { ShippingContext, ShippingIntent } from "@/lib/office-shipping-api";

export const invoice = { organization_id: 7, document_id: 22, expected_version: 3, expected_content_sha256: "c".repeat(64) };
export const intent: ShippingIntent = { mode: "spot", customer: "ООО Учебный пример", cargo: "Учебный груз", weight_kg: "700.50", declared_value_byn: "4000.00", route_from: "Минск", route_to: "Гродно", address: "Учебная улица, 1", zone_code: "", carrier_code: "synthetic-carrier", carrier_name: "Учебный перевозчик", pickup_date: "2026-11-03", contact: "Учебный контакт", comment: "Перед забором проверить упаковку" };
export async function shippingFixture(options: { id?: number; prepared?: boolean; associated?: boolean; resolved?: boolean; stage?: string } = {}): Promise<ShippingContext> {
  const id = options.id ?? 15;
  const source = { document_id: id, number: `УЧ-ДОК-${id}`, company: "ООО Учебный пример", title: "Учебный груз", amount: "100.00", region: "Гродно", weight: "Не подтверждён", address: "Учебная улица, 1", deal_id: null };
  const sha = await hash(source);
  const context: ShippingContext = { source_snapshot: source, source_sha256: sha, assignment_revision: 1, document_stage: options.stage ?? "ready", principal: "synthetic-reviewer", is_current_reviewer: true, capabilities: { can_request: true, can_associate: true }, request: null, association: null, source_matches_request: true, logistics: { state: "not_prepared", intake_id: null, pending_reason: "", target: null, shipment: null } };
  if (options.prepared || options.associated || options.resolved) {
    const envelope = "11111111-1111-4111-8111-111111111111";
    const payload = { schema_version: 1 as const, source: { kind: "office" as const, key: `office:shipping-request:${envelope}`, revision: "1" as const }, source_refs: { document_id: id, document_number: source.number, log_ref: "" }, intent: { ...intent } };
    context.request = { envelope_id: envelope, request_key: "synthetic-prepare", actor: context.principal, created_at: "2026-11-01T00:00:00Z", source_snapshot: source, source_sha256: sha, payload_sha256: await hash(payload), payload };
    context.logistics = { state: "pending", intake_id: 42, pending_reason: "persisted_source_required", target: null, shipment: null };
  }
  if (options.associated || options.resolved) context.association = { association_id: "22222222-2222-4222-8222-222222222222", request_key: "synthetic-confirm", execution_id: "33333333-3333-4333-8333-333333333333", exact_invoice: invoice, intent_digest: await hash({ schema_version: 1, exact_invoice: invoice, intent }), assignment_revision: 1, current_review_matches: true };
  if (options.resolved) context.logistics = { state: "resolved", intake_id: 42, pending_reason: "", target: { kind: "shipment", id: 91, number: "УЧ-ЛОГ-91", status: "planned" }, shipment: { id: 91, number: "УЧ-ЛОГ-91", status: "planned", carrier_name: "Учебный перевозчик", tracking_status: "", tracking_no: "", eta: null } };
  return context;
}
export function documentFixture(id = 15) { return { id, number: `УЧ-ДОК-${id}`, company: "ООО Учебный пример", title: "Учебный груз", stage: "ready", weight: "Не подтверждён", region: "Гродно", address: "Учебная улица, 1" }; }
