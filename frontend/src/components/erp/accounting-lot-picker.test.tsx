import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { AccountingLotPicker } from "./accounting-lot-picker";

const props = { org:"1", date:"2026-09-01", policyId:3, account:"41.2", warehouse:"W", sku:"A", onSelect:vi.fn() };
const data = { organization_id:1, posting_date:props.date, policy_id:3, account:"41.2", warehouse:"W", sku:"A", has_more:true, lots:[{lot:"L",book_quantity:"0.000001",book_value_byn:"0.01",selectable:true,reason:null},{lot:"Later",book_quantity:null,book_value_byn:null,selectable:false,reason:"Later movements"}] };
afterEach(() => { vi.unstubAllGlobals(); vi.clearAllMocks(); });

it("loads exact stock values only on demand, disables invalid lots and selects explicitly",async () => {
  const fetcher=vi.fn().mockResolvedValue({ok:true,json:async () => data}); vi.stubGlobal("fetch",fetcher);
  render(<AccountingLotPicker {...props} />);
  expect(fetcher).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText("Поиск бухгалтерской партии"),{target:{value:"L"}});
  fireEvent.click(screen.getByText("Подобрать партию из остатков"));
  expect(await screen.findByText("0.000001 · 0.01 BYN")).toBeInTheDocument();
  expect(screen.getByText("Выбрать партию Later")).toBeDisabled();
  expect(screen.getByText("Показаны первые 100 партий. Уточните поиск.")).toBeInTheDocument();
  expect(fetcher.mock.calls[0][0]).toContain("search=L");
  fireEvent.click(screen.getByText("Выбрать партию L")); expect(props.onSelect).toHaveBeenCalledWith("L");
  fireEvent.change(screen.getByLabelText("Поиск бухгалтерской партии"),{target:{value:"Other"}});
  expect(screen.queryByText("Выбрать партию L")).not.toBeInTheDocument();
});

it("does not show another warehouse's balances",async () => {
  vi.stubGlobal("fetch",vi.fn().mockResolvedValue({ok:true,json:async () => ({...data,warehouse:"Other"})}));
  render(<AccountingLotPicker {...props} />);
  fireEvent.click(screen.getByText("Подобрать партию из остатков"));
  expect(await screen.findByRole("alert")).toHaveTextContent("другого запроса");
  expect(screen.queryByText("Выбрать партию L")).not.toBeInTheDocument();
});
