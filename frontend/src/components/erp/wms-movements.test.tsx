import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
vi.mock("next/link", () => ({ default: ({ children, href }: { children: React.ReactNode; href: string }) => <a href={href}>{children}</a> }));
vi.mock("@/lib/instance-organization", () => ({ fetchInstanceOrganization: vi.fn() }));
vi.mock("@/lib/wms-ops", async (importActual) => ({
  ...await importActual<typeof import("@/lib/wms-ops")>(),
  fetchMovements: vi.fn(), fetchLocations: vi.fn(), fetchOperationWarehouses: vi.fn(),
  shipment: vi.fn(), adjustment: vi.fn(), transfer: vi.fn(),
}));
import { WmsMovements } from "@/components/erp/wms-movements";
import { fetchInstanceOrganization } from "@/lib/instance-organization";
import * as wms from "@/lib/wms-ops";
import type { StockMovement, WmsLocation } from "@/lib/wms-ops";
function mv(over: Partial<StockMovement> = {}): StockMovement {
  return {
    id: 1,
    organization_id: 7,
    sku_code: "6СТ-190",
    warehouse: "Главный",
    kind: "in",
    qty: 5,
    reason: "receipt",
    location_id: null,
    batch_ref: "",
    doc_ref: "ПР-1",
    note: "",
    created_at: "2026-07-15T10:00:00",
    ...over,
  };
}

const inRow = mv({ id: 1, sku_code: "6СТ-190", kind: "in", qty: 5, reason: "receipt" });
const outRow = mv({ id: 2, sku_code: "6СТ-100", kind: "out", qty: 12, reason: "shipment", doc_ref: "" });

const locations: WmsLocation[] = [
  { id: 10, warehouse: "Главный", zone: "A", code: "01", title: "", is_active: true },
  { id: 13, warehouse: "Главный", zone: "A", code: "02", title: "", is_active: true },
  { id: 11, warehouse: "Главный", zone: "B", code: "99", title: "", is_active: false },
  { id: 12, warehouse: "Второй", zone: "C", code: "07", title: "", is_active: true },
];

const company = { id: 7, name: "Synthetic company", unp: "123456789" };
const warehouse = (name: string, id: number) => ({ id, name, title: name, organization_id: 7,
  is_active: true, wms_enabled: false, prohibit_negative_stock: true });
