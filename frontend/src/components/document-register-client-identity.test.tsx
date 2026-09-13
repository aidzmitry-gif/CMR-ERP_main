import { render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { DealDocumentRegister } from "./deal-document-register";
import { fetchDocumentRegister, fetchRegisterOrganizations } from "@/lib/document-register-api";

afterEach(() => vi.unstubAllGlobals());
const identity = { status: "confirmed", counterparty_id: 42, snapshot: { id: 42, name: "Historical client", unp: "111111111", revision: 1, is_active: true, merged_into_id: null } };
const page = { organization_id: 7, deal_id: 501, client_identity: identity, coverage: { sales_documents: "available", settlements: "separate_chief_register", shipments: "unavailable", tn_ttn: "not_connected" }, shipment_documents: [], items: [], next_after_id: null };
const ok = (data: unknown) => ({ ok: true, status: 200, json: async () => data });

it("accepts and displays confirmed historical identity without breaking register A", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(ok(page)));
  render(<DealDocumentRegister dealId="501" org="7" />);
  expect(await screen.findByText(/Подтверждённый клиент ID 42/)).toHaveTextContent("Historical client · УНП 111111111");
  expect(screen.queryByText(/Общий реестр клиента пока недоступен/)).not.toBeInTheDocument();
});

it("rejects a snapshot belonging to a different exact client", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(ok({ ...page, client_identity: { ...identity, snapshot: { ...identity.snapshot, id: 43 } } })));
  await expect(fetchDocumentRegister("7", "501")).rejects.toThrow(/некорректный или чужой/);
});

it("preserves the primary Sales organization endpoint", async () => {
  const fetchMock = vi.fn().mockResolvedValue(ok([{ id: 7, name: "Book", unp: "111" }])); vi.stubGlobal("fetch", fetchMock);
  await fetchRegisterOrganizations();
  expect(fetchMock.mock.calls[0][0]).toBe("/api/sales/document-register/organizations");
});

it("preserves the neutral historical consumed label", async () => {
  const row = { id: 100, deal_id: 501, organization_id: 7, kind: "invoice", number: "TEST", version: 1, status: "paid", amount: "1200.01", currency: "BYN", created_at: null, issued_at: null, valid_until: null, reserve_status: "consumed", onec_ref: null, original_state: "legacy_unavailable", content_sha256: null, replacement_reason: null, supersedes_id: null, superseded_by_id: null, original_available: false, preview_available: false };
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(ok({ ...page, items: [row] })));
  render(<DealDocumentRegister dealId="501" org="7" />);
  expect(await screen.findByText(/Исторический статус резерва: требуется сверка/)).toBeInTheDocument();
  expect(screen.queryByText(/Резерв исполнен отгрузкой/)).not.toBeInTheDocument();
});
