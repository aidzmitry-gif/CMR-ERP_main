import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AnalyticsView } from "@/components/erp/analytics-view";

afterEach(() => vi.restoreAllMocks());

describe("AnalyticsView", () => {
  it("рендерит карточки модулей и подгружает количества", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => [1, 2, 3] }));
    render(<AnalyticsView />);
    expect(screen.getByText("Аналитика")).toBeInTheDocument();
    expect(screen.getByText("Сделки")).toBeInTheDocument();
    expect(screen.getByText("Платежи")).toBeInTheDocument();
    await waitFor(() => expect(screen.getAllByText("3").length).toBeGreaterThan(0));
  });

  it("переживает ошибку загрузки (показывает …)", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("down")));
    render(<AnalyticsView />);
    expect(screen.getByText("Аналитика")).toBeInTheDocument();
    expect(screen.getAllByText("…").length).toBeGreaterThan(0);
  });
});
