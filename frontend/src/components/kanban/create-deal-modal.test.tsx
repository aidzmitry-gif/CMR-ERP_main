import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", () => ({ fetchCrmStaff: vi.fn(), fetchBuyerOptions: vi.fn(), linkCrmClientToCounterparty: vi.fn() }));

import { CreateDealModal } from "@/components/kanban/create-deal-modal";
import { fetchCrmStaff, fetchBuyerOptions, linkCrmClientToCounterparty } from "@/lib/api";
import type { Stage } from "@/lib/types";

const mock = (fn: unknown) => fn as ReturnType<typeof vi.fn>;
const stages: Stage[] = [{ id: "new", title: "Новая заявка", color: "#000", count: 0, sum: 0, deals: [] }];
const master = { id: 41, name: "1C buyer", unp: "123456789" };
const linked = { id: 72, name: "Canonical buyer", owner_id: 34, counterparty_id: 41 };

beforeEach(() => {
  vi.clearAllMocks();
  mock(fetchBuyerOptions).mockResolvedValue({ status: "ok", rows: [master], total: 1 });
  mock(linkCrmClientToCounterparty).mockResolvedValue(linked);
  mock(fetchCrmStaff).mockResolvedValue([]);
});
afterEach(() => vi.unstubAllGlobals());

function fillDeal() {
  fireEvent.change(screen.getByPlaceholderText("CRM-2024-0200"), { target: { value: "CRM-NEW" } });
  fireEvent.change(screen.getByPlaceholderText("Поставка ..."), { target: { value: "Поставка АКБ" } });
}

