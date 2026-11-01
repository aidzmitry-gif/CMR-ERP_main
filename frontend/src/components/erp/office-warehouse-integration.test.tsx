import { webcrypto } from "node:crypto";

import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { OfficeView } from "@/components/erp/office-view";
import { FunnelBoard } from "@/components/funnel/funnel-board";
import { documentFixture, shippingFixture } from "@/test/office-shipping-fixtures";
import { warehouseFixture } from "@/test/office-warehouse-fixtures";

beforeEach(() => { vi.stubGlobal("crypto", webcrypto); sessionStorage.clear(); });
afterEach(() => vi.unstubAllGlobals());
const boardProps = { title: "Учебная воронка", boardPath: "/office/board", createPath: "/office/docs", patchPath: "/office/docs", fields: [] };

it("refreshes the Office list and native board from server facts after reconcile while preserving selection and board input", async () => {
  let context = await shippingFixture({ associated: true }); let data = warehouseFixture(context);
  const fetcher = vi.fn<typeof fetch>(async (input, init) => {
    const url = String(input);
    if (url === "/api/office/board") return Response.json({ stages: [] });
    if (url === "/api/office/docs") return Response.json([{ ...documentFixture(), stage: data.document_stage }]);
    if (url.endsWith("/shipping-source")) return Response.json(context);
    if (url.endsWith("/warehouse-progress/reconcile") && init?.method === "POST") {
      context = { ...context, document_stage: "shipped" }; data = warehouseFixture(context, { state: "complete" });
      return Response.json(data);
    }
    if (url.endsWith("/warehouse-progress")) return Response.json(data);
    return Response.json({}, { status: 404 });
  }); vi.stubGlobal("fetch", fetcher);
  render(<OfficeView board={<FunnelBoard {...boardProps} />} />);
  const search = await screen.findByPlaceholderText("Поиск...");
  fireEvent.change(search, { target: { value: "Сохранённый фильтр" } });
  fireEvent.click(screen.getByRole("button", { name: "Доставка" }));
  const list = await screen.findByRole("region", { name: "Выбор документа" });
  fireEvent.click(within(list).getByRole("button", { name: /УЧ-ДОК-15/ }));
  fireEvent.click(await screen.findByRole("button", { name: "Сверить документ с актами" }));
  await waitFor(() => expect(fetcher.mock.calls.filter(([url]) => String(url) === "/api/office/board")).toHaveLength(2));
  await waitFor(() => expect(within(list).getByText("Отгрузка оформлена")).toBeInTheDocument());
  expect(within(list).getByRole("button", { name: /УЧ-ДОК-15/ })).toHaveAttribute("aria-pressed", "true");
  fireEvent.click(screen.getByRole("button", { name: "Документы" }));
  expect(screen.getByPlaceholderText("Поиск...")).toBe(search);
  expect(search).toHaveValue("Сохранённый фильтр");
  expect(fetcher.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1);
});

it("retains the existing default board load behavior and refreshes an explicit token without remounting its input", async () => {
  const fetcher = vi.fn<typeof fetch>(async () => Response.json({ stages: [] })); vi.stubGlobal("fetch", fetcher);
  const view = render(<FunnelBoard {...boardProps} />);
  const search = await screen.findByPlaceholderText("Поиск...");
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
  fireEvent.change(search, { target: { value: "Черновик фильтра" } });
  view.rerender(<FunnelBoard {...boardProps} title="Другое название" />);
  expect(fetcher).toHaveBeenCalledTimes(1);
  view.rerender(<FunnelBoard {...boardProps} refreshToken={1} />);
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2));
  expect(screen.getByPlaceholderText("Поиск...")).toBe(search);
  expect(search).toHaveValue("Черновик фильтра");
});
