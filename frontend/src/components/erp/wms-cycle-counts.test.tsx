import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { WmsCycleCounts } from "./wms-cycle-counts";
import { deferred, detail, jsonResponse, organizations, plan } from "@/test/inventory-fixtures";

const { push } = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
beforeEach(() => { push.mockReset(); });
afterEach(() => vi.unstubAllGlobals());
const props = { initial: [plan()], organizations, initialOrganizationId: 1, today: "2026-09-09" };
function confirm(scope: ReturnType<typeof within> = screen) {
  fireEvent.change(scope.getByLabelText("Источник ожидаемого остатка"), { target: { value: "wms_physical" } });
  fireEvent.change(scope.getByLabelText("Основание проверки полноты"), { target: { value: "Полнота проверена" } });
  fireEvent.click(scope.getByRole("checkbox"));
}

it("создание плана требует org/склад/корректный период/подтверждение", async () => {
  const fetcher = vi.fn().mockResolvedValue(jsonResponse(plan({ id: 4, warehouse: "Новый" }))); vi.stubGlobal("fetch", fetcher);
  render(<WmsCycleCounts {...props} />);
  expect(screen.getByRole("button", { name: "Создать план" })).toBeDisabled();
  expect(screen.getByRole("checkbox")).not.toBeChecked();
  fireEvent.change(screen.getByLabelText("Склад"), { target: { value: "Новый" } }); confirm();
  fireEvent.change(screen.getByLabelText("Период, дней"), { target: { value: "0" } });
  expect(screen.getByRole("button", { name: "Создать план" })).toBeDisabled();
  fireEvent.change(screen.getByLabelText("Период, дней"), { target: { value: "7" } });
  fireEvent.click(screen.getByRole("button", { name: "Создать план" }));
  await screen.findByText("Новый");
  expect(JSON.parse(fetcher.mock.calls[0][1].body)).toEqual({ organization_id: 1, warehouse: "Новый", zone: null, cadence_days: 7, next_due_date: "2026-09-09", expected_source: "wms_physical", source_evidence: "Полнота проверена", journal_complete: true });
  expect(screen.getByRole("checkbox")).not.toBeChecked();
});

it("run требует новое незаполненное подтверждение и передаёт его без org из клиента", async () => {
  const fetcher = vi.fn().mockResolvedValue(jsonResponse(detail())); vi.stubGlobal("fetch", fetcher);
  render(<WmsCycleCounts {...props} />);
  expect(screen.getByText("Просрочено")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Запустить" }));
  const scope = within(screen.getByRole("region", { name: "Подтверждение запуска" }));
  expect(scope.getByRole("checkbox")).not.toBeChecked();
  expect(scope.getByRole("button", { name: "Подтвердить и запустить" })).toBeDisabled();
  expect(fetcher).not.toHaveBeenCalled(); confirm(scope);
  fireEvent.click(scope.getByRole("button", { name: "Подтвердить и запустить" }));
  await waitFor(() => expect(push).toHaveBeenCalledWith("/erp/wms/inventory/7"));
  expect(fetcher.mock.calls[0][0]).toBe("/api/wms/cycle-plans/3/run");
  expect(JSON.parse(fetcher.mock.calls[0][1].body)).toEqual({ expected_source: "wms_physical", source_evidence: "Полнота проверена", journal_complete: true });
});

it("отмена и повторный выбор run не переиспользуют подтверждение", () => {
  render(<WmsCycleCounts {...props} />);
  fireEvent.click(screen.getByRole("button", { name: "Запустить" }));
  const scope = within(screen.getByRole("region", { name: "Подтверждение запуска" })); confirm(scope);
  fireEvent.click(scope.getByRole("button", { name: "Отмена" }));
  fireEvent.click(screen.getByRole("button", { name: "Запустить" }));
  const fresh = within(screen.getByRole("region", { name: "Подтверждение запуска" }));
  expect(fresh.getByRole("checkbox")).not.toBeChecked();
  expect(fresh.getByLabelText("Основание проверки полноты")).toHaveValue("");
});

it("409 run не превращается в обновление пустого списка или переход", async () => {
  const fetcher = vi.fn().mockResolvedValue(jsonResponse({ detail: "Журнал изменился" }, 409)); vi.stubGlobal("fetch", fetcher);
  render(<WmsCycleCounts {...props} />); fireEvent.click(screen.getByRole("button", { name: "Запустить" }));
  const scope = within(screen.getByRole("region", { name: "Подтверждение запуска" })); confirm(scope);
  fireEvent.click(scope.getByRole("button", { name: "Подтвердить и запустить" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Журнал изменился");
  expect(fetcher).toHaveBeenCalledTimes(1); expect(push).not.toHaveBeenCalled();
  expect(scope.getByRole("checkbox")).not.toBeChecked();
  expect(scope.getByRole("button", { name: "Подтвердить и запустить" })).toBeDisabled();
  expect(screen.queryByText("Планов пока нет")).not.toBeInTheDocument();
});

it("смена страницы игнорирует поздний run прежнего плана", async () => {
  const old = deferred<Response>(); vi.stubGlobal("fetch", vi.fn(() => old.promise));
  const view = render(<WmsCycleCounts {...props} />); fireEvent.click(screen.getByRole("button", { name: "Запустить" }));
  const scope = within(screen.getByRole("region", { name: "Подтверждение запуска" })); confirm(scope);
  fireEvent.click(scope.getByRole("button", { name: "Подтвердить и запустить" }));
  view.rerender(<WmsCycleCounts {...props} initial={[plan({ id: 9, organization_id: 2, warehouse: "Другой" })]} initialOrganizationId={2} />);
  await act(async () => old.resolve(jsonResponse(detail())));
  expect(screen.getByText("Другой")).toBeInTheDocument(); expect(push).not.toHaveBeenCalled();
});

it("смена org игнорирует поздний сбой списка предыдущего юрлица", async () => {
  const old = deferred<Response>();
  vi.stubGlobal("fetch", vi.fn((url: string) => url.endsWith("=1") ? old.promise : Promise.resolve(jsonResponse([plan({ id: 9, organization_id: 2, warehouse: "Компания Б склад" })]))));
  render(<WmsCycleCounts {...props} initial={[]} initialOrganizationId={null} />);
  fireEvent.change(screen.getByLabelText("Юрлицо"), { target: { value: "1" } });
  fireEvent.change(screen.getByLabelText("Юрлицо"), { target: { value: "2" } });
  await screen.findByText("Компания Б склад");
  await act(async () => old.reject(new Error("Old connection failed")));
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(screen.getByText("Компания Б склад")).toBeInTheDocument();
});
