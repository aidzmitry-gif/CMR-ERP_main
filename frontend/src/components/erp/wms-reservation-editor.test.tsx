import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { WmsReservationEditor } from "./wms-reservation-editor";
afterEach(() => vi.unstubAllGlobals());
const initial = { source: "doc:1", version: 2, sku_code: "A", warehouse: "Own", qty: "1.25" };
it("posts zero remaining quantity as the next version without changing identity", async () => {
  const fetcher = vi.fn().mockResolvedValue({ ok: true }); vi.stubGlobal("fetch", fetcher);
  const saved = vi.fn();
  render(<WmsReservationEditor organizationId={7} initial={initial} onBusy={vi.fn()} onSaved={saved} onCancel={vi.fn()} />);
  expect(screen.getByLabelText("Исходная строка")).toBeDisabled();
  fireEvent.change(screen.getByLabelText("Количество резерва"), { target: { value: "0" } });
  fireEvent.change(screen.getByLabelText("Основание изменения"), { target: { value: "Released" } });
  fireEvent.click(screen.getByRole("button", { name: "Записать версию" }));
  await waitFor(() => expect(saved).toHaveBeenCalledTimes(1));
  expect(JSON.parse(fetcher.mock.calls[0][1].body)).toEqual({ organization_id: 7, source: "doc:1", version: 3, sku_code: "A", warehouse: "Own", qty: "0", evidence: "Released" });
});
it("retains exact decimal input after conflict and does not report success", async () => {
  const fetcher = vi.fn().mockResolvedValue({ ok: false, status: 409 }); vi.stubGlobal("fetch", fetcher);
  const saved = vi.fn();
  render(<WmsReservationEditor organizationId={7} initial={initial} onBusy={vi.fn()} onSaved={saved} onCancel={vi.fn()} />);
  fireEvent.change(screen.getByLabelText("Количество резерва"), { target: { value: "999999999999,99" } });
  fireEvent.change(screen.getByLabelText("Основание изменения"), { target: { value: "Reason" } });
  fireEvent.click(screen.getByRole("button", { name: "Записать версию" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Версия уже существует");
  expect(screen.getByLabelText("Количество резерва")).toHaveValue("999999999999,99");
  expect(JSON.parse(fetcher.mock.calls[0][1].body).qty).toBe("999999999999.99");
  expect(saved).not.toHaveBeenCalled();
});
it("rejects malformed quantities before requesting a write", () => {
  const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
  render(<WmsReservationEditor organizationId={7} initial={null} onBusy={vi.fn()} onSaved={vi.fn()} onCancel={vi.fn()} />);
  for (const qty of ["0", "NaN", "1.001", "-1", ""]) {
    fireEvent.change(screen.getByLabelText("Количество резерва"), { target: { value: qty } });
    fireEvent.click(screen.getByRole("button", { name: "Записать версию" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Первый резерв должен быть больше нуля");
  }
  expect(fetcher).not.toHaveBeenCalled();
});
it("blocks invoice sources before sending a manual write", () => {
  const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
  render(<WmsReservationEditor organizationId={7} initial={null} onBusy={vi.fn()} onSaved={vi.fn()} onCancel={vi.fn()} />);
  fireEvent.change(screen.getByLabelText("Исходная строка"), { target: { value: "invoice:22:1:warehouse" } });
  fireEvent.click(screen.getByRole("button", { name: "Записать версию" }));
  expect(screen.getByRole("alert")).toHaveTextContent("Ручная запись запрещена");
  expect(fetcher).not.toHaveBeenCalled();
});
