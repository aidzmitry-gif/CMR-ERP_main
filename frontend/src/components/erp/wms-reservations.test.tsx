import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { WmsReservations } from "./wms-reservations";

afterEach(() => { vi.unstubAllGlobals(); });
const companies = [{ id: 1, name: "One", unp: "1" }, { id: 2, name: "Two", unp: "2" }];
const row = { id: 1, organization_id: 1, source: "doc:1/line:1", version: 2, sku_code: "SKU-A", warehouse: "Own", qty: "1.25", evidence: "Partial release evidence", actor: "accountant" };
const ok = (data: unknown) => ({ ok: true, json: async () => data });

it("requires explicit company, shows exact quantities and source history", async () => {
  const fetcher = vi.fn(async (url: string) => ok(url.includes("receipt-organizations") ? companies : url.includes("/summary?") ? [{ ...row, source_count: 1 }] : [row]));
  vi.stubGlobal("fetch", fetcher);
  render(<WmsReservations />);
  await screen.findByRole("option", { name: "One · 1" });
  expect(fetcher).toHaveBeenCalledTimes(1);
  fireEvent.change(screen.getByLabelText("Юрлицо"), { target: { value: "1" } });
  expect(await screen.findByText("1.25")).toBeInTheDocument();
  expect(await screen.findByText("SKU-A · Own · Резерв 1.25 · Исходных строк: 1")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "История doc:1/line:1" }));
  expect(await screen.findByText("Partial release evidence")).toBeInTheDocument();
  expect(fetcher).toHaveBeenCalledWith("/api/wms/reservations/history?organization_id=1&source=doc%3A1%2Fline%3A1", expect.anything());
});

it("ignores late company responses and reports failures with retry", async () => {
  let resolveFirst!: (value: unknown) => void;
  let failSecond = true;
  vi.stubGlobal("fetch", vi.fn((url: string) => {
    if (url.includes("/summary?")) return Promise.resolve(ok([]));
    if (url.includes("receipt-organizations")) return Promise.resolve(ok(companies));
    if (url.endsWith("=1")) return new Promise((resolve) => { resolveFirst = resolve; });
    return Promise.resolve(failSecond ? { ok: false } : ok([]));
  }));
  render(<WmsReservations />);
  await screen.findByRole("option", { name: "One · 1" });
  fireEvent.change(screen.getByLabelText("Юрлицо"), { target: { value: "1" } });
  fireEvent.change(screen.getByLabelText("Юрлицо"), { target: { value: "2" } });
  expect(await screen.findByRole("alert")).toHaveTextContent("Не удалось загрузить резервы");
  await act(async () => { resolveFirst(ok([row])); });
  expect(screen.queryByText("SKU-A")).not.toBeInTheDocument();
  failSecond = false;
  fireEvent.click(screen.getByRole("button", { name: "Обновить" }));
  await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
  expect(await screen.findByText("В этом регистре резервов нет.")).toBeInTheDocument();
});
it("links invoice reservations to their original and offers editing only for manual rows", async () => {
  const invoice = { ...row, id: 2, source: "invoice:22:1:warehouse", version: 1 };
  vi.stubGlobal("fetch", vi.fn(async (url: string) => ok(url.includes("receipt-organizations") ? companies : url.includes("/summary?") ? [] : [row, invoice])));
  render(<WmsReservations />);
  await screen.findByRole("option", { name: "One · 1" });
  fireEvent.change(screen.getByLabelText("Юрлицо"), { target: { value: "1" } });
  expect(await screen.findByRole("link", { name: "Оригинал счёта" })).toHaveAttribute("href", "/api/sales/documents/22/render");
  expect(screen.queryByRole("button", { name: "Изменить invoice:22:1:warehouse" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "История invoice:22:1:warehouse" })).toBeEnabled();
  expect(screen.getByRole("button", { name: "Изменить doc:1/line:1" })).toBeEnabled();
});