const page = { organization_id: 7, items: [warehouse("Главный", 1), warehouse("Второй", 2)], truncated: false };
beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(fetchInstanceOrganization).mockResolvedValue(company);
  vi.mocked(wms.fetchMovements).mockResolvedValue([]);
  vi.mocked(wms.fetchOperationWarehouses).mockResolvedValue(page);
  vi.mocked(wms.fetchLocations).mockImplementation(async name => locations.filter(row => row.is_active && row.warehouse === name));
  vi.mocked(wms.shipment).mockResolvedValue(true);
  vi.mocked(wms.adjustment).mockResolvedValue(true);
  vi.mocked(wms.transfer).mockResolvedValue(true);
});
async function choose(name: string) {
  fireEvent.change(screen.getByLabelText("Склад операции"), { target: { value: name } });
  await waitFor(() => expect(screen.getByRole("button", { name: "Записать" })).toBeEnabled());
}
async function mount(rows: StockMovement[] = [], selected = "Главный") {
  vi.mocked(wms.fetchMovements).mockResolvedValueOnce(rows);
  render(<WmsMovements />);
  await waitFor(() => expect(screen.getByLabelText("Склад операции")).toBeEnabled());
  if (selected) await choose(selected);
}
function fill(qty = "1") {
  fireEvent.change(screen.getByPlaceholderText("Код SKU*"), { target: { value: "A" } });
  fireEvent.change(screen.getByPlaceholderText("Кол-во*"), { target: { value: qty } });
}
const save = () => fireEvent.click(screen.getByRole("button", { name: "Записать" }));
const refresh = () => fireEvent.click(screen.getByRole("button", { name: /Обновить/ }));
describe("WmsMovements", () => {
  it("направляет накладную поставщика в закупки без ручной приёмки", async () => {
    await mount();
    expect(screen.getByRole("link", { name: /Накладные на поступление/ })).toHaveAttribute("href", "/erp/procurement/receipts");
    expect(screen.queryByRole("button", { name: "Приёмка" })).not.toBeInTheDocument();
  });
  it("clears the selected location when warehouse changes", async () => {
    await mount(); fireEvent.change(screen.getByLabelText("Из ячейки"), { target: { value: "10" } });
    await choose("Второй"); fill(); save();
    await waitFor(() => expect(wms.shipment).toHaveBeenCalledWith(expect.objectContaining({ warehouse: "Второй", location_id: null })));
  });
  it("locks fields and operation tabs until posting finishes", async () => {
    await mount(); let finish!: (value: boolean) => void;
    vi.mocked(wms.shipment).mockReturnValueOnce(new Promise(resolve => { finish = resolve; }));
    fill(); save();
    await waitFor(() => expect(wms.shipment).toHaveBeenCalledOnce());
    expect(screen.getByPlaceholderText("Код SKU*")).toBeDisabled();
    expect(screen.getByRole("button", { name: /Отгрузка/ })).toBeDisabled();
    expect(screen.getByLabelText("Склад операции")).toBeDisabled();
    await act(async () => finish(false));
    expect(await screen.findByText(/Не удалось подтвердить запись/)).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Код SKU*")).toHaveValue("A");
  });
  it("keeps previous rows on failed refresh and permits read-only retry", async () => {
    await mount([inRow]); vi.mocked(wms.fetchMovements).mockRejectedValueOnce(Error()); refresh();
    expect(await screen.findByText(/Показаны ранее загруженные движения/)).toBeInTheDocument();
    expect(screen.getByText("6СТ-190")).toBeInTheDocument(); refresh();
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
    expect(wms.shipment).not.toHaveBeenCalled();
  });
  it("distinguishes saved movement from failed refresh", async () => {
    await mount([inRow]); vi.mocked(wms.fetchMovements).mockRejectedValueOnce(Error()); fill(); save();
    expect(await screen.findByText(/Движение записано, но журнал не обновился/)).toBeInTheDocument();
    expect(screen.getByText("6СТ-190")).toBeInTheDocument();
    expect(wms.shipment).toHaveBeenCalledOnce();
    expect(screen.getByRole("button", { name: "Записать" })).toBeDisabled();
  });
  it("uses configured company but requires explicit warehouse without a default", async () => {
    await mount([], ""); expect(screen.getByText(/Synthetic company/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Юрлицо операции")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Склад операции")).toHaveValue("");
    fill(); save(); expect(screen.getByText("Выберите склад операции")).toBeInTheDocument();
    expect(wms.shipment).not.toHaveBeenCalled();
  });
  it("renders Russian reason, signed quantity, colors and SKUs", async () => {
    await mount([inRow, outRow]); const journal = within(screen.getByRole("table"));
    expect(journal.getByText("Приёмка")).toBeInTheDocument(); expect(journal.getByText("Отгрузка")).toBeInTheDocument();
    expect(screen.getByText("+5").className).toMatch(/text-green-600/);
    expect(screen.getByText("−12").className).toMatch(/text-red-600/);
    expect(screen.getByText("6СТ-190")).toBeInTheDocument(); expect(screen.getByText("6СТ-100")).toBeInTheDocument();
  });
  it("shows empty journal only after a successful load", async () => {
    await mount(); expect(screen.getByText("Движений по фильтру нет")).toBeInTheDocument();
  });
  it("filters journal by reason", async () => {
    await mount([inRow, outRow]);
    fireEvent.change(screen.getAllByRole("combobox").find(s => s.textContent?.includes("Все типы"))!, { target: { value: "shipment" } });
    expect(screen.queryByText("6СТ-190")).not.toBeInTheDocument(); expect(screen.getByText("6СТ-100")).toBeInTheDocument();
  });
  it("loads active locations only for the explicitly selected warehouse", async () => {
    await mount(); expect(wms.fetchLocations).toHaveBeenCalledWith("Главный");
    expect(screen.getByRole("option", { name: "A · 01" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "B · 99" })).not.toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "C · 07" })).not.toBeInTheDocument();
  });
  it("rejects missing SKU/quantity without a write", async () => {
    await mount(); save(); expect(screen.getByText(/Укажите корректное количество/)).toBeInTheDocument();
    expect(wms.shipment).not.toHaveBeenCalled();
  });
  it("posts decimal-comma quantity with exact company and warehouse then refreshes", async () => {
    await mount(); vi.mocked(wms.fetchMovements).mockResolvedValueOnce([mv({ sku_code: "НОВЫЙ-SKU" })]); fill("2,5"); save();
    expect(await screen.findByText("Движение записано")).toBeInTheDocument();
    expect(wms.shipment).toHaveBeenCalledWith(expect.objectContaining({ organization_id: 7, warehouse: "Главный", sku_code: "A", qty: 2.5 }));
    expect(wms.fetchMovements).toHaveBeenLastCalledWith(7); expect(screen.getByText("НОВЫЙ-SKU")).toBeInTheDocument();
  });
  it("does not refresh journal after unconfirmed posting", async () => {
    await mount(); vi.mocked(wms.fetchMovements).mockClear(); vi.mocked(wms.shipment).mockResolvedValueOnce(false);
    fill(); save(); expect(await screen.findByText(/Не удалось подтвердить запись/)).toBeInTheDocument();
    expect(wms.fetchMovements).not.toHaveBeenCalled();
  });
  it("sends adjustment instead of shipment", async () => {
    await mount(); fireEvent.click(screen.getByRole("button", { name: /Коррекция/ }));
    fireEvent.change(screen.getByPlaceholderText("Код SKU*"), { target: { value: "A" } });
    fireEvent.change(screen.getByPlaceholderText("Кол-во (±)"), { target: { value: "-4" } }); save();
    await waitFor(() => expect(wms.adjustment).toHaveBeenCalledWith(expect.objectContaining({ organization_id: 7, qty: -4 })));
    expect(wms.shipment).not.toHaveBeenCalled();
  });
  it("refreshes scoped journal from backend", async () => {
    await mount(); vi.mocked(wms.fetchMovements).mockResolvedValueOnce([mv({ sku_code: "ОБНОВЛ-SKU" })]); refresh();
    expect(await screen.findByText("ОБНОВЛ-SKU")).toBeInTheDocument(); expect(wms.fetchMovements).toHaveBeenLastCalledWith(7);
  });
  it("transfers between two distinct active locations", async () => {
    await mount(); fireEvent.click(screen.getByRole("button", { name: /Перемещение/ })); fill("2");
    fireEvent.change(screen.getByLabelText("Из ячейки"), { target: { value: "10" } });
    fireEvent.change(screen.getByLabelText("В ячейку"), { target: { value: "13" } }); save();
    await waitFor(() => expect(wms.transfer).toHaveBeenCalledWith(expect.objectContaining({ organization_id: 7, warehouse: "Главный", qty: 2, from_location_id: 10, to_location_id: 13 })));
    expect(wms.shipment).not.toHaveBeenCalled();
  });
  it("gates data and writes until configured company can be retried", async () => {
    vi.mocked(fetchInstanceOrganization).mockRejectedValueOnce(Error("Configuration unavailable")); render(<WmsMovements />);
    expect(await screen.findByText("Configuration unavailable")).toBeInTheDocument();
    expect(wms.fetchMovements).not.toHaveBeenCalled(); expect(wms.fetchOperationWarehouses).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Записать" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Повторить загрузку юрлица" }));
    await waitFor(() => expect(screen.getByLabelText("Склад операции")).toBeEnabled());
  });
  it("keeps catalog failure unknown and blocks writes", async () => {
    vi.mocked(wms.fetchOperationWarehouses).mockRejectedValueOnce(Error()); render(<WmsMovements />);
    expect(await screen.findByText(/Запись недоступна/)).toBeInTheDocument();
    expect(screen.queryByText("Движений по фильтру нет")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Записать" })).toBeDisabled();
  });
  it("searches truncated warehouse catalog and clears a removed choice", async () => {
    vi.mocked(wms.fetchOperationWarehouses).mockResolvedValueOnce({ ...page, truncated: true }); await mount();
    expect(screen.getByText(/Показана часть складов/)).toBeInTheDocument();
    vi.mocked(wms.fetchOperationWarehouses).mockResolvedValueOnce({ ...page, items: [page.items[1]] });
    fireEvent.change(screen.getByLabelText("Поиск склада"), { target: { value: "Второй" } });
    fireEvent.click(screen.getByRole("button", { name: "Найти склад" }));
    await waitFor(() => expect(screen.getByLabelText("Склад операции")).toHaveValue(""));
    expect(wms.fetchOperationWarehouses).toHaveBeenLastCalledWith(7, "Второй");
    expect(screen.getByLabelText("Из ячейки")).toHaveValue("");
  });
  it("ignores late locations after warehouse is cleared by refreshed catalog", async () => {
    await mount([], ""); let finish!: (rows: WmsLocation[]) => void;
    vi.mocked(wms.fetchLocations).mockReturnValueOnce(new Promise(resolve => { finish = resolve; }));
    fireEvent.change(screen.getByLabelText("Склад операции"), { target: { value: "Главный" } });
    vi.mocked(wms.fetchOperationWarehouses).mockResolvedValueOnce({ ...page, items: [page.items[1]] }); refresh();
    await waitFor(() => expect(screen.getByLabelText("Склад операции")).toHaveValue(""));
    await act(async () => finish([locations[0]]));
    expect(screen.queryByRole("option", { name: "A · 01" })).not.toBeInTheDocument();
  });
  it("blocks transfer on unknown locations until read-only retry", async () => {
    await mount([], ""); vi.mocked(wms.fetchLocations).mockRejectedValueOnce(Error());
    fireEvent.change(screen.getByLabelText("Склад операции"), { target: { value: "Главный" } });
    expect(await screen.findByText(/Не удалось загрузить ячейки/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Записать" })).toBeDisabled(); expect(wms.transfer).not.toHaveBeenCalled();
    refresh(); await waitFor(() => expect(screen.getByRole("button", { name: "Записать" })).toBeEnabled());
  });
  it("refuses posting after installation company changed", async () => {
    await mount(); vi.mocked(fetchInstanceOrganization).mockResolvedValueOnce({ ...company, id: 8 }); fill(); save();
    expect(await screen.findByText(/Юрлицо установки изменилось/)).toBeInTheDocument(); expect(wms.shipment).not.toHaveBeenCalled();
    refresh(); await waitFor(() => expect(wms.fetchMovements).toHaveBeenCalledTimes(2));
    expect(screen.getByText(/Юрлицо установки изменилось/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Записать" })).toBeDisabled();
  });
  it("refuses transfer to same location", async () => {
    await mount(); fireEvent.click(screen.getByRole("button", { name: /Перемещение/ })); fill();
    fireEvent.change(screen.getByLabelText("Из ячейки"), { target: { value: "10" } });
    fireEvent.change(screen.getByLabelText("В ячейку"), { target: { value: "10" } }); save();
    expect(screen.getByText(/две разные ячейки/)).toBeInTheDocument(); expect(wms.transfer).not.toHaveBeenCalled();
  });
  it("never presents pending initial data as an empty journal", async () => {
    vi.mocked(wms.fetchMovements).mockReturnValueOnce(new Promise(() => {})); render(<WmsMovements />);
    expect(await screen.findByText(/наличие движений неизвестно/)).toBeInTheDocument();
    expect(screen.queryByText("Движений по фильтру нет")).not.toBeInTheDocument(); expect(screen.getByRole("button", { name: "Записать" })).toBeDisabled();
  });
  it("never posts from a form unmounted during deferred company recheck", async () => {
    const view = render(<WmsMovements />);
    await waitFor(() => expect(screen.getByLabelText("Склад операции")).toBeEnabled());
    await choose("Главный"); fill();
    let finish!: (value: typeof company) => void;
    vi.mocked(fetchInstanceOrganization).mockReturnValueOnce(new Promise(resolve => { finish = resolve; }));
    save(); await waitFor(() => expect(fetchInstanceOrganization).toHaveBeenCalledTimes(2));
    view.unmount(); await act(async () => finish(company));
    expect(wms.shipment).not.toHaveBeenCalled(); expect(wms.adjustment).not.toHaveBeenCalled(); expect(wms.transfer).not.toHaveBeenCalled();
    expect(wms.fetchMovements).toHaveBeenCalledTimes(1);
  });

});
