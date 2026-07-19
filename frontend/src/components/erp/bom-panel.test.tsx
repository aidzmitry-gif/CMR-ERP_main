import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// Мокаем только сетевые функции домена BOM; чистые (статусы/обеспеченность/счётчики)
// оставляем реальными — их вывод компонент рендерит по тексту.
vi.mock("@/lib/production-bom", async () => {
  const actual = await vi.importActual<typeof import("@/lib/production-bom")>(
    "@/lib/production-bom",
  );
  return {
    ...actual,
    fetchBoms: vi.fn(),
    fetchBom: vi.fn(),
    createBom: vi.fn(),
    approveBom: vi.fn(),
    deleteBom: vi.fn(),
    addBomItem: vi.fn(),
    deleteBomItem: vi.fn(),
  };
});

import { BomPanel } from "@/components/erp/bom-panel";
import * as bom from "@/lib/production-bom";
import type { Bom, BomDetail } from "@/lib/production-bom";

const boms: Bom[] = [
  { id: 1, product: "Стеллаж СТ-1", version: "v1", status: "draft", note: "", item_count: 3, coverage: 66 },
  { id: 2, product: "Тумба ТБ-2", version: "v2", status: "approved", note: "", item_count: 2, coverage: 100 },
];

const detail1: BomDetail = {
  ...boms[0],
  items: [
    { id: 11, bom_id: 1, component: "Стойка 2м", norm_qty: 4, unit: "шт", stock: 10, reserved: 2, status: "ok" },
    { id: 12, bom_id: 1, component: "Полка 900", norm_qty: 2.5, unit: "шт", stock: 3, reserved: 2, status: "short" },
  ],
};

const asMock = (fn: unknown) => fn as ReturnType<typeof vi.fn>;

beforeEach(() => {
  vi.clearAllMocks();
  // useEffect на маунте перечитывает список — по умолчанию отдаём те же фикстуры,
  // чтобы клиентский refetch не затирал SSR-данные.
  asMock(bom.fetchBoms).mockResolvedValue(boms);
  asMock(bom.fetchBom).mockResolvedValue(detail1);
  asMock(bom.createBom).mockResolvedValue({ ...boms[0], id: 3, product: "Новое" });
  asMock(bom.approveBom).mockResolvedValue(true);
  asMock(bom.deleteBom).mockResolvedValue(true);
  asMock(bom.addBomItem).mockResolvedValue(true);
  asMock(bom.deleteBomItem).mockResolvedValue(true);
});

