import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// Мокаем ТОЛЬКО сетевые функции модуля; чистые хелперы (formatNh, normStatusLabel,
// filterByKind, normCounts) оставляем реальными через importOriginal — их поведение
// (русский формат н.ч, лейблы статусов, фильтр по виду, счётчики) участвует в проверках.
vi.mock("@/lib/production-norms", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/production-norms")>();
  return {
    ...actual,
    fetchNorms: vi.fn(),
    createNorm: vi.fn(),
    approveNorm: vi.fn(),
    deleteNorm: vi.fn(),
  };
});

import { NormsTable } from "@/components/erp/norms-table";
import * as norms from "@/lib/production-norms";
import type { Norm } from "@/lib/production-norms";

const mock = (fn: unknown) => fn as ReturnType<typeof vi.fn>;

function makeNorms(): Norm[] {
  return [
    { id: 1, kind: "product", title: "Балка", nh: 10, status: "approved", note: "" },
    { id: 2, kind: "product", title: "Ферма", nh: 7.5, status: "pending", note: "" },
    { id: 3, kind: "product", title: "Заготовка", nh: 0, status: "none", note: "" },
    { id: 4, kind: "operation", title: "Сварка", nh: 2, status: "pending", note: "" },
  ];
}

function rowOf(title: string): HTMLElement {
  return screen.getByText(title).closest("tr") as HTMLElement;
}

beforeEach(() => {
  vi.clearAllMocks();
  // компонент на маунте тихо перечитывает список с клиента — по умолчанию отдаём фикстуру
  mock(norms.fetchNorms).mockResolvedValue(makeNorms());
  mock(norms.createNorm).mockResolvedValue({
    id: 99,
    kind: "product",
    title: "Новая",
    nh: 3.5,
    status: "none",
    note: "",
  });
  mock(norms.approveNorm).mockResolvedValue(true);
  mock(norms.deleteNorm).mockResolvedValue(true);
});

