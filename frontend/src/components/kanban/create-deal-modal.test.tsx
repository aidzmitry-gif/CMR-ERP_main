import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", () => ({ fetchCrmStaff: vi.fn(), linkCrmClientToCounterparty: vi.fn() }));
vi.mock("@/lib/crm-directory", () => ({ loadDirectory: vi.fn() }));

import { CreateDealModal } from "@/components/kanban/create-deal-modal";
import { fetchCrmStaff, linkCrmClientToCounterparty } from "@/lib/api";
import { loadDirectory } from "@/lib/crm-directory";
import type { Stage } from "@/lib/types";

const mock = (fn: unknown) => fn as ReturnType<typeof vi.fn>;
const stages: Stage[] = [{ id: "new", title: "Новая заявка", color: "#000", count: 0, sum: 0, deals: [] }];
const master = { id: 41, name: "1C buyer", unp: "123456789", is_active: true, deal_id: 8 };
const linked = { id: 72, name: "Canonical buyer", owner_id: 34, counterparty_id: 41 };

beforeEach(() => {
  vi.clearAllMocks();
  mock(loadDirectory).mockResolvedValue({ status: "ok", rows: [master], total: 1 });
  mock(linkCrmClientToCounterparty).mockResolvedValue(linked);
  mock(fetchCrmStaff).mockResolvedValue([]);
});
afterEach(() => vi.unstubAllGlobals());

function fillDeal() {
  fireEvent.change(screen.getByPlaceholderText("CRM-2024-0200"), { target: { value: "CRM-NEW" } });
  fireEvent.change(screen.getByPlaceholderText("Поставка ..."), { target: { value: "Поставка АКБ" } });
}

