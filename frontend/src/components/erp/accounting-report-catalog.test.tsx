import { fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { AccountingReportCatalog, type ReportFavoriteState } from "./accounting-report-catalog";

function Catalog({ onOpen = vi.fn(), reportReady = true, shown = true }: { onOpen?: (tab: string) => void; reportReady?: boolean; shown?: boolean }) {
  const [favoriteState, setFavoriteState] = useState<ReportFavoriteState>({ ids: [], loaded: false });
  return shown ? <AccountingReportCatalog onOpen={onOpen} reportReady={reportReady} favoriteState={favoriteState} setFavoriteState={setFavoriteState} /> : null;
}

const stored = new Map<string, string>();
beforeEach(() => {
  stored.clear();
  vi.stubGlobal("localStorage", {
    getItem: (key: string) => stored.get(key) ?? null,
    setItem: (key: string, value: string) => { stored.set(key, value); },
  });
});
afterEach(() => vi.unstubAllGlobals());

it("uses real ERP destinations and marks unfinished submission forms unavailable", () => {
  const onOpen = vi.fn();
  render(<Catalog onOpen={onOpen} />);
  expect(screen.getByRole("navigation", { name: "Группы отчётов" }).querySelectorAll("button")).toHaveLength(4);
  const trial = screen.getByText("ОСВ", { exact: true }).closest("article")!;
  expect(within(trial).getByRole("link", { name: "Открыть" })).toHaveAttribute("href", "#accounting-trial-balance");
  fireEvent.click(screen.getByRole("button", { name: "Товары и расчёты" }));
  const settlement = screen.getByText("Оплаты и зачёты счетов").closest("article")!;
  fireEvent.click(within(settlement).getByRole("button", { name: "Открыть" }));
  expect(onOpen).toHaveBeenCalledWith("invoice-settlements");
  fireEvent.click(screen.getByRole("button", { name: "Для сдачи" }));
  const vat = screen.getByText("Декларация по НДС").closest("article")!;
  expect(within(vat).getByText("Пока недоступен")).toBeInTheDocument();
  expect(within(vat).queryByRole("button", { name: "Открыть" })).not.toBeInTheDocument();
  expect(within(vat).queryByRole("link", { name: "Открыть" })).not.toBeInTheDocument();
});

it("searches report titles and restores browser favorites", async () => {
  const view = render(<Catalog />);
  fireEvent.change(screen.getByRole("textbox", { name: "Поиск отчёта" }), { target: { value: "баланс" } });
  expect(await screen.findByText("Баланс")).toBeInTheDocument();
  expect(screen.queryByText("Журнал проводок")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "В избранное: Баланс" }));
  expect(JSON.parse(localStorage.getItem("accountant-report-favorites-v1")!)).toEqual(["balance"]);
  view.unmount();
  render(<Catalog />);
  fireEvent.click(screen.getByRole("button", { name: "Избранное" }));
  expect(await screen.findByText("Баланс")).toBeInTheDocument();
});

it("keeps favorite choices usable when browser storage is unavailable", () => {
  vi.stubGlobal("localStorage", { getItem: () => { throw new Error("disabled"); }, setItem: () => { throw new Error("disabled"); } });
  const view = render(<Catalog />);
  fireEvent.click(screen.getByRole("button", { name: "В избранное: Журнал проводок" }));
  view.rerender(<Catalog shown={false} />);
  view.rerender(<Catalog />);
  fireEvent.click(screen.getByRole("button", { name: "Избранное" }));
  expect(screen.getByText("Журнал проводок")).toBeInTheDocument();
});

it("does not link to an absent book report while it is loading", () => {
  render(<Catalog reportReady={false} />);
  const trial = screen.getByText("ОСВ", { exact: true }).closest("article")!;
  expect(within(trial).getByText("Дождитесь загрузки книги")).toBeInTheDocument();
  expect(within(trial).queryByRole("link", { name: "Открыть" })).not.toBeInTheDocument();
});
