import { webcrypto } from "node:crypto";

import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import OfficePage from "@/app/erp/office/page";
import { FunnelBoard } from "@/components/funnel/funnel-board";
import { formatByn, formatMoney } from "@/lib/format";
import type { FunnelCard, FunnelStage } from "@/lib/types";
import { documentFixture, shippingFixture } from "@/test/office-shipping-fixtures";
import { warehouseFixture } from "@/test/office-warehouse-fixtures";

vi.mock("@/components/app-shell", () => ({ AppShell: ({ children }: { children: React.ReactNode }) => <div>{children}</div> }));
vi.mock("@dnd-kit/core", () => ({
  DndContext: ({ children, onDragStart }: { children: React.ReactNode; onDragStart: (e: { active: { id: number } }) => void }) => <div><button data-testid="synthetic-drag-start" onClick={() => onDragStart({ active: { id: 1 } })}>Учебное начало перетаскивания</button>{children}</div>,
  DragOverlay: ({ children }: { children: React.ReactNode }) => <div data-testid="synthetic-drag-overlay">{children}</div>,
  PointerSensor: class {}, useSensor: () => ({}), useSensors: () => [],
  useDraggable: () => ({ attributes: {}, listeners: {}, setNodeRef: () => {}, isDragging: false }),
  useDroppable: () => ({ setNodeRef: () => {}, isOver: false }),
}));

beforeEach(() => { vi.stubGlobal("crypto", webcrypto); sessionStorage.clear(); });
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });
const stageIds = ["draft", "ready", "shipped", "docs", "await_pay", "paid"];
function card(id: number, amount = 100): FunnelCard {
  return { id, code: `УЧ-ДОК-${id}`, title: `Учебный покупатель ${id}`, subtitle: "Документ по сделке", amount, flag: "", priority: "Обычный", status_tag: "", owner: "Учебный сотрудник", date: "", progress: null, next_step: "Сверить документ", insight: "", tags: [] };
}
function snapshot(rows: { stage: string; card: FunnelCard }[] = []): FunnelStage[] {
  return stageIds.map(id => { const cards = rows.filter(row => row.stage === id).map(row => row.card); return { id, title: `Этап ${id}`, color: "#334455", cards, count: cards.length, sum: cards.reduce((total, item) => total + (item.amount ?? 0), 0) }; });
}
function kpi(label: string, value: string) { expect(within(screen.getByRole("group", { name: label })).getByText(value, { exact: true })).toBeInTheDocument(); }
const genericProps = { title: "Прежняя доска", boardPath: "/other/board", createPath: "/other/items", patchPath: "/other/items", fields: [] };

it("replaces Office demo extras with counts from the single authorized snapshot and BYN document amounts", async () => {
  const data = snapshot(["draft", "ready", "docs", "await_pay", "paid"].map((stage, i) => ({ stage, card: card(i + 1, (i + 1) * 100) })));
  const fetcher = vi.fn<typeof fetch>(async () => Response.json({ stages: data })); vi.stubGlobal("fetch", fetcher);
  render(<OfficePage />); await screen.findByRole("group", { name: "Доступных документов" });
  kpi("Доступных документов", "5"); kpi("Черновики", "1"); kpi("К подготовке", "1"); kpi("Сбор документов", "1"); kpi("Ожидание оплаты", "1");
  expect(screen.getByText(/без отбора по датам/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Создать документ" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Новая сделка" })).not.toBeInTheDocument();
  for (const text of [/Сумма к получению/, /Сумма собрана/, /01.05 – 31.05.2024/, /МеталлПром/, /ХимПром/, /Конверсия/, /Итоги по воронке/]) expect(screen.queryByText(text)).not.toBeInTheDocument();
  expect(screen.getAllByText(formatByn(100), { exact: true }).length).toBeGreaterThan(0);
  expect(document.body.textContent).not.toContain("₽");
  expect(document.querySelector('[style*="undefined%"]')).toBeNull();
  expect(fetcher).toHaveBeenCalledTimes(1); expect(fetcher).toHaveBeenCalledWith("/api/office/board", { cache: "no-store" });
});

it("does not display zero KPI facts while the scoped snapshot is still loading", async () => {
  let finish: ((response: Response) => void) | undefined;
  vi.stubGlobal("fetch", vi.fn<typeof fetch>(() => new Promise<Response>(resolve => { finish = resolve; })));
  render(<OfficePage />); await waitFor(() => expect(finish).toBeDefined());
  expect(screen.queryByRole("group", { name: "Доступных документов" })).not.toBeInTheDocument();
  finish!(Response.json({ stages: snapshot([{ stage: "ready", card: card(1) }]) }));
  await screen.findByRole("group", { name: "Доступных документов" }); kpi("Доступных документов", "1");
});