describe("NormsTable", () => {
  it("KPI считаются из реального normCounts (всего/на утверждении/без нормы)", async () => {
    render(<NormsTable initial={makeNorms()} />);
    // ждём тихий перечит на клиенте
    await waitFor(() => expect(norms.fetchNorms).toHaveBeenCalled());

    const total = screen.getByText("Всего норм").parentElement as HTMLElement;
    expect(total).toHaveTextContent("4");
    // «На утверждении» встречается и как KPI-лейбл, и как бейдж статуса — берём KPI (рендерится первым)
    const pending = screen.getAllByText("На утверждении")[0].parentElement as HTMLElement;
    expect(pending).toHaveTextContent("2");
    const none = screen.getByText("Без нормы").parentElement as HTMLElement;
    expect(none).toHaveTextContent("1");
  });

  it("по умолчанию показывает изделия и форматирует н.ч по-русски (real formatNh)", async () => {
    render(<NormsTable initial={makeNorms()} />);
    await waitFor(() => expect(screen.getByText("Балка")).toBeInTheDocument());

    // изделия видны, операция скрыта
    expect(screen.getByText("Ферма")).toBeInTheDocument();
    expect(screen.queryByText("Сварка")).not.toBeInTheDocument();

    // формат: 10 → «10», 7.5 → «7,5», 0 → «—»
    expect(within(rowOf("Балка")).getByText("10")).toBeInTheDocument();
    expect(within(rowOf("Ферма")).getByText("7,5")).toBeInTheDocument();
    expect(within(rowOf("Заготовка")).getByText("—")).toBeInTheDocument();
  });

  it("переключение на «Операции» фильтрует строки по виду (real filterByKind)", async () => {
    render(<NormsTable initial={makeNorms()} />);
    await waitFor(() => expect(screen.getByText("Балка")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Операции" }));

    expect(screen.getByText("Сварка")).toBeInTheDocument();
    expect(screen.queryByText("Балка")).not.toBeInTheDocument();
    expect(screen.queryByText("Ферма")).not.toBeInTheDocument();
  });

  it("пустой вид показывает подсказку «Норм этого вида пока нет»", async () => {
    // только изделия — вкладка «Операции» пуста
    const productsOnly = makeNorms().filter((n) => n.kind === "product");
    mock(norms.fetchNorms).mockResolvedValue(productsOnly);
    render(<NormsTable initial={productsOnly} />);
    await waitFor(() => expect(screen.getByText("Балка")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Операции" }));
    expect(screen.getByText("Норм этого вида пока нет")).toBeInTheDocument();
  });

  it("кнопка утверждения есть только у неутверждённых норм", async () => {
    render(<NormsTable initial={makeNorms()} />);
    await waitFor(() => expect(screen.getByText("Балка")).toBeInTheDocument());

    // approved — без кнопки «Утвердить», но с «Удалить»
    expect(within(rowOf("Балка")).queryByTitle("Утвердить норму")).toBeNull();
    expect(within(rowOf("Балка")).getByTitle("Удалить норму")).toBeInTheDocument();
    // pending — обе кнопки
    expect(within(rowOf("Ферма")).getByTitle("Утвердить норму")).toBeInTheDocument();
  });

  it("клик по «Утвердить» зовёт approveNorm с id строки и перечитывает список", async () => {
    render(<NormsTable initial={makeNorms()} />);
    await waitFor(() => expect(screen.getByText("Ферма")).toBeInTheDocument());
    mock(norms.fetchNorms).mockClear(); // отсекаем маунт-вызов

    fireEvent.click(within(rowOf("Ферма")).getByTitle("Утвердить норму"));

    await waitFor(() => expect(norms.approveNorm).toHaveBeenCalledWith(2));
    // ok=true → перечит фактического состояния
    await waitFor(() => expect(norms.fetchNorms).toHaveBeenCalled());
  });

  it("отказ бэка при утверждении (ok=false) не перечитывает список", async () => {
    mock(norms.approveNorm).mockResolvedValue(false);
    render(<NormsTable initial={makeNorms()} />);
    await waitFor(() => expect(screen.getByText("Ферма")).toBeInTheDocument());
    mock(norms.fetchNorms).mockClear();

    fireEvent.click(within(rowOf("Ферма")).getByTitle("Утвердить норму"));

    await waitFor(() => expect(norms.approveNorm).toHaveBeenCalledWith(2));
    // при отказе refresh не вызывается
    expect(norms.fetchNorms).not.toHaveBeenCalled();
  });

  it("клик по «Удалить» зовёт deleteNorm с id строки", async () => {
    render(<NormsTable initial={makeNorms()} />);
    await waitFor(() => expect(screen.getByText("Заготовка")).toBeInTheDocument());

    fireEvent.click(within(rowOf("Заготовка")).getByTitle("Удалить норму"));

    await waitFor(() => expect(norms.deleteNorm).toHaveBeenCalledWith(3));
  });

  it("добавление с пустым названием не создаёт норму (валидация границы)", async () => {
    render(<NormsTable initial={makeNorms()} />);
    await waitFor(() => expect(screen.getByText("Балка")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: /Добавить/ }));
    expect(norms.createNorm).not.toHaveBeenCalled();
  });

  it("добавление зовёт createNorm с обрезанным названием, видом и н.ч через запятую", async () => {
    render(<NormsTable initial={makeNorms()} />);
    await waitFor(() => expect(screen.getByText("Балка")).toBeInTheDocument());

    fireEvent.change(screen.getByPlaceholderText("Название изделия"), {
      target: { value: "  Кронштейн  " },
    });
    fireEvent.change(screen.getByPlaceholderText("Н.ч"), { target: { value: "3,5" } });
    fireEvent.click(screen.getByRole("button", { name: /Добавить/ }));

    await waitFor(() =>
      expect(norms.createNorm).toHaveBeenCalledWith({
        title: "Кронштейн",
        kind: "product",
        nh: 3.5,
      }),
    );
  });

  it("плейсхолдер названия зависит от выбранного вида", async () => {
    render(<NormsTable initial={makeNorms()} />);
    await waitFor(() => expect(screen.getByText("Балка")).toBeInTheDocument());

    expect(screen.getByPlaceholderText("Название изделия")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Операции" }));
    expect(screen.getByPlaceholderText("Название операции")).toBeInTheDocument();
    // и создание уходит с kind=operation
    fireEvent.change(screen.getByPlaceholderText("Название операции"), {
      target: { value: "Резка" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Добавить/ }));
    await waitFor(() =>
      expect(norms.createNorm).toHaveBeenCalledWith(
        expect.objectContaining({ kind: "operation", title: "Резка" }),
      ),
    );
  });
});
