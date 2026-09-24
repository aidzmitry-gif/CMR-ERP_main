import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

vi.mock("@/lib/procurement-machine", () => ({
  organizations: vi.fn(), identity: vi.fn(), fetchProcurementSuppliers: vi.fn(),
}));
vi.mock("@/lib/procurement-scoped-claims", () => ({
  listClaims: vi.fn(), createClaim: vi.fn(), resolveClaim: vi.fn(),
  searchClaimOrders: vi.fn(), claimHistory: vi.fn(),
  previewUnassignedClaim: vi.fn(), bindUnassignedClaim: vi.fn(),
}));

import { ProcurementScopedClaims } from "@/components/erp/procurement-scoped-claims";
import * as machine from "@/lib/procurement-machine";
import * as claims from "@/lib/procurement-scoped-claims";

const organizations = vi.mocked(machine.organizations);
const identity = vi.mocked(machine.identity);
const suppliers = vi.mocked(machine.fetchProcurementSuppliers);
const list = vi.mocked(claims.listClaims);
const create = vi.mocked(claims.createClaim);
const resolve = vi.mocked(claims.resolveClaim);
const preview = vi.mocked(claims.previewUnassignedClaim);
const bind = vi.mocked(claims.bindUnassignedClaim);

const row = { organization_id: 7, order_id: null, claim: { id: 12, supplier: "Vendor A",
  supplier_id: 3, item: "Battery", reason: "Damage", order_code: "", claim_type: "брак",
  qty_affected: 1, amount_byn: "20.00", resolution: "", status: "open" as const,
  source: "manual", entity_ref: "claim:12" },
  ownership: { actor: "tester", created_at: "2026-09-24T12:00:00Z", evidence: "Act" } };

beforeEach(() => {
  vi.clearAllMocks();
  organizations.mockResolvedValue([{ id: 7, name: "Компания А", unp: "123" },
    { id: 8, name: "Компания Б", unp: "456" }]);
  identity.mockImplementation(async org => ({ organization_id: org, principal: "tester", can_manage: true }));
  list.mockImplementation(async org => ({ organization_id: org, items: org === 7 ? [row] : [],
    next_after_id: null, unassigned_claims_excluded: true }));
  suppliers.mockResolvedValue({ organization_id: 7, items: [{ id: 3, name: "Vendor A", unp: "299999001" }], truncated: false });
  create.mockResolvedValue(row);
  resolve.mockResolvedValue({ ...row, claim: { ...row.claim, status: "resolved", resolution: "Replacement" } });
  preview.mockResolvedValue({ organization_id: 7, claim_id: 23,
    source_snapshot: { id: 23, source: "production", entity_ref: "production:qc:23",
      item: "Battery", reason: "Damage", order_code: "QC-12", status: "open",
      supplier_id: null, supplier: "", amount_byn: null }, source_digest: "a".repeat(64) });
  bind.mockResolvedValue({ ...row, claim: { ...row.claim, id: 23,
    source: "production", entity_ref: "production:qc:23", order_code: "QC-12" } });
});

it("loads claims only after selecting a company and creates with directory supplier ID", async () => {
  render(<ProcurementScopedClaims />);
  await screen.findByRole("option", { name: "Компания А · 123" });
  expect(list).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText("Юрлицо претензий"), { target: { value: "7" } });
  await screen.findByText("Battery");
  fireEvent.click(screen.getByRole("button", { name: "Новая претензия" }));
  fireEvent.change(screen.getByLabelText("Поиск поставщика"), { target: { value: "Vendor" } });
  fireEvent.click(screen.getByRole("button", { name: "Найти в справочнике" }));
  await screen.findByRole("option", { name: "Vendor A · 299999001 · ID 3" });
  fireEvent.change(screen.getByLabelText("Поставщик претензии"), { target: { value: "3" } });
  fireEvent.change(screen.getByLabelText("Изделие"), { target: { value: "New battery" } });
  fireEvent.change(screen.getByLabelText("Причина"), { target: { value: "Defect" } });
  fireEvent.change(screen.getByLabelText("Основание принадлежности юрлицу"), { target: { value: "Quality act" } });
  fireEvent.click(screen.getByRole("button", { name: "Сохранить и закрыть" }));
  await waitFor(() => expect(create).toHaveBeenCalledWith(7, "tester", expect.objectContaining({
    supplier_id: 3, supplier: "Vendor A", supplier_unp: "299999001", ownership_evidence: "Quality act",
  })));
  expect(await screen.findByText("Battery")).toBeInTheDocument();
});

