import { act, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { WorktimePresence } from "./worktime-presence";

afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

it("reports visible ERP presence without starting a shift and stops after unmount", async () => {
  vi.useFakeTimers();
  const visibility = vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
  const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ items: [] }) }); vi.stubGlobal("fetch", fetcher);
  const view = render(<WorktimePresence enabled />);
  await act(async () => { await vi.advanceTimersByTimeAsync(30000); });
  expect(fetcher).not.toHaveBeenCalled();
  visibility.mockReturnValue("visible");
  await act(async () => { document.dispatchEvent(new Event("visibilitychange")); });
  expect(fetcher).toHaveBeenCalledTimes(2);
  expect(fetcher.mock.calls[0][0]).toBe("/api/hr/me/worktime/presence");
  expect(fetcher.mock.calls[0][1].method).toBe("POST");
  view.unmount();
  await act(async () => { await vi.advanceTimersByTimeAsync(60000); });
  expect(fetcher).toHaveBeenCalledTimes(2);
});

it("does not send presence when the access gate denies it", async () => {
  const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
  render(<WorktimePresence enabled={false} />);
  await act(async () => { document.dispatchEvent(new Event("visibilitychange")); });
  expect(fetcher).not.toHaveBeenCalled();
});

it("shows only addressed safe in-app notices and clears them when access expires", async () => {
  vi.useFakeTimers();
  vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
  let permitted = true;
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: permitted, json: async () => ({ items: [
    { id: "overtime:4", title: "Требуется согласование", href: "/erp/hr/worktime?tab=sheet&period=2026-10" },
    { id: "unsafe", title: "Чужая ссылка", href: "https://outside.example" },
  ] }) })));
  render(<WorktimePresence enabled />);
  await act(async () => { await vi.advanceTimersByTimeAsync(1); });
  expect(screen.getByText("Требуется согласование")).toBeInTheDocument();
  expect(screen.queryByText("Чужая ссылка")).not.toBeInTheDocument();
  expect(screen.getByRole("link")).toHaveAttribute("href", "/erp/hr/worktime?tab=sheet&period=2026-10");
  permitted = false;
  await act(async () => { await vi.advanceTimersByTimeAsync(30000); });
  expect(screen.queryByLabelText("Уведомления об учёте времени")).not.toBeInTheDocument();
});