describe("CreateDealModal directory link", () => {
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
    render(<CreateDealModal client={{ id: 12, name: "CRM buyer", owner_id: 34, counterparty_id: 41 }} stages={stages}
      defaultStage="new" onClose={vi.fn()} onCreate={onCreate} />);
    expect(fetchBuyerOptions).not.toHaveBeenCalled();
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
    // The basic endpoint excludes CRM relationships and archived master records.
    mock(fetchBuyerOptions).mockResolvedValue({ status: "ok", rows: [master], total: 1 });
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
    await waitFor(() => expect(fetchBuyerOptions).toHaveBeenCalledWith("Other", 0, expect.any(AbortSignal)));
  });

  it("ignores a pending old directory response after the query text changes", async () => {
    let resolve!: (value: unknown) => void;
    mock(fetchBuyerOptions).mockReturnValueOnce(new Promise((done) => { resolve = done; }));
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


describe("basic buyer discovery for the original CRM client", () => {
  it("parses the real basic response and encodes query and pagination", async () => {
    const { fetchBuyerOptions: actual } = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
    const fetch = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ rows: [master], total: 3 }) });
    vi.stubGlobal("fetch", fetch);
    const signal = new AbortController().signal;
    expect(await actual("Buyer & 123", 2, signal)).toEqual({ status: "ok", rows: [master], total: 3 });
    expect(fetch).toHaveBeenCalledWith("/api/sales/buyer-options?q=Buyer+%26+123&limit=50&offset=2", { signal });
  });

  it("rejects malformed pages, identities and unexpected sensitive fields", async () => {
    const { fetchBuyerOptions: actual } = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
    for (const page of [null, { rows: [], total: -1 }, { rows: {}, total: 0 },
      { rows: [{ ...master, contacts: [] }], total: 1 }, { rows: [{ ...master, id: "41" }], total: 1 },
      { rows: [{ ...master, name: " " }], total: 1 }, { rows: [master, master], total: 2 },
      { rows: [master], total: 0 }, { rows: [{ ...master, unp: 123 }], total: 1 }]) {
      vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => page }));
      expect(await actual("", 0)).toEqual({ status: "error" });
    }
  });

  it("distinguishes HTTP and network failures from a genuine empty result", async () => {
    const { fetchBuyerOptions: actual } = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
    const fetch = vi.fn().mockResolvedValueOnce({ ok: false, status: 503 })
      .mockResolvedValueOnce({ ok: false, status: 401 }).mockResolvedValueOnce({ ok: false, status: 403 })
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({ rows: [], total: 0 }) });
    vi.stubGlobal("fetch", fetch);
    for (const status of ["error", "unauthorized", "forbidden", "error"]) {
      expect(await actual("", 0)).toEqual({ status });
    }
    expect(await actual("", 0)).toEqual({ status: "ok", rows: [], total: 0 });
  });

  it("binds the selected ID to the original unbound client without creating another client", async () => {
    const onCreate = vi.fn().mockResolvedValue(true);
    render(<CreateDealModal client={{ id: 12, name: "Working buyer", owner_id: 34, counterparty_id: null }}
      stages={stages} defaultStage="new" onClose={vi.fn()} onCreate={onCreate} />);
    fillDeal();
    fireEvent.click(await screen.findByRole("button", { name: /1C buyer.*ID 41/ }));
    expect(screen.getByDisplayValue("Working buyer")).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Создать" }));
    await waitFor(() => expect(onCreate).toHaveBeenCalledWith(expect.objectContaining({
      crm_client_id: 12, counterparty_id: 41, owner_id: 34, counterparty: "Working buyer",
    })));
    expect(linkCrmClientToCounterparty).not.toHaveBeenCalled();
  });

  it("clears the selected first buyer on new query while preserving the CRM working name", async () => {
    const onCreate = vi.fn().mockResolvedValue(true);
    render(<CreateDealModal client={{ id: 12, name: "Working buyer", owner_id: 34 }}
      stages={stages} defaultStage="new" onClose={vi.fn()} onCreate={onCreate} />);
    fillDeal();
    fireEvent.click(await screen.findByRole("button", { name: /1C buyer.*ID 41/ }));
    fireEvent.change(screen.getByPlaceholderText("Название или УНП"), { target: { value: "New query" } });
    expect(screen.getByDisplayValue("Working buyer")).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Создать" }));
    await screen.findByText("Выберите контрагента из доступного справочника.");
    expect(onCreate).not.toHaveBeenCalled();
    expect(linkCrmClientToCounterparty).not.toHaveBeenCalled();
  });

  it("retries a failed basic search through the same endpoint", async () => {
    mock(fetchBuyerOptions).mockResolvedValueOnce({ status: "error" }).mockResolvedValueOnce({ status: "ok", rows: [master], total: 1 });
    render(<CreateDealModal stages={stages} defaultStage="new" onClose={vi.fn()} onCreate={vi.fn()} />);
    await screen.findByText("Справочник недоступен. Повторите поиск.");
    fireEvent.click(screen.getByRole("button", { name: "Найти" }));
    await screen.findByRole("button", { name: /1C buyer.*ID 41/ });
    expect(fetchBuyerOptions).toHaveBeenCalledTimes(2);
  });

  it("retries the first deal against the same client and buyer without a second CRM POST", async () => {
    const onCreate = vi.fn().mockResolvedValueOnce(false).mockResolvedValueOnce(true);
    render(<CreateDealModal client={{ id: 12, name: "Working buyer", owner_id: 34 }}
      stages={stages} defaultStage="new" onClose={vi.fn()} onCreate={onCreate} />);
    fillDeal();
    fireEvent.click(await screen.findByRole("button", { name: /1C buyer.*ID 41/ }));
    fireEvent.click(screen.getByRole("button", { name: "Создать" }));
    await screen.findByText(/Не удалось создать сделку \(возможно/);
    fireEvent.click(screen.getByRole("button", { name: "Создать" }));
    await waitFor(() => expect(onCreate).toHaveBeenCalledTimes(2));
    expect(onCreate.mock.calls[0][0]).toEqual(onCreate.mock.calls[1][0]);
    expect(linkCrmClientToCounterparty).not.toHaveBeenCalled();
  });

  it("ignores late relationship replies after context change, ABA and unmount", async () => {
    for (const transition of ["different", "aba", "unmount"]) {
      mock(linkCrmClientToCounterparty).mockClear();
      let resolve!: (value: unknown) => void;
      mock(linkCrmClientToCounterparty).mockReturnValueOnce(new Promise(done => { resolve = done; }));
      const onCreate = vi.fn().mockResolvedValue(true);
      const props = { stages, defaultStage: "new", onClose: vi.fn(), onCreate };
      const view = render(<CreateDealModal {...props} />);
      fillDeal();
      fireEvent.click(await screen.findByRole("button", { name: /1C buyer.*ID 41/ }));
      fireEvent.click(screen.getByRole("button", { name: "Создать" }));
      await waitFor(() => expect(linkCrmClientToCounterparty).toHaveBeenCalledTimes(1));
      if (transition === "unmount") view.unmount();
      else {
        view.rerender(<CreateDealModal {...props}
          client={{ id: 19, name: "Other context", owner_id: 34, counterparty_id: 41 }} />);
        if (transition === "aba") view.rerender(<CreateDealModal {...props} />);
      }
      await act(async () => resolve(linked));
      expect(onCreate).not.toHaveBeenCalled();
      if (transition !== "unmount") {
        expect(screen.getByPlaceholderText("CRM-2024-0200")).toHaveValue("");
        if (transition === "different") expect(screen.getByDisplayValue("Other context")).toBeDisabled();
        view.unmount();
      }
    }
  });
});
