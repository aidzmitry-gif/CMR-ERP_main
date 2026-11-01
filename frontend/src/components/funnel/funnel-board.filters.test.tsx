import { webcrypto } from "node:crypto";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import OfficePage from "@/app/erp/office/page";
import { FunnelBoard } from "@/components/funnel/funnel-board";
import { formatByn } from "@/lib/format";
import type { FunnelCard, FunnelStage } from "@/lib/types";
import { documentFixture, shippingFixture } from "@/test/office-shipping-fixtures";
import { warehouseFixture } from "@/test/office-warehouse-fixtures";

vi.mock("@/components/app-shell", () => ({ AppShell: ({ children }: { children: React.ReactNode }) => <>{children}</> }));
vi.mock("@dnd-kit/core", () => ({
  DndContext: ({ children, onDragStart, onDragEnd }: { children: React.ReactNode; onDragStart: (e: { active: { id: number } }) => void; onDragEnd: (e: { active: { id: number }; over: { id: string } }) => void }) => <div>
    <button onClick={() => onDragStart({ active: { id: 1 } })}>Учебное начало перетаскивания</button>
    <button onClick={() => onDragEnd({ active: { id: 1 }, over: { id: "docs" } })}>Учебный перенос в docs</button>
    <button onClick={() => onDragEnd({ active: { id: 1 }, over: { id: "foreign_stage" } })}>Учебный неизвестный этап</button>
    {children}
  </div>,
  DragOverlay: ({ children }: { children: React.ReactNode }) => <div data-testid="filter-drag-preview">{children}</div>,
  PointerSensor: class {}, useSensor: () => ({}), useSensors: () => [],
  useDraggable: () => ({ attributes: {}, listeners: {}, setNodeRef: () => {}, isDragging: false }),
  useDroppable: () => ({ setNodeRef: () => {}, isOver: false }),
}));

beforeEach(() => { vi.stubGlobal("crypto", webcrypto); sessionStorage.clear(); });
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });
const generic = { title: "Учебная соседняя доска", boardPath: "/other/board", createPath: "/other/items", patchPath: "/other/items", fields: [] };
function card(id: number, owner = "Учебный А", priority = "Срочно"): FunnelCard {
  return { id, code: `УЧ-ДОК-${id}`, title: `Учебный покупатель ${id}`, subtitle: "Учебный документ", amount: id * 10, flag: "", owner, priority, date: "", status_tag: "", progress: null, next_step: "Сверить документ", insight: "", tags: [] };
}
function snapshot(rows: { stage: string; card: FunnelCard }[]): FunnelStage[] {
  return ["draft", "ready", "shipped", "docs", "await_pay", "paid"].map(id => {
    const cards = rows.filter(row => row.stage === id).map(row => row.card);
    return { id, title: `Этап ${id}`, color: "#334455", cards, count: cards.length, sum: cards.reduce((total, item) => total + (item.amount ?? 0), 0) };
  });
}
const one = () => snapshot([{ stage: "ready", card: card(1) }]);
function openFilters() { fireEvent.click(screen.getByRole("button", { name: /^Фильтры/ })); }
function pick(label: string, value: string) { fireEvent.change(screen.getByRole("combobox", { name: label }), { target: { value } }); }
function count(shown: number, total: number) { expect(screen.getByRole("status")).toHaveTextContent(`Показано ${shown} из ${total} загруженных карточек.`); }
function kpi(label: string, value: string) { expect(within(screen.getByRole("group", { name: label })).getByText(value, { exact: true })).toBeInTheDocument(); }
function reset() { fireEvent.click(screen.getByRole("button", { name: "Сбросить отбор и поиск" })); }
function deferred() { let finish!: (value: Response) => void; const promise = new Promise<Response>(resolve => { finish = resolve; }); return { promise, finish }; }

