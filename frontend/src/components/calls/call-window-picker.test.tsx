import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { CallWindow, type CallContext } from "./call-window";
import * as api from "@/lib/api";

// Real shared picker hook; only external I/O and currency formatting are synthetic.
vi.mock("@/lib/api", () => ({
  fetchStock: vi.fn(), addDealItem: vi.fn(), createPriceQuote: vi.fn(), fetchLastOrder: vi.fn(),
  createDeal: vi.fn(), createDealTask: vi.fn(), issueDocument: vi.fn(),
  lookupCounterpartyResult: vi.fn(), updateDeal: vi.fn(), requestApproval: vi.fn(),
}));
vi.mock("@/components/kanban/currency-context", () => ({
  useCurrency: () => ({ fmt: (value: number) => `${value} BYN` }),
}));
vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => <a href={href}>{children}</a>,
}));

const sku = { id: 1, code: "SYNTHETIC-A", title: "Synthetic picker product", unit: "шт" };
const deal: CallContext = { kind: "deal", dealId: "d1", company: "Synthetic customer" };
const lead: CallContext = { kind: "lead", leadId: 1, company: "Synthetic lead" };

beforeEach(() => {
  vi.resetAllMocks();
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => [sku] }));
  vi.mocked(api.fetchStock).mockResolvedValue([]);
  vi.mocked(api.addDealItem).mockResolvedValue(true);
  vi.mocked(api.createPriceQuote).mockResolvedValue(true);
  vi.mocked(api.createDealTask).mockResolvedValue(true);
});
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

async function chooseProduct() {
  await waitFor(() => expect(screen.getByText(sku.title)).toBeVisible(), { timeout: 2500 });
  fireEvent.click(screen.getByText(sku.title));
}

it("KB02 equivalent inline context retains real picker and deferred invoice lock", async () => {
  let resolve!: (result: Awaited<ReturnType<typeof api.issueDocument>>) => void;
  vi.mocked(api.issueDocument).mockReturnValue(new Promise((done) => { resolve = done; }));
  const win = { location: { href: "" }, close: vi.fn() };
  vi.spyOn(window, "open").mockReturnValue(win as unknown as Window);
  const { rerender } = render(<CallWindow context={{ ...deal }} onClose={vi.fn()} />);
  await chooseProduct();
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: /Добавить в сделку/ })); });
  fireEvent.click(screen.getByRole("button", { name: "Счёт" }));
  expect(api.issueDocument).toHaveBeenCalledOnce();
  rerender(<CallWindow context={{ ...deal }} onClose={vi.fn()} />);
  expect(screen.getByText(sku.title)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Счёт" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Счёт" }));
  expect(api.issueDocument).toHaveBeenCalledOnce();
  await act(async () => { resolve({ ok: true, message: "Synthetic issued", renderUrl: "/synthetic-render" }); });
  expect(win.location.href).toBe("/synthetic-render");
  expect(api.updateDeal).toHaveBeenCalledOnce();
  expect(api.addDealItem).toHaveBeenCalledOnce();
  expect(screen.getByRole("button", { name: "Счёт" })).toBeEnabled();
});

it("KB03 partial retry keeps known deal and explicit new order creates another", async () => {
  vi.mocked(api.createDeal).mockResolvedValueOnce({ id: "d1", number: "SYNTHETIC-1" } as NonNullable<Awaited<ReturnType<typeof api.createDeal>>>)
    .mockResolvedValueOnce({ id: "d2", number: "SYNTHETIC-2" } as NonNullable<Awaited<ReturnType<typeof api.createDeal>>>);
  vi.mocked(api.addDealItem).mockResolvedValueOnce(false).mockResolvedValue(true);
  render(<CallWindow context={lead} onClose={vi.fn()} />);
  await chooseProduct();
  const commit = () => fireEvent.click(screen.getByRole("button", { name: /Создать сделку с товаром/ }));
  await act(async () => { commit(); });
  fireEvent.click(screen.getByRole("button", { name: "Новый заказ" }));
  expect(screen.getByText(sku.title)).toBeInTheDocument();
  expect(api.createDeal).toHaveBeenCalledOnce();
  await act(async () => { commit(); });
  expect(api.createDeal).toHaveBeenCalledOnce();
  expect(vi.mocked(api.addDealItem).mock.calls.map((args) => args[0])).toEqual(["d1", "d1"]);
  expect(vi.mocked(api.addDealItem).mock.calls[0]).toEqual(vi.mocked(api.addDealItem).mock.calls[1]);
  fireEvent.click(screen.getByRole("button", { name: "Новый заказ" }));
  await chooseProduct();
  await act(async () => { commit(); });
  expect(api.createDeal).toHaveBeenCalledTimes(2);
  expect(vi.mocked(api.addDealItem).mock.calls.map((args) => args[0])).toEqual(["d1", "d1", "d2"]);
  expect(vi.mocked(api.addDealItem).mock.calls[2][4]).not.toBe(vi.mocked(api.addDealItem).mock.calls[0][4]);
});