describe("BomPanel", () => {
  it("рендерит KPI, строки спецификаций, статусы и обеспеченность", async () => {
    render(<BomPanel initial={boms} />);
    await waitFor(() => expect(bom.fetchBoms).toHaveBeenCalled());

    // KPI: всего 2, утверждено 1, черновиков 1, не обеспечено 1 (coverage<100)
    const totalTile = screen.getByText("Спецификаций").closest("div")?.parentElement;
    expect(totalTile).toHaveTextContent("2");
    const approvedTile = screen.getByText("Утверждено").closest("div")?.parentElement;
    expect(approvedTile).toHaveTextContent("1");
    const underTile = screen.getByText("Не обеспечено").closest("div")?.parentElement;
    expect(underTile).toHaveTextContent("1");

    // строки списка + русские статусы + coverage
    expect(screen.getByText("Стеллаж СТ-1")).toBeInTheDocument();
    expect(screen.getByText("Тумба ТБ-2")).toBeInTheDocument();
    expect(screen.getByText("Черновик")).toBeInTheDocument();
    expect(screen.getByText("Утверждена")).toBeInTheDocument();
    expect(screen.getByText("66%")).toBeInTheDocument();
    expect(screen.getByText("100%")).toBeInTheDocument();
  });

  it("пустой список показывает заглушку «Спецификаций пока нет»", async () => {
    asMock(bom.fetchBoms).mockResolvedValue([]);
    render(<BomPanel initial={[]} />);
    expect(await screen.findByText("Спецификаций пока нет")).toBeInTheDocument();
  });

  it("клик по строке раскрывает состав: загрузка → позиции с «доступно» и дефицитом", async () => {
    render(<BomPanel initial={boms} />);
    await waitFor(() => expect(bom.fetchBoms).toHaveBeenCalled());

    fireEvent.click(screen.getByText("Стеллаж СТ-1"));
    // до прихода детали — плейсхолдер загрузки
    expect(screen.getByText("Загрузка состава…")).toBeInTheDocument();

    expect(await screen.findByText("Состав изделия")).toBeInTheDocument();
    expect(bom.fetchBom).toHaveBeenCalledWith(1);
    expect(screen.getByText("Стойка 2м")).toBeInTheDocument();
    expect(screen.getByText("Полка 900")).toBeInTheDocument();
    // available = stock - reserved: 10-2=8 и 3-2=1; норма 2,5 в русском формате
    expect(screen.getByText("8")).toBeInTheDocument();
    expect(screen.getByText(/2,5/)).toBeInTheDocument();
    // одна дефицитная позиция → счётчик «дефицит: 1»
    expect(screen.getByText(/дефицит: 1/)).toBeInTheDocument();
  });

  it("создание спецификации: ввод изделия + клик зовёт createBom и перечитывает список", async () => {
    render(<BomPanel initial={boms} />);
    await waitFor(() => expect(bom.fetchBoms).toHaveBeenCalled());
    asMock(bom.fetchBoms).mockClear();

    fireEvent.change(screen.getByPlaceholderText("Изделие новой спецификации"), {
      target: { value: "Верстак ВК-9" },
    });
    fireEvent.change(screen.getByPlaceholderText("Версия (v1)"), { target: { value: "v3" } });
    fireEvent.click(screen.getByRole("button", { name: /Спецификация/ }));

    await waitFor(() =>
      expect(bom.createBom).toHaveBeenCalledWith({ product: "Верстак ВК-9", version: "v3" }),
    );
    // после создания — refreshList перечитывает список
    await waitFor(() => expect(bom.fetchBoms).toHaveBeenCalled());
  });

  it("пустое изделие не зовёт createBom, а подсвечивает поле ошибкой", async () => {
    render(<BomPanel initial={boms} />);
    await waitFor(() => expect(bom.fetchBoms).toHaveBeenCalled());

    const input = screen.getByPlaceholderText("Изделие новой спецификации");
    fireEvent.click(screen.getByRole("button", { name: /Спецификация/ }));

    expect(bom.createBom).not.toHaveBeenCalled();
    expect(input.className).toMatch(/amber/);
  });

  it("кнопка утверждения есть только у черновика и зовёт approveBom с его id", async () => {
    render(<BomPanel initial={boms} />);
    await waitFor(() => expect(bom.fetchBoms).toHaveBeenCalled());

    // у утверждённой (id=2) кнопки нет → всего одна на весь список
    const approveButtons = screen.getAllByTitle("Утвердить спецификацию");
    expect(approveButtons).toHaveLength(1);

    fireEvent.click(approveButtons[0]);
    await waitFor(() => expect(bom.approveBom).toHaveBeenCalledWith(1));
  });

  it("удаление спецификации зовёт deleteBom с id строки", async () => {
    render(<BomPanel initial={boms} />);
    await waitFor(() => expect(bom.fetchBoms).toHaveBeenCalled());

    const delButtons = screen.getAllByTitle("Удалить спецификацию");
    expect(delButtons).toHaveLength(2);
    fireEvent.click(delButtons[1]); // строка id=2
    await waitFor(() => expect(bom.deleteBom).toHaveBeenCalledWith(2));
  });

  it("добавление позиции в раскрытый состав парсит числа и зовёт addBomItem", async () => {
    render(<BomPanel initial={boms} />);
    await waitFor(() => expect(bom.fetchBoms).toHaveBeenCalled());

    fireEvent.click(screen.getByText("Стеллаж СТ-1"));
    await screen.findByText("Состав изделия");

    fireEvent.change(screen.getByPlaceholderText("Комплектующее"), { target: { value: "Болт М8" } });
    fireEvent.change(screen.getByPlaceholderText("Норма"), { target: { value: "2,5" } });
    fireEvent.change(screen.getByPlaceholderText("Ед."), { target: { value: "шт" } });
    fireEvent.change(screen.getByPlaceholderText("Склад"), { target: { value: "100" } });
    fireEvent.change(screen.getByPlaceholderText("Резерв"), { target: { value: "10" } });
    fireEvent.click(screen.getByRole("button", { name: /Позиция/ }));

    await waitFor(() =>
      expect(bom.addBomItem).toHaveBeenCalledWith(1, {
        component: "Болт М8",
        norm_qty: 2.5,
        unit: "шт",
        stock: 100,
        reserved: 10,
      }),
    );
  });

  it("пустое состояние состава: подсказка добавить комплектующее", async () => {
    asMock(bom.fetchBom).mockResolvedValue({ ...boms[0], items: [] });
    render(<BomPanel initial={boms} />);
    await waitFor(() => expect(bom.fetchBoms).toHaveBeenCalled());

    fireEvent.click(screen.getByText("Стеллаж СТ-1"));
    expect(await screen.findByText("Состав пуст — добавьте комплектующее")).toBeInTheDocument();
  });

  it("удаление позиции состава зовёт deleteBomItem с id позиции", async () => {
    render(<BomPanel initial={boms} />);
    await waitFor(() => expect(bom.fetchBoms).toHaveBeenCalled());

    fireEvent.click(screen.getByText("Стеллаж СТ-1"));
    await screen.findByText("Состав изделия");

    const row = screen.getByText("Стойка 2м").closest("tr") as HTMLElement;
    fireEvent.click(within(row).getByTitle("Удалить позицию"));
    await waitFor(() => expect(bom.deleteBomItem).toHaveBeenCalledWith(11));
  });
});
