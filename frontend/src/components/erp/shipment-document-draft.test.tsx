import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";

import { ShipmentDocumentDraft } from "./shipment-document-draft";

beforeEach(() => { vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
  status: "draft_required", document_kind: "ttn", document_label: "ТТН",
  prefilled: { operation_date: "2026-09-13", total_quantity: "1", items: [{ line_no: 1, sku_code: "A", quantity: "1" }] },
  required_fields: ["vehicle_registration"], blockers: ["Внутренний акт WMS не является ТН или ТТН."], statutory_certified: false, can_issue: false,
  shipment_document_policy: { status: "review_ready", policy_id: 7, effective_from: "2026-09-01", normative_verified: true, scenario: { kind: "ttn", exchange_mode: "electronic", form_version: "Synthetic", numbering_rule: "Synthetic", signing_rule: "Synthetic", exchange_rule: "Synthetic", evidence: "Synthetic evidence" } },
}), { status: 200, headers: { "Content-Type": "application/json" } }))); });

it("loads a source-bound non-certified TN/TTN draft and never offers issuance", async () => {
  const user = userEvent.setup();
  render(<ShipmentDocumentDraft org="7" sourceKey="12345678-1234-4234-8234-123456789012" />);
  await user.click(screen.getByRole("button", { name: "Подготовить ТН/ТТН" }));
  expect(await screen.findByText(/Черновик ТТН/)).toBeInTheDocument();
  expect(screen.getByText(/сценарий заполнен/)).toBeInTheDocument();
  expect(screen.getByText(/не является ТН\/ТТН/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /выпустить|подписать/i })).not.toBeInTheDocument();
  await waitFor(() => expect(fetch).toHaveBeenCalledWith(expect.stringContaining("kind=ttn"), expect.anything()));
});
