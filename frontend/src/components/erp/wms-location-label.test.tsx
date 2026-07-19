import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// Мокаем ТОЛЬКО сетевой fetchLocations; чистые хелперы (locationLabel) оставляем настоящими.
vi.mock("@/lib/wms-ops", async (importActual) => {
  const actual = await importActual<typeof import("@/lib/wms-ops")>();
  return {
    ...actual,
    fetchLocations: vi.fn().mockResolvedValue([]),
  };
});

import { WmsLocationLabel } from "@/components/erp/wms-location-label";
import * as wms from "@/lib/wms-ops";
import type { WmsLocation } from "@/lib/wms-ops";

const asMock = (fn: unknown) => fn as ReturnType<typeof vi.fn>;

const locations: WmsLocation[] = [
  { id: 10, warehouse: "Главный", zone: "A", code: "A-01", title: "Верхняя полка", is_active: true },
  { id: 11, warehouse: "Второй", zone: "", code: "ЯЧ-99", title: "", is_active: true },
];

beforeEach(() => {
  vi.clearAllMocks();
  asMock(wms.fetchLocations).mockResolvedValue(locations);
});

describe("WmsLocationLabel", () => {
  it("показывает индикатор загрузки до ответа fetchLocations", () => {
    asMock(wms.fetchLocations).mockReturnValue(new Promise(() => {}));
    render(<WmsLocationLabel id={10} />);
    expect(screen.getByText("Загрузка…")).toBeInTheDocument();
  });

  it("показывает «Ячейка не найдена», если id отсутствует в списке", async () => {
    render(<WmsLocationLabel id={999} />);
    await waitFor(() => expect(screen.getByText("Ячейка не найдена")).toBeInTheDocument());
    expect(screen.queryByText("Загрузка…")).not.toBeInTheDocument();
  });

  it("рендерит SVG-штрихкод для ASCII-кода и подпись «зона · код»", async () => {
    render(<WmsLocationLabel id={10} />);
    await waitFor(() => expect(screen.getByText("Главный")).toBeInTheDocument());
    expect(screen.getByText("A · A-01")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Штрихкод A-01" })).toBeInTheDocument();
    expect(screen.getByText("A-01")).toBeInTheDocument();
    expect(screen.getByText("Верхняя полка")).toBeInTheDocument();
  });

  it("не рендерит title, если он пустой", async () => {
    render(<WmsLocationLabel id={11} />);
    await waitFor(() => expect(screen.getByText("Второй")).toBeInTheDocument());
    expect(screen.queryByText("Верхняя полка")).not.toBeInTheDocument();
  });

  it("показывает читаемый fallback вместо штрихкода для некодируемого в Code 39 значения", async () => {
    render(<WmsLocationLabel id={11} />);
    await waitFor(() => expect(screen.getByText("Второй")).toBeInTheDocument());
    expect(screen.queryByRole("img", { name: /Штрихкод/ })).not.toBeInTheDocument();
    // код без зоны → сама подпись ячейки равна коду
    expect(screen.getAllByText("ЯЧ-99").length).toBeGreaterThanOrEqual(2);
  });

  it("клик по кнопке «Печать» вызывает window.print", async () => {
    const printSpy = vi.spyOn(window, "print").mockImplementation(() => {});
    render(<WmsLocationLabel id={10} />);
    await waitFor(() => expect(screen.getByText("Главный")).toBeInTheDocument());
    screen.getByRole("button", { name: /Печать/ }).click();
    expect(printSpy).toHaveBeenCalledTimes(1);
  });

  it("перезапрашивает локации при смене id", async () => {
    const { rerender } = render(<WmsLocationLabel id={10} />);
    await waitFor(() => expect(screen.getByText("Главный")).toBeInTheDocument());
    rerender(<WmsLocationLabel id={11} />);
    await waitFor(() => expect(screen.getByText("Второй")).toBeInTheDocument());
    expect(wms.fetchLocations).toHaveBeenCalledTimes(2);
  });
});
