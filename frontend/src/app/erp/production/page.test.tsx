import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import ProductionPage from "./page";

vi.mock("@/components/app-shell", () => ({ AppShell: ({ children }: { children: React.ReactNode }) => <div className="flex">{children}</div> }));
vi.mock("@/lib/funnel-api", () => ({
  fetchFunnelBoard: async () => [{ id: "queued", title: "Очередь", color: "blue", count: 2, sum: 0, cards: [1, 2].map(id => ({
    id, code: `ПЗ-${id}`, title: `Сборка ${id}`, subtitle: "", flag: "", amount: null,
    priority: "", status_tag: "", owner: "", date: "", progress: null, next_step: "", insight: "", tags: [],
  })) }],
  createFunnelCard: async () => true,
  moveFunnelCard: async () => true,
}));

describe("производственные заказы", () => {
  it("два разных заказа не получают одинаковые выдуманные BOM, OEE, риски и выпуск", async () => {
    render(<ProductionPage />);
    await screen.findByText("Сборка 1");
    expect(screen.getByRole("link", { name: "Спецификации сборок" })).toHaveAttribute("href", "/erp/production/bom");
    expect(screen.queryByText("Загрузка линий (OEE)")).not.toBeInTheDocument();
    expect(screen.queryByText("Выпущено, шт")).not.toBeInTheDocument();
    for (const title of ["Сборка 1", "Сборка 2"]) {
      fireEvent.click(screen.getByText(title));
      expect(screen.getByText("Маршрут / этапы")).toBeInTheDocument();
      expect(screen.queryByText("Обеспеченность материалами (BOM)")).not.toBeInTheDocument();
      expect(screen.queryByText("BMS 16S 48V")).not.toBeInTheDocument();
      expect(screen.queryByText(/Дефицит BMS 16S — 36 шт/)).not.toBeInTheDocument();
      fireEvent.click(screen.getByRole("button", { name: /Закрыть/ }));
    }
  });
});
