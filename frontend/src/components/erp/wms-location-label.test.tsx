import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// Мокаем ТОЛЬКО сетевой fetchLocation; чистые хелперы (locationLabel) оставляем настоящими.
vi.mock("@/lib/wms-ops", async (importActual) => {
  const actual = await importActual<typeof import("@/lib/wms-ops")>();
  return {
    ...actual,
    fetchLocation: vi.fn(),
    fetchLocationOrganizations: vi.fn(),
  };
});

import { WmsLocationLabel } from "@/components/erp/wms-location-label";
import * as wms from "@/lib/wms-ops";
import type { WmsLocation } from "@/lib/wms-ops";

const asMock = (fn: unknown) => fn as ReturnType<typeof vi.fn>;

const locations: WmsLocation[] = [
  { id: 10, organization_id: 7, warehouse: "Главный", zone: "A", code: "A-01", title: "Верхняя полка", is_active: true },
  { id: 11, organization_id: 7, warehouse: "Второй", zone: "", code: "ЯЧ-99", title: "", is_active: true },
];

beforeEach(() => {
  vi.clearAllMocks();
  asMock(wms.fetchLocation).mockImplementation(async (id: number) => locations.find((row) => row.id === id) ?? null);
  asMock(wms.fetchLocationOrganizations).mockResolvedValue([{ id: 7, name: "Учебная компания" }]);
});

describe("WmsLocationLabel", () => {
  it("показывает индикатор загрузки до ответа fetchLocation", () => {
    asMock(wms.fetchLocation).mockReturnValue(new Promise(() => {}));
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
    expect(screen.getByText("Учебная компания")).toBeInTheDocument();
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
    expect(screen.queryByText("Главный")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Печать" })).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("Второй")).toBeInTheDocument());
    expect(wms.fetchLocation).toHaveBeenCalledTimes(2);
  });
});


describe("label access and stale responses", () => {
  it("does not turn access failure into missing or expose a print action", async () => {
    asMock(wms.fetchLocation).mockRejectedValue(new wms.LocationRequestError("Нет доступа", 403));
    render(<WmsLocationLabel id={10} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Нет доступа");
    expect(screen.queryByText("Ячейка не найдена")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Печать" })).not.toBeInTheDocument();
  });
  it("hides the label when its company cannot be confirmed", async () => {
    asMock(wms.fetchLocationOrganizations).mockResolvedValue([{ id: 8, name: "Другая компания" }]);
    render(<WmsLocationLabel id={10} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Не удалось подтвердить доступ");
    expect(screen.queryByText("A · A-01")).not.toBeInTheDocument();
  });
  it("removes the previous label immediately and ignores its late response after id changes", async () => {
    let finish!: (value: WmsLocation) => void;
    asMock(wms.fetchLocation).mockImplementation((id: number) => id === 10 ? new Promise<WmsLocation>((resolve) => { finish = resolve; }) : Promise.resolve(locations[1]));
    const { rerender } = render(<WmsLocationLabel id={10} />);
    rerender(<WmsLocationLabel id={11} />);
    await screen.findByText("Второй");
    finish(locations[0]);
    await waitFor(() => expect(screen.queryByText("Главный")).not.toBeInTheDocument());
  });
  it("retry loads again after a network error without creating any location", async () => {
    asMock(wms.fetchLocation).mockRejectedValueOnce(new Error("Нет связи"));
    render(<WmsLocationLabel id={10} />);
    (await screen.findByRole("button", { name: "Повторить загрузку" })).click();
    await screen.findByText("Главный");
    expect(wms.fetchLocation).toHaveBeenCalledTimes(2);
  });
});