it("keeps a failed board request distinct from an empty successful snapshot", async () => {
  vi.stubGlobal("fetch", vi.fn<typeof fetch>(async () => Response.json({}, { status: 503 })));
  render(<OfficePage />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Не удалось загрузить доску");
  expect(screen.queryByRole("group", { name: "Доступных документов" })).not.toBeInTheDocument();
  expect(screen.queryByText("Доска пуста")).not.toBeInTheDocument();
});

it("shows true zero counts only after a successful empty scoped snapshot", async () => {
  vi.stubGlobal("fetch", vi.fn<typeof fetch>(async () => Response.json({ stages: snapshot() })));
  render(<OfficePage />); await screen.findByRole("group", { name: "Доступных документов" });
  for (const label of ["Доступных документов", "Черновики", "К подготовке", "Сбор документов", "Ожидание оплаты"]) kpi(label, "0");
  expect(screen.queryByRole("alert")).not.toBeInTheDocument(); expect(screen.getByText(/в вашем доступе/)).toBeInTheDocument();
});

it("uses BYN for the Office card, column, drawer and drag preview without changing numeric amounts", async () => {
  const amount = 1200.25, shown = formatByn(amount).replace(/\s/g, " ");
  vi.stubGlobal("fetch", vi.fn<typeof fetch>(async () => Response.json({ stages: snapshot([{ stage: "ready", card: card(1, amount) }]) })));
  render(<OfficePage />); await screen.findByText("Учебный покупатель 1");
  expect(screen.getAllByText(shown, { exact: true })).toHaveLength(1);
  expect(screen.getByText(`1 карточка · ${shown}`, { exact: true })).toBeInTheDocument();
  fireEvent.click(screen.getByText("Учебный покупатель 1"));
  expect(await screen.findByText("Детали · № УЧ-ДОК-1")).toBeInTheDocument(); expect(screen.getAllByText(shown, { exact: true })).toHaveLength(2);
  fireEvent.click(screen.getByRole("button", { name: "Закрыть карточку" })); fireEvent.click(screen.getByTestId("synthetic-drag-start"));
  expect(within(screen.getByTestId("synthetic-drag-overlay")).getByText(shown, { exact: true })).toBeInTheDocument();
  expect(document.body.textContent).not.toContain("₽");
});

it("keeps the existing generic currency and static KPI/summary contracts unless BYN is explicitly selected", async () => {
  const amount = 990.5, fetcher = vi.fn<typeof fetch>(async () => Response.json({ stages: snapshot([{ stage: "ready", card: card(1, amount) }]) })); vi.stubGlobal("fetch", fetcher);
  const props = { ...genericProps, kpis: [{ label: "Прежний показатель", value: "7", target: "10", note: "Прежняя цель", percent: 70, tone: "blue" as const }], summary: [{ label: "Прежний итог", value: "Проверенное значение" }] };
  const view = render(<FunnelBoard {...props} />); await screen.findByText("Учебный покупатель 1");
  expect(screen.getByText(formatMoney(amount), { exact: true })).toBeInTheDocument(); expect(screen.getByText("Проверенное значение")).toBeInTheDocument();
  expect(screen.getByRole("group", { name: "Прежний показатель" })).toHaveTextContent("7 / 10"); expect(document.querySelector('[style="width: 70%;"]')).not.toBeNull();
  const search = screen.getByPlaceholderText("Поиск..."); fireEvent.change(search, { target: { value: "покупатель" } });
  fireEvent.click(screen.getByText("Учебный покупатель 1")); const selected = await screen.findByText("Детали · № УЧ-ДОК-1");
  view.rerender(<FunnelBoard {...props} currency="BYN" />);
  expect(screen.getByText("Детали · № УЧ-ДОК-1")).toBe(selected); expect(search).toHaveValue("покупатель");
  expect(screen.getAllByText(formatByn(amount), { exact: true })).toHaveLength(2); expect(fetcher).toHaveBeenCalledTimes(1);
});

it("updates default computed amount summaries when the opt-in currency changes without refetching", async () => {
  const amount = 73.25, fetcher = vi.fn<typeof fetch>(async () => Response.json({ stages: snapshot([{ stage: "ready", card: card(1, amount) }]) })); vi.stubGlobal("fetch", fetcher);
  const view = render(<FunnelBoard {...genericProps} />); await screen.findByText("Итоги по воронке");
  expect(screen.getAllByText(formatMoney(amount), { exact: true })).toHaveLength(2);
  view.rerender(<FunnelBoard {...genericProps} currency="BYN" />);
  expect(screen.getAllByText(formatByn(amount), { exact: true })).toHaveLength(2); expect(fetcher).toHaveBeenCalledTimes(1);
});

it("refreshes real Office KPI counts after addressed warehouse reconciliation using the existing board reload", async () => {
  let context = await shippingFixture({ associated: true }), progress = warehouseFixture(context, { state: "complete" });
  let currentStage = "ready";
  const fetcher = vi.fn<typeof fetch>(async (input, init) => {
    const url = String(input);
    if (url === "/api/office/board") return Response.json({ stages: snapshot([{ stage: currentStage, card: card(15) }]) });
    if (url === "/api/office/docs") return Response.json([{ ...documentFixture(), stage: currentStage }]);
    if (url.endsWith("/shipping-source")) return Response.json(context);
    if (url.endsWith("/warehouse-progress/reconcile") && init?.method === "POST") { currentStage = "shipped"; context = { ...context, document_stage: "shipped" }; progress = { ...progress, document_stage: "shipped" }; return Response.json(progress); }
    if (url.endsWith("/warehouse-progress")) return Response.json(progress);
    return Response.json({}, { status: 404 });
  }); vi.stubGlobal("fetch", fetcher);
  render(<OfficePage />); await screen.findByRole("group", { name: "К подготовке" }); kpi("К подготовке", "1");
  fireEvent.click(screen.getByRole("button", { name: "Доставка" }));
  const list = await screen.findByRole("region", { name: "Выбор документа" }); fireEvent.click(within(list).getByRole("button", { name: /УЧ-ДОК-15/ }));
  fireEvent.click(await screen.findByRole("button", { name: "Сверить документ с актами" }));
  await waitFor(() => expect(fetcher.mock.calls.filter(([url]) => String(url) === "/api/office/board")).toHaveLength(2));
  fireEvent.click(screen.getByRole("button", { name: "Документы" })); await waitFor(() => kpi("К подготовке", "0")); kpi("Доступных документов", "1");
  expect(fetcher.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1);
});
