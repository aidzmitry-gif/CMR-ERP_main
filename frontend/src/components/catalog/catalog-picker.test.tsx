import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

// Компонент самодостаточный: демо-каталог внутри, из внешнего — только чистые
// форматтеры @/lib/format (formatByn/plural). Мокать нечего — тестируем как есть.
import { CatalogPicker } from "@/components/catalog/catalog-picker";

// тайл скорборда: label и value лежат в одном .tile-div → находим по label и
// проверяем value внутри плитки (значения-числа не уникальны на всём экране).
function metricTile(label: string): HTMLElement {
  const tile = screen.getByText(label).closest("div")?.parentElement;
  if (!tile) throw new Error(`метрика «${label}» не найдена`);
  return tile as HTMLElement;
}

describe("CatalogPicker", () => {
  it("рендерит заголовок и скорборд с реальными метриками каталога", () => {
    render(<CatalogPicker />);
    expect(screen.getByText("Каталог-подбор")).toBeInTheDocument();

    // 8 позиций в CATALOG; 7 непустых по складу; сумма «в пути» = 40+12+30+6 = 88.
    expect(within(metricTile("Позиций в каталоге")).getByText("8")).toBeInTheDocument();
    expect(within(metricTile("В наличии (своб. > 0)")).getByText("7")).toBeInTheDocument();
    expect(within(metricTile("В пути, шт")).getByText("88")).toBeInTheDocument();
    // корзина пуста → в счёте 0 BYN
    expect(within(metricTile("В счёте сейчас")).getByText("0 BYN")).toBeInTheDocument();
  });

  it("пустая корзина показывает подсказку и не показывает итог/кнопку переноса", () => {
    render(<CatalogPicker />);
    expect(screen.getByText(/Пусто\. Добавьте товары/)).toBeInTheDocument();
    expect(screen.queryByText("Итого")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Перенести в счёт/ })).not.toBeInTheDocument();
  });

  it("поиск сужает каталог, добавление в счёт наполняет корзину и итог", () => {
    render(<CatalogPicker />);

    // сузим до одной карточки — так «В счёт» будет единственной кнопкой товара
    fireEvent.change(screen.getByPlaceholderText(/поиск: название/), {
      target: { value: "6СТ-77" },
    });
    expect(screen.getByText("АКБ 6СТ-77 (легковой)")).toBeInTheDocument();
    expect(screen.queryByText("АКБ 6СТ-190 (Зубр)")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "В счёт" }));

    // корзина: позиция появилась, «Пусто» ушло, итог и НДС посчитаны (цена 260)
    expect(screen.queryByText(/Пусто\. Добавьте товары/)).not.toBeInTheDocument();
    expect(screen.getByText("Итого")).toBeInTheDocument();
    expect(screen.getAllByText("260 BYN").length).toBeGreaterThan(0);
    // метрика «В счёте сейчас» обновилась синхронно с корзиной
    expect(within(metricTile("В счёте сейчас")).getByText("260 BYN")).toBeInTheDocument();
  });

  it("контрол количества (+ / убрать) меняет сумму и очищает корзину", () => {
    render(<CatalogPicker />);
    fireEvent.change(screen.getByPlaceholderText(/поиск: название/), {
      target: { value: "6СТ-77" },
    });

    fireEvent.click(screen.getByRole("button", { name: "В счёт" }));
    // после добавления в карточке появился числовой инпут количества (= 1)
    const qty = screen.getByDisplayValue("1") as HTMLInputElement;
    fireEvent.change(qty, { target: { value: "3" } });
    // 3 × 260 = 780
    expect(within(metricTile("В счёте сейчас")).getByText("780 BYN")).toBeInTheDocument();

    // крестик «Убрать» в корзине очищает позицию
    fireEvent.click(screen.getByRole("button", { name: "Убрать" }));
    expect(screen.getByText(/Пусто\. Добавьте товары/)).toBeInTheDocument();
    expect(within(metricTile("В счёте сейчас")).getByText("0 BYN")).toBeInTheDocument();
  });

  it("фильтр по группе-чипу оставляет только товары группы", () => {
    render(<CatalogPicker />);
    expect(screen.getByText("АКБ 6СТ-77 (легковой)")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Услуги/ }));
    expect(screen.getByText("Доставка по РБ")).toBeInTheDocument();
    expect(screen.queryByText("АКБ 6СТ-77 (легковой)")).not.toBeInTheDocument();
  });

  it("бессмысленный поиск даёт пустое состояние «Ничего не найдено»", () => {
    render(<CatalogPicker />);
    fireEvent.change(screen.getByPlaceholderText(/поиск: название/), {
      target: { value: "zzzzzz" },
    });
    expect(screen.getByText(/Ничего не найдено/)).toBeInTheDocument();
  });

  it("ИИ-подбор по свободному запросу ранжирует товар и кладёт его в счёт", async () => {
    render(<CatalogPicker />);

    fireEvent.change(
      screen.getByPlaceholderText(/Свободный запрос ИИ/),
      { target: { value: "нужен АКБ на фуру MAN бюджет до 1500 срочно" } },
    );
    fireEvent.click(screen.getByRole("button", { name: /Подобрать/ }));

    // блок рекомендаций с учётом бюджета и срочности из запроса
    expect(await screen.findByText(/Рекомендую под задачу/)).toBeInTheDocument();
    // грузовой АКБ 6СТ-190 бьётся по тегу «man» + в бюджет 1500 + есть на складе:
    // виден и в каталоге, и в блоке рекомендаций → минимум 2 совпадения
    const before = screen.getAllByText(/АКБ 6СТ-190 \(Зубр\)/);
    expect(before.length).toBeGreaterThanOrEqual(2);

    // кнопка «в счёт» (строчная) — из блока рекомендаций, а не из каталога («В счёт»)
    fireEvent.click(screen.getAllByRole("button", { name: "в счёт" })[0]);
    expect(screen.queryByText(/Пусто\. Добавьте товары/)).not.toBeInTheDocument();
    // добавленный товар теперь виден и в корзине справа → на одно совпадение больше
    expect(screen.getAllByText(/АКБ 6СТ-190 \(Зубр\)/).length).toBeGreaterThan(before.length);
  });

  it("ИИ-подбор без ввода просит уточнить задачу", () => {
    render(<CatalogPicker />);
    fireEvent.click(screen.getByRole("button", { name: /Подобрать/ }));
    expect(screen.getByText(/Опишите задачу/)).toBeInTheDocument();
  });
});