it("does not render a late response from another company", async () => {
  let release!: (value: Awaited<ReturnType<typeof claims.listClaims>>) => void;
  list.mockImplementation(org => org === 7 ? new Promise(done => { release = done; })
    : Promise.resolve({ organization_id: 8, items: [], next_after_id: null, unassigned_claims_excluded: true }));
  render(<ProcurementScopedClaims />);
  await screen.findByRole("option", { name: "Компания А · 123" });
  const selector = screen.getByLabelText("Юрлицо претензий");
  fireEvent.change(selector, { target: { value: "7" } });
  await waitFor(() => expect(list).toHaveBeenCalledWith(7));
  fireEvent.change(selector, { target: { value: "8" } });
  await screen.findByText("Подтверждённых претензий этого юрлица пока нет.");
  release({ organization_id: 7, items: [row], next_after_id: null, unassigned_claims_excluded: true });
  await waitFor(() => expect(screen.queryByText("Battery")).toBeNull());
});

it("keeps resolution command for exact retry after an uncertain result", async () => {
  resolve.mockRejectedValueOnce(new Error("network"));
  render(<ProcurementScopedClaims />);
  await screen.findByRole("option", { name: "Компания А · 123" });
  fireEvent.change(screen.getByLabelText("Юрлицо претензий"), { target: { value: "7" } });
  await screen.findByText("Battery");
  fireEvent.click(screen.getByRole("button", { name: "Решить" }));
  fireEvent.change(screen.getByLabelText("Как урегулировано"), { target: { value: "Replacement" } });
  fireEvent.click(screen.getByRole("button", { name: "Сохранить и закрыть" }));
  await screen.findByRole("alert");
  const first = resolve.mock.calls[0][3];
  fireEvent.click(screen.getByRole("button", { name: "Сохранить и закрыть" }));
  await waitFor(() => expect(resolve).toHaveBeenCalledTimes(2));
  expect(resolve.mock.calls[1][3]).toEqual(first);
});

it("binds an exact QC source to a directory supplier and reuses the command on retry", async () => {
  bind.mockRejectedValueOnce(new Error("network"));
  render(<ProcurementScopedClaims />);
  await screen.findByRole("option", { name: "Компания А · 123" });
  fireEvent.change(screen.getByLabelText("Юрлицо претензий"), { target: { value: "7" } });
  await screen.findByText("Battery");
  fireEvent.click(screen.getByRole("button", { name: "Сопоставить претензию ОТК" }));
  for (const [label, value] of [
    ["Ссылка ОТК (production:qc:ID)", "production:qc:23"],
    ["Изделие ОТК", "Battery"], ["Причина ОТК", "Damage"], ["Наряд ОТК", "QC-12"],
  ]) fireEvent.change(screen.getByLabelText(label), { target: { value } });
  fireEvent.click(screen.getByRole("button", { name: "Проверить первичную запись" }));
  await waitFor(() => expect(preview).toHaveBeenCalledWith(7, "tester", {
    entity_ref: "production:qc:23", item: "Battery", reason: "Damage", order_code: "QC-12",
  }));
  await screen.findByText(/Найдена претензия №23/);
  fireEvent.change(screen.getByLabelText("Поиск поставщика ОТК"), { target: { value: "Vendor" } });
  fireEvent.click(screen.getByRole("button", { name: "Найти в справочнике" }));
  await screen.findByRole("option", { name: "Vendor A · 299999001 · ID 3" });
  fireEvent.change(screen.getByLabelText("Поставщик для сопоставления"), { target: { value: "3" } });
  fireEvent.change(screen.getByLabelText("Первичное основание принадлежности юрлицу"),
    { target: { value: "Act QC-12" } });
  fireEvent.click(screen.getByRole("button", { name: "Подтвердить сопоставление и закрыть" }));
  await screen.findByRole("alert");
  const original = bind.mock.calls[0][3];
  expect(bind.mock.calls[0].slice(0, 3)).toEqual([7, 23, "tester"]);
  expect(original).toMatchObject({ entity_ref: "production:qc:23", expected_digest: "a".repeat(64),
    supplier_id: 3, supplier: "Vendor A", supplier_unp: "299999001",
    ownership_evidence: "Act QC-12" });
  fireEvent.click(screen.getByRole("button", { name: "Подтвердить сопоставление и закрыть" }));
  await waitFor(() => expect(bind).toHaveBeenCalledTimes(2));
  expect(bind.mock.calls[1][3]).toEqual(original);
});
