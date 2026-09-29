import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { AccountingAssemblyEstimate } from "./accounting-assembly-estimate";

vi.mock("@/lib/expense-control-api", () => ({
  context: vi.fn().mockResolvedValue({ catalog: { revision: 1,
    groups: [{ id: 3, code: "production", title: "Производство", active: true }],
    articles: [{ id: 7, group_id: 3, code: "assembly_labor", title: "Оплата сборки", active: true }] } }),
}));

afterEach(() => vi.unstubAllGlobals());
const result = { organization_id: 1, status: "estimated", input: {}, total_cost_byn: "177.00", unit_cost_byn: "17.700000",
  revenue_net_byn: "300.00", gross_profit_byn: "123.00", margin_percent: "41.00", missing_price_lines: [],
  known_components_byn: "135.00", batch_costs_byn: "42.00", cost_article_snapshots: {}, lines: [] };

it("sends decimal strings and clears a stale estimate after editing", async () => {
  const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => result });
  vi.stubGlobal("fetch", fetcher);
  render(<AccountingAssemblyEstimate org="1" date="2026-09-28" />);
  fireEvent.change(screen.getByLabelText("Цена 1"), { target: { value: "2,5" } });
  fireEvent.click(screen.getByText("Рассчитать"));
  expect(await screen.findByText("123.00 BYN")).toBeInTheDocument();
  const payload = JSON.parse(fetcher.mock.calls[0][1].body);
  expect(payload.components[0].unit_cost_byn).toBe("2.5");
  expect(payload.quantity).toBe("1");
  expect(payload.sale_unit_net_byn).toBeNull();
  fireEvent.change(screen.getByLabelText("Количество изделий"), { target: { value: "2" } });
  expect(screen.queryByText("123.00 BYN")).not.toBeInTheDocument();
});

it("shows incomplete costs as unknown rather than a zero-cost profit", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ...result, status: "incomplete",
    missing_price_lines: [1], total_cost_byn: null, unit_cost_byn: null, gross_profit_byn: null, margin_percent: null }) }));
  render(<AccountingAssemblyEstimate org="1" date="2026-09-28" />);
  fireEvent.click(screen.getByText("Рассчитать"));
  expect(await screen.findByRole("alert")).toHaveTextContent("Не указаны цены в строках: 1");
  expect(screen.queryByText("123.00 BYN")).not.toBeInTheDocument();
  expect(screen.getAllByText("Не рассчитано")).toHaveLength(3);
});

it("ignores an estimate from a previous organization", async () => {
  let resolve!: (value: unknown) => void;
  vi.stubGlobal("fetch", vi.fn(() => new Promise(done => { resolve = done; })));
  const view = render(<AccountingAssemblyEstimate org="1" date="2026-09-28" />);
  fireEvent.click(screen.getByText("Рассчитать"));
  view.rerender(<AccountingAssemblyEstimate org="2" date="2026-09-28" />);
  await act(async () => resolve({ ok: true, json: async () => result }));
  expect(screen.queryByText("123.00 BYN")).not.toBeInTheDocument();
  expect(screen.getByText("Рассчитать")).toBeEnabled();
});

it("imports BOM norms but requires explicit component prices", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce({ ok: true, json: async () => [{ id: 4, product: "Pack", version: "v2" }] })
    .mockResolvedValueOnce({ ok: true, json: async () => ({ id: 4, product: "Pack", version: "v2", status: "approved",
      items: [{ component: "Cell", unit: "шт", norm_qty: 4 }] }) }));
  render(<AccountingAssemblyEstimate org="1" date="2026-09-28" />);
  fireEvent.click(screen.getByText("Загрузить спецификации"));
  fireEvent.change(await screen.findByLabelText("Спецификация BOM"), { target: { value: "4" } });
  fireEvent.click(screen.getByText("Взять состав (заменить строки)"));
  await waitFor(() => expect(screen.getByLabelText("Комплектующее 1")).toHaveValue("Cell"));
  expect(screen.getByLabelText("Норма 1")).toHaveValue("4");
  expect(screen.getByLabelText("Цена 1")).toHaveValue("");
});

it("binds a batch cost to an active article in the selected organization", async () => {
  const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ...result,
    cost_article_snapshots: { labor_byn: { id: 7, code: "assembly_labor", title: "Оплата сборки", group_title: "Производство" } } }) });
  vi.stubGlobal("fetch", fetcher);
  render(<AccountingAssemblyEstimate org="1" date="2026-09-28" />);
  fireEvent.change(await screen.findByLabelText("Статья расходов: Оплата сборки"), { target: { value: "7" } });
  fireEvent.click(screen.getByText("Рассчитать"));
  expect(await screen.findByText(/Производство \/ Оплата сборки \(assembly_labor\)/)).toBeInTheDocument();
  const payload = JSON.parse(fetcher.mock.calls[0][1].body);
  expect(payload.batch_cost_articles).toEqual([{ category: "labor_byn", article_id: 7 }]);
});
