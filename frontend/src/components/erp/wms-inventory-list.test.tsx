import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { WmsInventoryList } from "./wms-inventory-list";
import { deferred, inventory, jsonResponse, organizations } from "@/test/inventory-fixtures";

const { push } = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
beforeEach(() => { push.mockReset(); });
afterEach(() => vi.unstubAllGlobals());
const props = { initial: [], organizations, initialOrganizationId: null };

function confirm() {
  fireEvent.change(screen.getByLabelText("Источник ожидаемого остатка"), { target: { value: "wms_physical" } });
  fireEvent.change(screen.getByLabelText("Основание проверки полноты"), { target: { value: "Полнота проверена" } });
  fireEvent.click(screen.getByRole("checkbox"));
}

it("ничего не выбирает автоматически; создание требует всех полей", async () => {
  const fetcher = vi.fn().mockResolvedValue(jsonResponse([])); vi.stubGlobal("fetch", fetcher);
  render(<WmsInventoryList {...props} />);
  expect(screen.getByLabelText("Юрлицо")).toHaveValue("");
  expect(screen.getByRole("checkbox")).not.toBeChecked();
  expect(screen.getByRole("button", { name: "Новая инвентаризация" })).toBeDisabled();
  expect(fetcher).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText("Юрлицо"), { target: { value: "1" } });
  await screen.findByText("Инвентаризаций пока нет");
  fireEvent.change(screen.getByLabelText("Склад"), { target: { value: "Минск" } }); confirm();
  fetcher.mockResolvedValueOnce(jsonResponse(inventory()));
  fireEvent.click(screen.getByRole("button", { name: "Новая инвентаризация" }));
  await waitFor(() => expect(push).toHaveBeenCalledWith("/erp/wms/inventory/7"));
  const [, options] = fetcher.mock.calls.at(-1)!;
  expect(JSON.parse(options.body)).toEqual({ organization_id: 1, warehouse: "Минск", expected_source: "wms_physical", source_evidence: "Полнота проверена", journal_complete: true });
});

it.each([403, 409, 503])("HTTP %s при чтении показывает ошибку вместо пустого списка", async (status) => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ detail: "Ошибка чтения" }, status)));
  render(<WmsInventoryList {...props} />);
  fireEvent.change(screen.getByLabelText("Юрлицо"), { target: { value: "1" } });
  expect(await screen.findByRole("alert")).toHaveTextContent("Ошибка чтения");
  expect(screen.queryByText("Инвентаризаций пока нет")).not.toBeInTheDocument();
});

it("смена юрлица игнорирует поздний список и сбрасывает подтверждение", async () => {
  const old = deferred<Response>();
  vi.stubGlobal("fetch", vi.fn((url: string) => url.endsWith("=1") ? old.promise : Promise.resolve(jsonResponse([inventory({ id: 8, number: "ИНВ-Б", organization_id: 2 })]))));
  render(<WmsInventoryList {...props} />);
  fireEvent.change(screen.getByLabelText("Юрлицо"), { target: { value: "1" } });
  fireEvent.change(screen.getByLabelText("Юрлицо"), { target: { value: "2" } });
  await screen.findByText("ИНВ-Б");
  await act(async () => old.resolve(jsonResponse([inventory({ number: "СТАРЫЙ" })])));
  expect(screen.queryByText("СТАРЫЙ")).not.toBeInTheDocument();
  expect(screen.getByRole("checkbox")).not.toBeChecked();
});

it("поздний ответ создания не переводит на документ прежнего юрлица", async () => {
  const old = deferred<Response>();
  vi.stubGlobal("fetch", vi.fn((url: string, options?: RequestInit) => options?.method === "POST" ? old.promise : Promise.resolve(jsonResponse([]))));
  render(<WmsInventoryList initial={[]} organizations={organizations} initialOrganizationId={1} />);
  fireEvent.change(screen.getByLabelText("Склад"), { target: { value: "Минск" } }); confirm();
  fireEvent.click(screen.getByRole("button", { name: "Новая инвентаризация" }));
  fireEvent.change(screen.getByLabelText("Юрлицо"), { target: { value: "2" } });
  await screen.findByText("Инвентаризаций пока нет");
  await act(async () => old.resolve(jsonResponse(inventory())));
  expect(push).not.toHaveBeenCalled();
  expect(screen.getByRole("checkbox")).not.toBeChecked();
});

it("сетевая ошибка создания сохраняет введённые данные и видимый сбой", async () => {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
  render(<WmsInventoryList initial={[]} organizations={organizations} initialOrganizationId={1} />);
  fireEvent.change(screen.getByLabelText("Склад"), { target: { value: "Минск" } }); confirm();
  fireEvent.click(screen.getByRole("button", { name: "Новая инвентаризация" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Ошибка сети");
  expect(screen.getByLabelText("Основание проверки полноты")).toHaveValue("Полнота проверена");
  expect(push).not.toHaveBeenCalled();
});