describe("CreateDealModal directory link", () => {
  it("accepts a BYN amount with kopecks and submits the exact amount", async () => {
    const onCreate = vi.fn().mockResolvedValue(true);
    render(<CreateDealModal client={{ id: 12, name: "CRM buyer", owner_id: 34 }} stages={stages}
      defaultStage="new" onClose={vi.fn()} onCreate={onCreate} />);
    fillDeal();
    const amount = screen.getByRole("spinbutton", { name: "Сумма, BYN" });
    fireEvent.change(amount, { target: { value: "-0.01" } });
    expect(amount).toBeInvalid();
    fireEvent.change(amount, { target: { value: "123.45" } });
    expect(amount).toBeValid();
    fireEvent.click(screen.getByRole("button", { name: "Создать" }));
    await waitFor(() => expect(onCreate).toHaveBeenCalledWith(expect.objectContaining({ amount: 123.45 })));
    expect(onCreate).toHaveBeenCalledTimes(1);
  });

  it("posts only the numeric MDM ID and rejects a mismatched server link", async () => {
    const { linkCrmClientToCounterparty: actual } = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
    const fetch = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ ...linked, source: "crm", counterparty_id: 999 }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ ...linked, source: "crm" }) });
    vi.stubGlobal("fetch", fetch);
    expect(await actual(41, "request-key-1")).toBeNull();
    expect(await actual(41, "request-key-1", 34)).toEqual(linked);
    expect(fetch.mock.calls[0][0]).toBe("/api/sales/clients");
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({ counterparty_id: 41, request_key: "request-key-1" });
    expect(JSON.parse(fetch.mock.calls[1][1].body)).toEqual({ counterparty_id: 41, request_key: "request-key-1", owner_id: 34 });
  });

  it("keeps an existing numeric CRM client without directory lookup", async () => {
    const onCreate = vi.fn().mockResolvedValue(true);
    render(<CreateDealModal client={{ id: 12, name: "CRM buyer", owner_id: 34 }} stages={stages}
      defaultStage="new" onClose={vi.fn()} onCreate={onCreate} />);
    expect(loadDirectory).not.toHaveBeenCalled();
    expect(screen.getByDisplayValue("CRM buyer")).toBeDisabled();
    fillDeal();
    fireEvent.click(screen.getByRole("button", { name: "Создать" }));
    await waitFor(() => expect(onCreate).toHaveBeenCalledWith(expect.objectContaining({
      crm_client_id: 12, owner_id: 34, counterparty: "CRM buyer",
    })));
    expect(linkCrmClientToCounterparty).not.toHaveBeenCalled();
  });

  it("selects a visible MDM ID and submits the server-confirmed CRM client ID", async () => {
    const onCreate = vi.fn().mockResolvedValue(true);
    mock(loadDirectory).mockResolvedValue({ status: "ok", rows: [master,
      { id: 99, name: "CRM-only", unp: null, is_active: true, deal_id: null, source: "crm" },
      { id: 100, name: "Archived", unp: null, is_active: false, deal_id: null }], total: 3 });
    render(<CreateDealModal stages={stages} defaultStage="new" onClose={vi.fn()} onCreate={onCreate} />);
    const choice = await screen.findByRole("button", { name: /1C buyer.*ID 41/ });
    expect(screen.queryByText("CRM-only")).not.toBeInTheDocument();
    expect(screen.queryByText("Archived")).not.toBeInTheDocument();
    fillDeal();
    fireEvent.click(choice);
    fireEvent.click(screen.getByRole("button", { name: "Создать" }));
    await waitFor(() => expect(linkCrmClientToCounterparty).toHaveBeenCalledWith(41, expect.any(String), undefined));
    expect(onCreate).toHaveBeenCalledWith(expect.objectContaining({
      crm_client_id: 72, counterparty: "Canonical buyer", owner_id: 34, number: "CRM-NEW",
    }));
  });

  it("clears a selection when search changes and never links free text", async () => {
    const onCreate = vi.fn().mockResolvedValue(true);
    render(<CreateDealModal stages={stages} defaultStage="new" onClose={vi.fn()} onCreate={onCreate} />);
    fireEvent.click(await screen.findByRole("button", { name: /1C buyer.*ID 41/ }));
    fillDeal();
    fireEvent.change(screen.getByPlaceholderText("Название или УНП"), { target: { value: "Other" } });
    expect(screen.getByPlaceholderText("Выберите контрагента выше")).toHaveValue("");
    expect(screen.queryByRole("button", { name: /1C buyer.*ID 41/ })).not.toBeInTheDocument();
    expect(screen.getByText(/Нажмите «Найти»/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Создать" }));
    expect(linkCrmClientToCounterparty).not.toHaveBeenCalled();
    expect(onCreate).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Найти" }));
    await waitFor(() => expect(loadDirectory).toHaveBeenCalledWith("clients", "Other", 0, expect.any(AbortSignal)));
  });

  it("ignores a pending old directory response after the query text changes", async () => {
    let resolve!: (value: unknown) => void;
    mock(loadDirectory).mockReturnValueOnce(new Promise((done) => { resolve = done; }));
    render(<CreateDealModal stages={stages} defaultStage="new" onClose={vi.fn()} onCreate={vi.fn()} />);
    fireEvent.change(screen.getByPlaceholderText("Название или УНП"), { target: { value: "Other" } });
    await act(async () => resolve({ status: "ok", rows: [master], total: 1 }));
    expect(screen.queryByRole("button", { name: /1C buyer.*ID 41/ })).not.toBeInTheDocument();
    expect(screen.getByText(/Нажмите «Найти»/)).toBeInTheDocument();
  });

  it("retains its request key across a failed link retry", async () => {
    mock(linkCrmClientToCounterparty).mockResolvedValueOnce(null).mockResolvedValueOnce(linked);
    const onCreate = vi.fn().mockResolvedValue(true);
    render(<CreateDealModal stages={stages} defaultStage="new" onClose={vi.fn()} onCreate={onCreate} />);
    fillDeal();
    fireEvent.click(await screen.findByRole("button", { name: /1C buyer.*ID 41/ }));
    fireEvent.click(screen.getByRole("button", { name: "Создать" }));
    await screen.findByText(/Контрагент недоступен/);
    expect(onCreate).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Создать" }));
    await waitFor(() => expect(onCreate).toHaveBeenCalled());
    expect(mock(linkCrmClientToCounterparty).mock.calls[0][1])
      .toBe(mock(linkCrmClientToCounterparty).mock.calls[1][1]);
  });

  it("requires a privileged creator to choose the owner by numeric ID", async () => {
    mock(fetchCrmStaff).mockResolvedValue([{ employee_id: 17, full_name: "Сидоров" }]);
    mock(linkCrmClientToCounterparty).mockResolvedValue({ ...linked, owner_id: 17 });
    const onCreate = vi.fn().mockResolvedValue(true);
    render(<CreateDealModal stages={stages} defaultStage="new" onClose={vi.fn()} onCreate={onCreate} canAssignOwner />);
    fillDeal();
    fireEvent.click(await screen.findByRole("button", { name: /1C buyer.*ID 41/ }));
    fireEvent.click(screen.getByRole("button", { name: "Создать" }));
    expect(linkCrmClientToCounterparty).not.toHaveBeenCalled();
    await screen.findByText("Выберите ответственного.");
    await screen.findByRole("option", { name: "Сидоров" });
    fireEvent.change(screen.getByRole("combobox", { name: "Ответственный" }), { target: { value: "17" } });
    fireEvent.click(screen.getByRole("button", { name: "Создать" }));
    await waitFor(() => expect(linkCrmClientToCounterparty).toHaveBeenCalledWith(41, expect.any(String), 17));
    expect(onCreate).toHaveBeenCalledWith(expect.objectContaining({ crm_client_id: 72, owner_id: 17 }));
  });
});