it("399 filters: combines native Office stage owner priority and search without changing full KPI or fetching again", async () => {
  const stages = snapshot([{ stage: "ready", card: card(1) }, { stage: "ready", card: card(2, "Учебный Б") }, { stage: "draft", card: card(3) }, { stage: "ready", card: card(4, "Учебный А", "Низкий") }]);
  const fetcher = vi.fn<typeof fetch>(async () => Response.json({ stages })); vi.stubGlobal("fetch", fetcher);
  render(<OfficePage />); await screen.findByText("Учебный покупатель 1"); openFilters();
  pick("Этап", "ready"); count(3, 4); pick("Ответственный в карточке", "=Учебный А"); count(2, 4); pick("Приоритет", "=Срочно");
  fireEvent.change(screen.getByPlaceholderText("Поиск..."), { target: { value: "  ПОКУПАТЕЛЬ 1  " } }); count(1, 4);
  expect(screen.queryByText("Учебный покупатель 2")).not.toBeInTheDocument();
  expect(screen.getByText(`1 карточка · ${formatByn(10).replace(/\s/g, " ")}`)).toBeInTheDocument();
  expect(screen.getAllByText("Этап draft")).toHaveLength(1); expect(screen.getByText("Этап draft").tagName).toBe("OPTION"); kpi("Доступных документов", "4"); kpi("К подготовке", "3");
  expect(screen.getByText(/остальные показатели не пересчитываются/)).toBeInTheDocument();
  reset(); count(4, 4); expect(screen.getByPlaceholderText("Поиск...")).toHaveValue("");
  expect(fetcher).toHaveBeenCalledTimes(1); expect(fetcher).toHaveBeenCalledWith("/api/office/board", { cache: "no-store" });
});

it("399 filters: distinguishes empty exact labels from all and preserves arbitrary duplicate text values", async () => {
  vi.stubGlobal("fetch", vi.fn<typeof fetch>(async () => Response.json({ stages: snapshot([{ stage: "ready", card: card(1, "", "") }, { stage: "ready", card: card(2, "=", "Сверхсрочно") }, { stage: "ready", card: card(3, "Учебный Б", "__all__") }, { stage: "docs", card: card(4, "", "__all__") }]) })));
  render(<FunnelBoard {...generic} />); await screen.findByText("Учебный покупатель 1"); openFilters();
  pick("Ответственный в карточке", "="); count(2, 4); pick("Приоритет", "="); count(1, 4);
  expect(screen.getByText("Учебный покупатель 1")).toBeInTheDocument(); expect(screen.queryByText("Учебный покупатель 4")).not.toBeInTheDocument();
  pick("Приоритет", "=__all__"); count(1, 4); expect(screen.getByText("Учебный покупатель 4")).toBeInTheDocument();
  pick("Ответственный в карточке", "=="); pick("Приоритет", "=Сверхсрочно"); count(1, 4); expect(screen.getByText("Учебный покупатель 2")).toBeInTheDocument();
  reset(); count(4, 4);
});

