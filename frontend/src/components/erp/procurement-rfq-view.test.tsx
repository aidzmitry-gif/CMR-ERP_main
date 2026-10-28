import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/procurement-rfq", async () => {
  const actual = await vi.importActual<typeof import("@/lib/procurement-rfq")>("@/lib/procurement-rfq");
  return { ...actual, fetchRfqs: vi.fn(), createRfq: vi.fn(), addBid: vi.fn(), awardRfq: vi.fn() };
});

import { ProcurementRfqView } from "@/components/erp/procurement-rfq-view";
import * as api from "@/lib/procurement-rfq";
import type { Rfq } from "@/lib/procurement-rfq";

const rfq: Rfq = { id: 3, number: "RFQ-000003", organization_id: 1, request_key: "key", request_id: 9,
  item: "Сталь листовая", sku_code: "", qty: 10, status: "open", due_date: null,
  best_bid_id: 20, bids: [{ id: 20, rfq_id: 3, supplier_id: 7, price_byn: 180,
    lead_time_days: 5, incoterms: "", note: "", is_winner: false }] };
const page = { organization_id: 1, items: [rfq], next_after_id: null };
const mocked = (value: unknown) => value as ReturnType<typeof vi.fn>;

beforeEach(() => {
  vi.clearAllMocks();
  sessionStorage.clear();
  vi.stubGlobal("fetch", vi.fn((url: string) => {
    if (url.endsWith("/receipt-organizations")) return Promise.resolve({ ok: true,
      json: async () => [{ id: 1, name: "ООО А", unp: "111" }, { id: 2, name: "ООО Б", unp: "222" }] });
    if (url.includes("owned-sources")) return Promise.resolve({ ok: true,
      json: async () => ({ organization_id: Number(url.split("/")[4]), items: [{ id: 9, number: "ЗАК-9", item: "Сталь листовая" }] }) });
    if (url.endsWith("supplier-options")) return Promise.resolve({ ok: true,
      json: async () => ({ organization_id: Number(url.split("/")[4]), items: [{ id: 7, name: "Поставщик 7", unp: "777" }] }) });
    if (url.endsWith("/rfq/3/history")) return Promise.resolve({ ok: true,
      json: async () => ({ organization_id: Number(url.split("/")[4]), rfq_id: 3,
        items: [{ id: 1, action: "create", actor: "tester", created_at: "2026-09-24T10:00:00Z",
          before: null, after: { request_id: 9, item: "Сталь листовая", quantity: "10" } }] }) });
    throw new Error(url);
  }));
  mocked(api.fetchRfqs).mockImplementation(async (org: number) => org === 1 ? page : { organization_id: 2, items: [], next_after_id: null });
});

async function chooseOrg() {
  render(<ProcurementRfqView />);
  await screen.findByRole("option", { name: "ООО А · 111" });
  fireEvent.change(screen.getByLabelText("Юрлицо RFQ"), { target: { value: "1" } });
  await screen.findByRole("button", { name: /RFQ-000003.*Сталь листовая.*1 пред/ });
}

