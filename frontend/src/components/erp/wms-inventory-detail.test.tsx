import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { WmsInventoryDetail } from "./wms-inventory-detail";
import { deferred, detail, inventory, jsonResponse } from "@/test/inventory-fixtures";
afterEach(() => vi.unstubAllGlobals());

it("показывает provenance, версию, количественное расхождение и неизвестную стоимость", () => {
  render(<WmsInventoryDetail initial={detail()} />);
  expect(screen.getByRole("heading", { name: "ИНВ-7" })).toBeInTheDocument();
  expect(screen.getByText("Физический журнал WMS")).toBeInTheDocument();
  expect(screen.getByText("Акт пересчёта")).toBeInTheDocument();
  expect(screen.getByText("a".repeat(64))).toBeInTheDocument();
  expect(screen.getByText("31")).toBeInTheDocument();
  expect(screen.getAllByText("Неизвестно")).toHaveLength(3);
  expect(screen.getByText("-3")).toHaveClass("text-red-600");
  expect(screen.queryByText("0 BYN")).not.toBeInTheDocument();
  expect(screen.queryByText(/Ожидается \(1С\)/)).not.toBeInTheDocument();
});

it("неполный пересчёт и незаполненный снимок нельзя провести", () => {
  const current = detail(); current.lines[0].counted_qty = null;
  render(<WmsInventoryDetail initial={current} />);
  expect(screen.getByRole("button", { name: "Провести" })).toBeDisabled();
});

it("проведение сохраняет статус и блокирует дальнейший ввод", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(inventory({ status: "done" }))));
  render(<WmsInventoryDetail initial={detail()} />); fireEvent.click(screen.getByRole("button", { name: "Провести" }));
  await screen.findByText("Проведена");
  expect(screen.queryByRole("button", { name: "Провести" })).not.toBeInTheDocument();
  expect(screen.queryByLabelText("Факт SKU")).not.toBeInTheDocument();
});

it("stale 409 сохраняет снимок, запрещает повторное проведение и предлагает новый пересчёт", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ detail: "Журнал изменился" }, 409)));
  render(<WmsInventoryDetail initial={detail()} />); fireEvent.click(screen.getByRole("button", { name: "Провести" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Журнал изменился");
  expect(screen.getByText("a".repeat(64))).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Провести" })).toBeDisabled();
  expect(screen.getByRole("link", { name: "Создать новый пересчёт" })).toHaveAttribute("href", "/erp/wms/inventory?organization_id=1");
});

it("пустое количество не отправляет ноль или null", () => {
  const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
  render(<WmsInventoryDetail initial={detail()} />);
  fireEvent.change(screen.getByLabelText("Факт SKU"), { target: { value: "" } }); fireEvent.blur(screen.getByLabelText("Факт SKU"));
  expect(fetcher).not.toHaveBeenCalled(); expect(screen.getByRole("alert")).toHaveTextContent("не считается нулём");
});

it("неудачная запись сохраняет черновик и не проводит документ", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ detail: "Нет доступа" }, 403)));
  render(<WmsInventoryDetail initial={detail()} />);
  fireEvent.change(screen.getByLabelText("Факт SKU"), { target: { value: "28" } }); fireEvent.blur(screen.getByLabelText("Факт SKU"));
  await screen.findByRole("alert"); expect(screen.getByLabelText("Факт SKU")).toHaveValue("28");
  expect(screen.getByRole("button", { name: "Провести" })).toBeDisabled();
});

it("успешная запись пересчёта обновляет факт после чтения документа", async () => {
  const fresh = detail(); fresh.lines[0].counted_qty = 28;
  const fetcher = vi.fn().mockResolvedValueOnce(jsonResponse(fresh.lines[0])).mockResolvedValueOnce(jsonResponse(fresh)); vi.stubGlobal("fetch", fetcher);
  render(<WmsInventoryDetail initial={detail()} />);
  fireEvent.change(screen.getByLabelText("Факт SKU"), { target: { value: "28" } }); fireEvent.blur(screen.getByLabelText("Факт SKU"));
  await waitFor(() => expect(screen.getByRole("button", { name: "Провести" })).toBeEnabled());
  expect(JSON.parse(fetcher.mock.calls[0][1].body)).toEqual({ counted_qty: 28 });
});

it("смена документа игнорирует поздний populate предыдущей страницы", async () => {
  const old = deferred<Response>(); vi.stubGlobal("fetch", vi.fn(() => old.promise));
  const view = render(<WmsInventoryDetail initial={detail({ lines: [], snapshot_version: null })} />);
  fireEvent.click(screen.getByRole("button", { name: "Зафиксировать снимок WMS" }));
  view.rerender(<WmsInventoryDetail initial={detail({ id: 9, number: "ИНВ-9", organization_id: 2 })} />);
  await act(async () => old.resolve(jsonResponse(detail())));
  expect(screen.getByRole("heading", { name: "ИНВ-9" })).toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "ИНВ-7" })).not.toBeInTheDocument();
});
