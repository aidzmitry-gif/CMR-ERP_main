import { webcrypto } from "node:crypto";

import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { OfficeWarehouseProgress } from "@/components/erp/office-warehouse-progress";
import { shippingFixture } from "@/test/office-shipping-fixtures";
import { warehouseFixture } from "@/test/office-warehouse-fixtures";

beforeEach(() => vi.stubGlobal("crypto", webcrypto));
afterEach(() => vi.unstubAllGlobals());

it("shows original quantities per warehouse, released reserve and document mode with truthful coverage", async () => {
  const context = await shippingFixture({ associated: true, stage: "paid" });
  const fetcher = vi.fn<typeof fetch>().mockResolvedValue(Response.json(warehouseFixture(context, { released: true, documentMode: true }))); vi.stubGlobal("fetch", fetcher);
  render(<OfficeWarehouseProgress context={context} disabled={false} onReconciled={vi.fn()} />);
  expect(await screen.findByText("Выдача зарегистрирована частично")).toBeInTheDocument();
  const rows = screen.getAllByRole("article"); expect(rows).toHaveLength(2);
  expect(within(rows[0]).getByText("Склад W")).toBeInTheDocument(); expect(within(rows[1]).getByText("Склад W2")).toBeInTheDocument();
  expect(within(rows[1]).getAllByText("3.00")).toHaveLength(2);
  expect(screen.getByText(/Снятый резерв не считается выдачей/)).toBeInTheDocument();
  expect(screen.getByText(/Документальный режим: без подтверждения на устройстве/)).toBeInTheDocument();
  expect(screen.getByText(/Этап документа: Оплачен/)).toBeInTheDocument();
  expect(screen.getByText(/Полнота сведений из 1С/)).toBeInTheDocument();
  expect(fetcher).toHaveBeenCalledTimes(1);
});

it.each(["none_recorded", "complete"] as const)("shows the server's %s state without inventing transport delivery", async state => {
  const context = await shippingFixture({ associated: true });
  vi.stubGlobal("fetch", vi.fn<typeof fetch>().mockResolvedValue(Response.json(warehouseFixture(context, { state }))));
  render(<OfficeWarehouseProgress context={context} disabled={false} onReconciled={vi.fn()} />);
  expect(await screen.findByText(state === "complete" ? "Выдача по счёту зарегистрирована полностью" : "Выдача пока не зарегистрирована")).toBeInTheDocument();
  expect(screen.getByText(/доставка перевозчиком проверяются отдельно/)).toBeInTheDocument();
});

it("reads fresh capability before one explicit reconcile, then observes saved facts and notifies the parent", async () => {
  const context = await shippingFixture({ associated: true }); let data = warehouseFixture(context);
  const onReconciled = vi.fn(); const calls: string[] = [];
  const fetcher = vi.fn<typeof fetch>(async (_input, init) => {
    calls.push(init?.method ?? "GET");
    if (init?.method === "POST") { data = warehouseFixture(context, { state: "complete" }); data.document_stage = "shipped"; }
    return Response.json(data);
  }); vi.stubGlobal("fetch", fetcher);
  render(<OfficeWarehouseProgress context={context} disabled={false} onReconciled={onReconciled} />);
  const button = await screen.findByRole("button", { name: "Сверить документ с актами" });
  fireEvent.click(button); fireEvent.click(button);
  expect(await screen.findByText("Сверка завершена. Показаны сохранённые сведения.")).toBeInTheDocument();
  expect(calls).toEqual(["GET", "GET", "POST", "GET"]); expect(onReconciled).toHaveBeenCalledTimes(1);
  expect(screen.getByText(/Этап документа: Отгрузка оформлена/)).toBeInTheDocument();
});

it.each(["readonly", "other command pending"])("prevents reconciliation when %s", async kind => {
  const context = await shippingFixture({ associated: true });
  const fetcher = vi.fn<typeof fetch>().mockResolvedValue(Response.json(warehouseFixture(context, { canReconcile: kind !== "readonly" }))); vi.stubGlobal("fetch", fetcher);
  render(<OfficeWarehouseProgress context={context} disabled={kind !== "readonly"} onReconciled={vi.fn()} />);
  await screen.findByText("Выдача зарегистрирована частично");
  if (kind === "readonly") expect(screen.queryByRole("button", { name: "Сверить документ с актами" })).not.toBeInTheDocument();
  else expect(screen.getByRole("button", { name: "Сверить документ с актами" })).toBeDisabled();
  expect(fetcher).toHaveBeenCalledTimes(1);
});