it("399 filters: keeps zero matches distinct from an empty board and retains active selection when collapsed", async () => {
  vi.stubGlobal("fetch", vi.fn<typeof fetch>(async () => Response.json({ stages: one() })));
  render(<FunnelBoard {...generic} />); await screen.findByText("Учебный покупатель 1"); openFilters(); pick("Этап", "draft");
  count(0, 1); expect(screen.getByRole("status")).toHaveTextContent("Нет карточек по выбранным условиям."); expect(screen.queryByText("Доска пуста")).not.toBeInTheDocument();
  openFilters(); expect(screen.queryByRole("group", { name: "Фильтры доски" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Фильтры · 1" })).toHaveAttribute("aria-expanded", "false"); count(0, 1);
  openFilters(); expect(screen.getByRole("combobox", { name: "Этап" })).toHaveValue("draft"); reset(); count(1, 1);
});

it("399 filters: never widens missing criteria on refresh and resolves drawer and drag preview only from fresh snapshot", async () => {
  const pending = deferred(); let request = 0;
  const fetcher = vi.fn<typeof fetch>(async () => { request++; return request === 1 ? Response.json({ stages: one() }) : request === 2 ? pending.promise : Response.json({ stages: snapshot([{ stage: "docs", card: card(2, "Учебный Б", "Низкий") }]) }); }); vi.stubGlobal("fetch", fetcher);
  const view = render(<FunnelBoard {...generic} />); await screen.findByText("Учебный покупатель 1"); openFilters(); pick("Этап", "ready"); pick("Ответственный в карточке", "=Учебный А"); pick("Приоритет", "=Срочно");
  fireEvent.click(screen.getByText("Учебный покупатель 1")); fireEvent.click(screen.getByRole("button", { name: "Учебное начало перетаскивания" }));
  view.rerender(<FunnelBoard {...generic} refreshToken={1} />);
  expect(screen.queryByText("Детали · № УЧ-ДОК-1")).not.toBeInTheDocument(); expect(screen.queryByText("Учебный покупатель 1")).not.toBeInTheDocument(); expect(screen.getByTestId("filter-drag-preview")).toBeEmptyDOMElement();
  expect(screen.queryByRole("status")).not.toBeInTheDocument(); expect(screen.queryByRole("option", { name: "Учебный А" })).not.toBeInTheDocument();
  pending.finish(Response.json({ stages: snapshot([{ stage: "docs", card: { ...card(1, "Учебный Б", "Низкий"), title: "Обновлённая учебная карточка" } }]).filter(stage => stage.id !== "ready") }));
  await screen.findByText("Детали · № УЧ-ДОК-1"); count(0, 1); expect(screen.getByRole("combobox", { name: "Этап" })).toHaveValue("ready");
  expect(screen.getByRole("option", { name: "Выбранный этап отсутствует в снимке" })).toBeInTheDocument(); expect(screen.getByRole("option", { name: "Выбранный ответственный отсутствует в снимке" })).toBeInTheDocument();
  expect(within(screen.getByTestId("filter-drag-preview")).getByText("Обновлённая учебная карточка")).toBeInTheDocument(); expect(screen.queryByText("Учебный покупатель 1")).not.toBeInTheDocument();
  view.rerender(<FunnelBoard {...generic} refreshToken={2} />); await waitFor(() => count(0, 1)); expect(screen.queryByText("Детали · № УЧ-ДОК-1")).not.toBeInTheDocument(); expect(screen.getByTestId("filter-drag-preview")).toBeEmptyDOMElement();
  reset(); count(1, 1); expect(screen.getByText("Учебный покупатель 2")).toBeInTheDocument(); expect(fetcher).toHaveBeenCalledTimes(3);
});

it("399 filters: fences query selection options and previews immediately when the board path changes or fails", async () => {
  const pendingA = deferred(), pendingB = deferred(); let original = 0, other = 0;
  const fetcher = vi.fn<typeof fetch>(async input => {
    if (String(input) === "/api/other/board") return ++original === 1 ? Response.json({ stages: one() }) : pendingA.promise;
    return ++other === 1 ? pendingB.promise : other === 2 ? Response.json({}, { status: 503 }) : Response.json({ stages: snapshot([{ stage: "docs", card: card(2, "Учебный Б", "Низкий") }]) });
  }); vi.stubGlobal("fetch", fetcher);
  const view = render(<FunnelBoard {...generic} />); await screen.findByText("Учебный покупатель 1"); openFilters(); pick("Ответственный в карточке", "=Учебный А"); fireEvent.change(screen.getByPlaceholderText("Поиск..."), { target: { value: "покупатель 1" } });
  fireEvent.click(screen.getByText("Учебный покупатель 1")); fireEvent.click(screen.getByRole("button", { name: "Учебное начало перетаскивания" }));
  view.rerender(<FunnelBoard {...generic} boardPath="/next/board" />);
  expect(screen.getByPlaceholderText("Поиск...")).toHaveValue(""); expect(screen.getByRole("combobox", { name: "Ответственный в карточке" })).toHaveValue("");
  expect(screen.getByRole("combobox", { name: "Этап" })).toBeDisabled(); expect(screen.queryByRole("option", { name: "Учебный А" })).not.toBeInTheDocument(); expect(screen.queryByText("Детали · № УЧ-ДОК-1")).not.toBeInTheDocument(); expect(screen.getByTestId("filter-drag-preview")).toBeEmptyDOMElement();
  await waitFor(() => expect(other).toBe(1)); view.rerender(<FunnelBoard {...generic} />); await waitFor(() => expect(original).toBe(2));
  expect(screen.queryByText("Учебный покупатель 1")).not.toBeInTheDocument(); expect(screen.queryByText("Детали · № УЧ-ДОК-1")).not.toBeInTheDocument(); expect(screen.getByTestId("filter-drag-preview")).toBeEmptyDOMElement(); expect(screen.queryByRole("option", { name: "Учебный А" })).not.toBeInTheDocument();
  pendingB.finish(Response.json({ stages: snapshot([{ stage: "docs", card: { ...card(2), title: "Опоздавший ответ B" } }]) }));
  pendingA.finish(Response.json({ stages: snapshot([{ stage: "ready", card: { ...card(1, "Учебный В"), title: "Свежая карточка A" } }]) }));
  await screen.findByText("Детали · № УЧ-ДОК-1"); expect(screen.queryByText("Опоздавший ответ B")).not.toBeInTheDocument(); expect(within(screen.getByTestId("filter-drag-preview")).getByText("Свежая карточка A")).toBeInTheDocument();
  view.rerender(<FunnelBoard {...generic} boardPath="/next/board" />); await screen.findByRole("alert"); expect(screen.queryByRole("status")).not.toBeInTheDocument(); expect(screen.queryByText("Доска пуста")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Повторить загрузку" })); await screen.findByText("Учебный покупатель 2"); count(1, 1);
  expect(screen.queryByRole("option", { name: "Учебный А" })).not.toBeInTheDocument(); expect(screen.queryByText("Детали · № УЧ-ДОК-1")).not.toBeInTheDocument(); expect(fetcher).toHaveBeenCalledTimes(5);
});

it("399 filters: preserves Office filters and unsaved form across hidden delivery reconciliation and shows fresh data", async () => {
  let context = await shippingFixture({ associated: true }), progress = warehouseFixture(context, { state: "complete" }), currentStage = "ready";
  const fetcher = vi.fn<typeof fetch>(async (input, init) => {
    const url = String(input);
    if (url === "/api/office/board") return Response.json({ stages: snapshot([{ stage: currentStage, card: { ...card(15), title: currentStage === "ready" ? "Учебный покупатель 15" : "Обновлённый офисный документ" } }, { stage: "draft", card: card(16, "Учебный Б") }]) });
    if (url === "/api/office/docs") return Response.json([{ ...documentFixture(), stage: currentStage }]);
    if (url.endsWith("/shipping-source")) return Response.json(context);
    if (url.endsWith("/warehouse-progress/reconcile") && init?.method === "POST") { currentStage = "shipped"; context = { ...context, document_stage: "shipped" }; progress = { ...progress, document_stage: "shipped" }; return Response.json(progress); }
    if (url.endsWith("/warehouse-progress")) return Response.json(progress);
    return Response.json({}, { status: 404 });
  }); vi.stubGlobal("fetch", fetcher);
  render(<OfficePage />); await screen.findByText("Учебный покупатель 15"); openFilters(); pick("Этап", "ready"); pick("Ответственный в карточке", "=Учебный А");
  fireEvent.change(screen.getByPlaceholderText("Поиск..."), { target: { value: "УЧ-ДОК-15" } }); fireEvent.click(screen.getByRole("button", { name: "Создать документ" })); fireEvent.change(screen.getByLabelText("Описание"), { target: { value: "Учебный несохранённый черновик" } });
  fireEvent.click(screen.getByRole("button", { name: "Доставка" })); const list = await screen.findByRole("region", { name: "Выбор документа" }); fireEvent.click(within(list).getByRole("button", { name: /УЧ-ДОК-15/ }));
  fireEvent.click(await screen.findByRole("button", { name: "Сверить документ с актами" })); await waitFor(() => expect(fetcher.mock.calls.filter(([path]) => path === "/api/office/board")).toHaveLength(2));
  fireEvent.click(screen.getByRole("button", { name: "Документы" })); await waitFor(() => count(0, 2));
  expect(screen.getByLabelText("Описание")).toHaveValue("Учебный несохранённый черновик"); expect(screen.getByPlaceholderText("Поиск...")).toHaveValue("УЧ-ДОК-15"); expect(screen.getByRole("combobox", { name: "Этап" })).toHaveValue("ready"); kpi("К подготовке", "0"); kpi("Доступных документов", "2");
  reset(); fireEvent.click(screen.getByText("Обновлённый офисный документ")); expect(await screen.findByText("Детали · № УЧ-ДОК-15")).toBeInTheDocument(); expect(screen.queryByText("Учебный покупатель 15")).not.toBeInTheDocument();
  expect(fetcher.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1); expect(fetcher.mock.calls.some(([url, init]) => url === "/api/office/docs" && init?.method === "POST")).toBe(false);
});

it("399 filters: keeps movement commands bound to real stages while recomputing filtered columns", async () => {
  const fetcher = vi.fn<typeof fetch>(async (_input, init) => init?.method === "PATCH" ? Response.json({}) : Response.json({ stages: snapshot([{ stage: "ready", card: card(1) }, { stage: "docs", card: card(2, "Учебный Б") }]) })); vi.stubGlobal("fetch", fetcher);
  render(<OfficePage />); await screen.findByText("Учебный покупатель 1"); openFilters(); pick("Ответственный в карточке", "=Учебный А"); count(1, 2);
  fireEvent.click(screen.getByRole("button", { name: "Учебный перенос в docs" })); await waitFor(() => kpi("К подготовке", "0")); kpi("Сбор документов", "2"); count(1, 2);
  const calls = fetcher.mock.calls.filter(([, init]) => init?.method === "PATCH"); expect(calls).toHaveLength(1); expect(calls[0][0]).toBe("/api/office/docs/1"); expect(JSON.parse(String(calls[0][1]?.body))).toEqual({ stage: "docs" });
  expect(screen.getByText(`1 карточка · ${formatByn(10).replace(/\s/g, " ")}`)).toBeInTheDocument(); expect(screen.queryByText("Учебный покупатель 2")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Учебный неизвестный этап" })); expect(fetcher.mock.calls.filter(([, init]) => init?.method === "PATCH")).toHaveLength(1);
});

it("399 filters: supports native keyboard toggle controls and disables criteria until data is loaded", async () => {
  const user = userEvent.setup(), pending = deferred(), fetcher = vi.fn<typeof fetch>(() => pending.promise); vi.stubGlobal("fetch", fetcher);
  render(<FunnelBoard {...generic} />); const toggle = screen.getByRole("button", { name: "Фильтры" }); toggle.focus(); await user.keyboard("{Enter}");
  const panel = screen.getByRole("group", { name: "Фильтры доски" }); expect(toggle).toHaveAttribute("aria-controls", panel.id); expect(toggle).toHaveAttribute("aria-expanded", "true");
  for (const select of within(panel).getAllByRole("combobox")) expect(select).toBeDisabled(); expect(screen.queryByRole("status")).not.toBeInTheDocument();
  pending.finish(Response.json({ stages: one() })); await screen.findByText("Учебный покупатель 1"); for (const select of within(panel).getAllByRole("combobox")) expect(select).toBeEnabled();
  await user.selectOptions(screen.getByRole("combobox", { name: "Приоритет" }), "=Срочно"); toggle.focus(); await user.keyboard("{Enter}"); expect(toggle).toHaveAttribute("aria-expanded", "false"); expect(toggle).toHaveTextContent("Фильтры · 1"); count(1, 1); expect(fetcher).toHaveBeenCalledTimes(1);
});
