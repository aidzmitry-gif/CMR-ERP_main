import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { WmsLocation } from "@/lib/wms-ops";

// next/link → простая <a> (jsdom): компонент тестируем изолированно.
vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

vi.mock("@/lib/wms-ops", async (importActual) => {
  const actual = await importActual<typeof import("@/lib/wms-ops")>();
  return {
    ...actual,
    fetchLocations: vi.fn().mockResolvedValue([]),
    createLocation: vi.fn().mockResolvedValue(true),
  };
});

import { WmsLocations } from "@/components/erp/wms-locations";
import * as wmsOps from "@/lib/wms-ops";

const asMock = (fn: unknown) => fn as ReturnType<typeof vi.fn>;

const locations: WmsLocation[] = [
  { id: 1, warehouse: "Главный", zone: "A", code: "A-01", title: "Стеллаж 1", is_active: true },
  { id: 2, warehouse: "Главный", zone: "", code: "B-02", title: "", is_active: false },
];

beforeEach(() => {
  vi.clearAllMocks();
  asMock(wmsOps.fetchLocations).mockResolvedValue([]);
  asMock(wmsOps.createLocation).mockResolvedValue(true);
});

describe("WmsLocations", () => {
  it("пустой список показывает подсказку добавить первую ячейку", () => {
    render(<WmsLocations initial={[]} />);
    expect(screen.getByText("Ячеек пока нет — добавьте первую")).toBeInTheDocument();
  });

  it("рендерит строки с меткой ячейки, статусом и ссылкой на этикетку", () => {
    render(<WmsLocations initial={locations} />);

    // locationLabel: «зона · код» когда есть зона, иначе просто код
    expect(screen.getByText("A · A-01")).toBeInTheDocument();
    expect(screen.getByText("B-02")).toBeInTheDocument();

    // статусы
    expect(screen.getByText("Активна")).toBeInTheDocument();
    expect(screen.getByText("Архив")).toBeInTheDocument();

    // прочерки для пустых зоны/описания второй строки
    const dashes = screen.getAllByText("—");
    expect(dashes.length).toBe(2); // зона и описание у второй строки

    // ссылка на этикетку ведёт на конкретный id
    const links = screen.getAllByRole("link", { name: /Этикетка/ });
    expect(links[0]).toHaveAttribute("href", "/erp/wms/locations/1/label");
    expect(links[1]).toHaveAttribute("href", "/erp/wms/locations/2/label");
  });

  it("пустой код ячейки при добавлении не зовёт createLocation и подсвечивает поле ошибкой", () => {
    render(<WmsLocations initial={[]} />);
    fireEvent.click(screen.getByRole("button", { name: /Добавить/ }));

    expect(wmsOps.createLocation).not.toHaveBeenCalled();
    expect(screen.getByPlaceholderText("Ячейка*").className).toContain("border-amber-500");
  });

  it("заполненная форма зовёт createLocation с обрезанными полями и очищает код/описание после успеха", async () => {
    asMock(wmsOps.fetchLocations).mockResolvedValue([
      { id: 3, warehouse: "Главный", zone: "C", code: "C-03", title: "Новая", is_active: true },
    ]);

    render(<WmsLocations initial={[]} />);

    fireEvent.change(screen.getByPlaceholderText("Склад"), { target: { value: "  Склад-2  " } });
    fireEvent.change(screen.getByPlaceholderText("Зона"), { target: { value: "  Z  " } });
    fireEvent.change(screen.getByPlaceholderText("Ячейка*"), { target: { value: "  Z-09  " } });
    fireEvent.change(screen.getByPlaceholderText("Описание"), { target: { value: "  Верхний ряд  " } });

    fireEvent.click(screen.getByRole("button", { name: /Добавить/ }));

    await waitFor(() =>
      expect(wmsOps.createLocation).toHaveBeenCalledWith({
        warehouse: "Склад-2",
        zone: "Z",
        code: "Z-09",
        title: "Верхний ряд",
      }),
    );

    // после успешного добавления код и описание сброшены, склад/зона сохранены
    await waitFor(() =>
      expect((screen.getByPlaceholderText("Ячейка*") as HTMLInputElement).value).toBe(""),
    );
    expect((screen.getByPlaceholderText("Описание") as HTMLInputElement).value).toBe("");
    // склад/зона сохраняются как есть (не обрезаются при сбросе формы), только code/title трим на отправке
    expect((screen.getByPlaceholderText("Склад") as HTMLInputElement).value).toBe("  Склад-2  ");
    expect((screen.getByPlaceholderText("Зона") as HTMLInputElement).value).toBe("  Z  ");

    // список обновлён из fetchLocations
    expect(await screen.findByText("C · C-03")).toBeInTheDocument();
  });

  it("если createLocation вернул false — список не обновляется и форма не сбрасывается", async () => {
    asMock(wmsOps.createLocation).mockResolvedValue(false);

    render(<WmsLocations initial={[]} />);
    fireEvent.change(screen.getByPlaceholderText("Ячейка*"), { target: { value: "X-01" } });
    fireEvent.click(screen.getByRole("button", { name: /Добавить/ }));

    await waitFor(() => expect(wmsOps.createLocation).toHaveBeenCalled());
    expect(wmsOps.fetchLocations).not.toHaveBeenCalled();
    expect((screen.getByPlaceholderText("Ячейка*") as HTMLInputElement).value).toBe("X-01");
  });

  it("пустой склад при добавлении подставляет «Главный» по умолчанию", async () => {
    render(<WmsLocations initial={[]} />);
    fireEvent.change(screen.getByPlaceholderText("Склад"), { target: { value: "   " } });
    fireEvent.change(screen.getByPlaceholderText("Ячейка*"), { target: { value: "D-01" } });
    fireEvent.click(screen.getByRole("button", { name: /Добавить/ }));

    await waitFor(() =>
      expect(wmsOps.createLocation).toHaveBeenCalledWith(
        expect.objectContaining({ warehouse: "Главный", code: "D-01" }),
      ),
    );
  });
});