it("does not POST when capability is revoked in the fresh preflight read", async () => {
  const context = await shippingFixture({ associated: true }); let count = 0;
  const fetcher = vi.fn<typeof fetch>(async () => Response.json(warehouseFixture(context, { canReconcile: ++count === 1 }))); vi.stubGlobal("fetch", fetcher);
  render(<OfficeWarehouseProgress context={context} disabled={false} onReconciled={vi.fn()} />);
  fireEvent.click(await screen.findByRole("button", { name: "Сверить документ с актами" }));
  expect(await screen.findByText(/Права на сверку изменились/)).toBeInTheDocument();
  expect(fetcher.mock.calls.some(([, init]) => init?.method === "POST")).toBe(false);
});

it("keeps lost POST results explicit and permits a read without any automatic command retry", async () => {
  const context = await shippingFixture({ associated: true }); let posted = false;
  const fetcher = vi.fn<typeof fetch>(async (_input, init) => {
    if (init?.method === "POST") { posted = true; throw new TypeError("synthetic lost response"); }
    return Response.json(warehouseFixture(context, { state: posted ? "complete" : "partial" }));
  }); vi.stubGlobal("fetch", fetcher);
  render(<OfficeWarehouseProgress context={context} disabled={false} onReconciled={vi.fn()} />);
  fireEvent.click(await screen.findByRole("button", { name: "Сверить документ с актами" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Связь прервана");
  expect(screen.queryByText("Выдача зарегистрирована частично")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Перечитать сведения" }));
  expect(await screen.findByText("Выдача по счёту зарегистрирована полностью")).toBeInTheDocument();
  expect(fetcher.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1);
  expect(screen.queryByText("Сверка завершена. Показаны сохранённые сведения.")).not.toBeInTheDocument();
});

it("does not POST when another command becomes pending during the preflight GET", async () => {
  const context = await shippingFixture({ associated: true }); let reads = 0;
  let finish: ((value: Response) => void) | undefined;
  const fetcher = vi.fn<typeof fetch>(async () => ++reads === 1 ? Response.json(warehouseFixture(context)) : new Promise<Response>(resolve => { finish = resolve; }));
  vi.stubGlobal("fetch", fetcher);
  const view = render(<OfficeWarehouseProgress context={context} disabled={false} onReconciled={vi.fn()} />);
  fireEvent.click(await screen.findByRole("button", { name: "Сверить документ с актами" }));
  await waitFor(() => expect(finish).toBeDefined());
  view.rerender(<OfficeWarehouseProgress context={context} disabled onReconciled={vi.fn()} />);
  finish!(Response.json(warehouseFixture(context)));
  expect(await screen.findByText("Дождитесь завершения другой команды перед сверкой.")).toBeInTheDocument();
  expect(fetcher.mock.calls.some(([, init]) => init?.method === "POST")).toBe(false);
});

it("shows failed reads as unknown, supports explicit GET recovery and never substitutes zero quantities", async () => {
  const context = await shippingFixture({ associated: true });
  const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json({}, { status: 503 })).mockResolvedValue(Response.json(warehouseFixture(context))); vi.stubGlobal("fetch", fetcher);
  render(<OfficeWarehouseProgress context={context} disabled={false} onReconciled={vi.fn()} />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Отсутствие ответа не означает отсутствие выдачи");
  expect(screen.queryByRole("article")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Перечитать сведения" }));
  expect(await screen.findByText("Выдача зарегистрирована частично")).toBeInTheDocument();
  expect(fetcher).toHaveBeenCalledTimes(2);
});

it("rejects another principal before posting and ignores a late response from the old selected document", async () => {
  const old = await shippingFixture({ associated: true }), next = await shippingFixture({ associated: true, id: 16 });
  let finish: ((value: Response) => void) | undefined;
  const fetcher = vi.fn<typeof fetch>(async input => String(input).includes("/15/") ? new Promise<Response>(resolve => { finish = resolve; }) : Response.json({ ...warehouseFixture(next), principal: "other-principal" }));
  vi.stubGlobal("fetch", fetcher);
  const view = render(<OfficeWarehouseProgress context={old} disabled={false} onReconciled={vi.fn()} />);
  await waitFor(() => expect(finish).toBeDefined());
  view.rerender(<OfficeWarehouseProgress context={next} disabled={false} onReconciled={vi.fn()} />);
  expect(await screen.findByRole("alert")).toHaveTextContent("не прошли сверку");
  finish!(Response.json(warehouseFixture(old)));
  await waitFor(() => expect(screen.queryByRole("article")).not.toBeInTheDocument());
  expect(fetcher.mock.calls.some(([, init]) => init?.method === "POST")).toBe(false);
});