describe("ProcurementRfqView", () => {
  it("does not expose RFQs before choosing a company and clears them on company switch", async () => {
    render(<ProcurementRfqView />);
    expect(screen.getByText("Выберите юрлицо, чтобы открыть его запросы цен.")).toBeInTheDocument();
    expect(api.fetchRfqs).not.toHaveBeenCalled();
    await screen.findByRole("option", { name: "ООО А · 111" });
    fireEvent.change(screen.getByLabelText("Юрлицо RFQ"), { target: { value: "1" } });
    expect(await screen.findByText("Поставщик 7")).toBeInTheDocument();
    expect(await screen.findByText("Создан запрос")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Юрлицо RFQ"), { target: { value: "2" } });
    expect(screen.queryByText("Поставщик 7")).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("Запросов нет")).toBeInTheDocument());
  });

  it("creates RFQ from an owned request with a repeatable key", async () => {
    let confirm!: (value: Rfq) => void;
    mocked(api.createRfq).mockImplementation(() => new Promise<Rfq>((resolve) => { confirm = resolve; }));
    await chooseOrg();
    fireEvent.change(screen.getByLabelText("Заявка на закупку"), { target: { value: "9" } });
    fireEvent.click(screen.getByRole("button", { name: "Создать RFQ" }));
    await waitFor(() => expect(api.createRfq).toHaveBeenCalledWith(1, {
      request_key: expect.any(String), request_id: 9,
    }));
    expect(screen.getByLabelText("Заявка на закупку")).toHaveValue("9");
    confirm(rfq);
    await waitFor(() => expect(screen.getByLabelText("Заявка на закупку")).toHaveValue(""));
  });

  it("keeps the same create key and company after an unknown response", async () => {
    mocked(api.createRfq).mockResolvedValueOnce(null).mockResolvedValueOnce(rfq);
    await chooseOrg();
    fireEvent.change(screen.getByLabelText("Заявка на закупку"), { target: { value: "9" } });
    fireEvent.click(screen.getByRole("button", { name: "Создать RFQ" }));
    expect(await screen.findByText(/Исход создания не подтверждён/)).toBeInTheDocument();
    expect(screen.getByLabelText("Юрлицо RFQ")).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Создать RFQ" }));
    await waitFor(() => expect(api.createRfq).toHaveBeenCalledTimes(2));
    expect(mocked(api.createRfq).mock.calls[1]).toEqual(mocked(api.createRfq).mock.calls[0]);
  });

  it("restores the pending RFQ after remount without generating a new key", async () => {
    mocked(api.createRfq).mockResolvedValueOnce(null).mockResolvedValueOnce(rfq);
    const view = render(<ProcurementRfqView />);
    await screen.findByRole("option", { name: "ООО А · 111" });
    fireEvent.change(screen.getByLabelText("Юрлицо RFQ"), { target: { value: "1" } });
    await screen.findByRole("option", { name: "ЗАК-9 · Сталь листовая" });
    fireEvent.change(screen.getByLabelText("Заявка на закупку"), { target: { value: "9" } });
    fireEvent.click(screen.getByRole("button", { name: "Создать RFQ" }));
    expect(await screen.findByText(/Исход создания не подтверждён/)).toBeInTheDocument();
    expect(sessionStorage.getItem("procurement-rfq:pending:v1")).toContain('"requestId":9');
    view.unmount();
    render(<ProcurementRfqView />);
    await waitFor(() => expect(screen.getByLabelText("Юрлицо RFQ")).toHaveValue("1"));
    expect(screen.getByLabelText("Юрлицо RFQ")).toBeDisabled();
    await screen.findByRole("option", { name: "ЗАК-9 · Сталь листовая" });
    fireEvent.click(screen.getByRole("button", { name: "Создать RFQ" }));
    await waitFor(() => expect(api.createRfq).toHaveBeenCalledTimes(2));
    expect(mocked(api.createRfq).mock.calls[1]).toEqual(mocked(api.createRfq).mock.calls[0]);
    expect(sessionStorage.getItem("procurement-rfq:pending:v1")).toBeNull();
  });

  it("uses catalog supplier ID and exact price, then awards within the same company", async () => {
    let release!: (value: Rfq) => void;
    mocked(api.addBid).mockReturnValueOnce(new Promise<Rfq>((resolve) => { release = resolve; }));
    mocked(api.awardRfq).mockResolvedValue({ ...rfq, status: "awarded" });
    await chooseOrg();
    fireEvent.change(screen.getByLabelText("Поставщик предложения"), { target: { value: "7" } });
    fireEvent.change(screen.getByPlaceholderText("Цена, BYN"), { target: { value: "100.50" } });
    fireEvent.click(screen.getByRole("button", { name: /Предложение/ }));
    await waitFor(() => expect(api.addBid).toHaveBeenCalledWith(1, 3, expect.objectContaining({
      supplier_id: 7, price_byn: "100.50", bid_key: expect.any(String),
    })));
    expect(screen.getByRole("button", { name: "Выбрать" })).toBeDisabled();
    expect(api.awardRfq).not.toHaveBeenCalled();
    await act(async () => { release(rfq); });
    await waitFor(() => expect(screen.getByRole("button", { name: "Выбрать" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Выбрать" }));
    await waitFor(() => expect(api.awardRfq).toHaveBeenCalledWith(1, 3, 20));
  });

  it("restores a pending supplier bid with the same key after remount", async () => {
    mocked(api.addBid).mockResolvedValueOnce(null).mockResolvedValueOnce(rfq);
    const view = render(<ProcurementRfqView />);
    await screen.findByRole("option", { name: "ООО А · 111" });
    fireEvent.change(screen.getByLabelText("Юрлицо RFQ"), { target: { value: "1" } });
    await screen.findByLabelText("Поставщик предложения");
    fireEvent.change(screen.getByLabelText("Поставщик предложения"), { target: { value: "7" } });
    fireEvent.change(screen.getByPlaceholderText("Цена, BYN"), { target: { value: "100.50" } });
    fireEvent.click(screen.getByRole("button", { name: /Предложение/ }));
    expect(await screen.findByText(/Исход предложения не подтверждён/)).toBeInTheDocument();
    view.unmount();
    render(<ProcurementRfqView />);
    await waitFor(() => expect(screen.getByLabelText("Юрлицо RFQ")).toHaveValue("1"));
    expect(screen.getByLabelText("Юрлицо RFQ")).toBeDisabled();
    await screen.findByLabelText("Поставщик предложения");
    expect(screen.getByLabelText("Поставщик предложения")).toHaveValue("7");
    fireEvent.click(screen.getByRole("button", { name: /Предложение/ }));
    await waitFor(() => expect(api.addBid).toHaveBeenCalledTimes(2));
    expect(mocked(api.addBid).mock.calls[1]).toEqual(mocked(api.addBid).mock.calls[0]);
    expect(sessionStorage.getItem("procurement-rfq:pending:v1")).toBeNull();
  });
});
