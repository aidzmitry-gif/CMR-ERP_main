import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { ClientDocumentRegister } from "./client-document-register";

afterEach(() => vi.unstubAllGlobals());
const context = { configuration: "AIOS_SELLER_UNP", organization: { id: 7, name: "Synthetic organization", unp: "987654321" } };
const page = {
  organization_id: 7, counterparty_id: 42,
  client_current: { id: 42, name: "Synthetic client", unp: "111111111", revision: 1, is_active: true, merged_into_id: null },
  identity_policy: "exact_binding_no_merge_follow",
  coverage: { sales_documents: "confirmed_bindings_only", settlements: "separate_chief_register", shipments: "unavailable", tn_ttn: "not_connected" },
  shipment_documents: [], items: [], next_after_id: null,
};
const ok = (data: unknown, status = 200) => ({ ok: status === 200, status, json: async () => data });

it("loads client documents for the configured organization with no organization picker", async () => {
  const fetcher = vi.fn(async (url: string) => ok(url.includes("instance-organization") ? context : page));
  vi.stubGlobal("fetch", fetcher);
  render(<ClientDocumentRegister clientId="42" />);
  expect(await screen.findByText(/Текущая запись MDM ID 42/)).toHaveTextContent("Synthetic client");
  expect(screen.queryByLabelText("Юрлицо документов клиента")).not.toBeInTheDocument();
  expect(fetcher).toHaveBeenCalledWith(expect.stringContaining("/organizations/7/counterparties/42/document-register?"), expect.anything());
  expect(fetcher.mock.calls.some(([url]) => url.includes("/document-register/organizations"))).toBe(false);
});

it("does not request client documents when the configured organization is denied", async () => {
  const fetcher = vi.fn().mockResolvedValue(ok({}, 403));
  vi.stubGlobal("fetch", fetcher);
  render(<ClientDocumentRegister clientId="42" />);
  expect(await screen.findByRole("alert")).toHaveTextContent("права сотрудника");
  expect(fetcher).toHaveBeenCalledTimes(1);
  expect(screen.getByRole("link", { name: "Настройки организации" })).toHaveAttribute("href", "/erp/settings");
});

it("retries configuration before requesting documents after a temporary failure", async () => {
  const fetcher = vi.fn().mockResolvedValueOnce(ok({}, 503)).mockResolvedValueOnce(ok(context)).mockResolvedValue(ok(page));
  vi.stubGlobal("fetch", fetcher);
  render(<ClientDocumentRegister clientId="42" />);
  await userEvent.click(await screen.findByRole("button", { name: "Повторить загрузку юрлица" }));
  await waitFor(() => expect(screen.getByText(/Текущая запись MDM ID 42/)).toBeInTheDocument());
  expect(fetcher).toHaveBeenCalledTimes(3);
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});
