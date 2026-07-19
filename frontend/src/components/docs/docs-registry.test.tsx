import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DocsRegistry } from "@/components/docs/docs-registry";

// Компонент полностью автономен (демо-данные внутри, единственная внешняя
// зависимость — чистый formatByn из @/lib/format). Мокать нечего.

// нормализуем пробелы (formatByn ставит неразрывный U+00A0 как разделитель тысяч)
const digits = (s: string | null | undefined) => (s ?? "").replace(/\s/g, "");

// карточка скорборда: находим по подписи, поднимаемся к контейнеру со значением
function scoreCard(label: string): HTMLElement {
  const el = screen.getByText(label).closest("div")?.parentElement;
  if (!el) throw new Error(`нет карточки скорборда «${label}»`);
  return el as HTMLElement;
}

describe("DocsRegistry", () => {
  it("рендерит заголовок и по умолчанию роль «Менеджер» с её областью видимости", () => {
    render(<DocsRegistry />);
    expect(screen.getByText("Реестр документов")).toBeInTheDocument();
    // область видимости менеджера подписана в шапке роли
    expect(screen.getByText("свои сделки")).toBeInTheDocument();
    // менеджер (Сидоров К.) видит только 3 своих документа
    expect(scoreCard("документов видно")).toHaveTextContent("3");
  });

  it("скорборд менеджера: сумма BYN, заморожено (подписан/оплачен) = 2, помечено = 0", () => {
    render(<DocsRegistry />);
    // 12 400 + 86 000 + 86 000 = 184 400 BYN
    expect(digits(scoreCard("сумма по реестру").textContent)).toContain("184400BYN");
    // ДГ-0118 подписан + СЧ-0420 оплачен → два замороженных
    expect(scoreCard("заморожено (подписан/оплачен)")).toHaveTextContent("2");
    expect(scoreCard("помечено на удаление")).toHaveTextContent("0");
  });

  it("роль «Директор» расширяет видимость до всех 10 документов", () => {
    render(<DocsRegistry />);
    fireEvent.click(screen.getByRole("button", { name: /Директор/ }));
    expect(screen.getByText("все отделы")).toBeInTheDocument();
    expect(scoreCard("документов видно")).toHaveTextContent("10");
  });

  it("роль «РОП (Новые)» ограничивает отделом и видит 1 помеченный документ", () => {
    render(<DocsRegistry />);
    fireEvent.click(screen.getByRole("button", { name: /РОП/ }));
    expect(screen.getAllByText(/Отдел продаж · Новые/).length).toBeGreaterThan(0);
    // отдел «Новые» = Сидоров + Петрова: 5 документов, из них КП-0288 помечен
    expect(scoreCard("документов видно")).toHaveTextContent("5");
    expect(scoreCard("помечено на удаление")).toHaveTextContent("1");
  });

  it("поиск сужает реестр до одного документа, прочие исчезают", () => {
    render(<DocsRegistry />);
    // менеджер видит СЧ-0461 и СЧ-0420 — оба присутствуют до поиска
    expect(screen.getByText("Счёт СЧ-0420")).toBeInTheDocument();
    fireEvent.change(screen.getByPlaceholderText("номер / сделка / клиент"), {
      target: { value: "СЧ-0461" },
    });
    expect(screen.getByText("Счёт СЧ-0461")).toBeInTheDocument();
    expect(screen.queryByText("Счёт СЧ-0420")).not.toBeInTheDocument();
    expect(scoreCard("документов видно")).toHaveTextContent("1");
  });

  it("несовпадающий фильтр даёт пустое состояние", () => {
    render(<DocsRegistry />);
    fireEvent.change(screen.getByPlaceholderText("номер / сделка / клиент"), {
      target: { value: "нет-такого-документа" },
    });
    expect(screen.getByText("Нет документов под текущие фильтры/роль")).toBeInTheDocument();
  });

  it("«Изменить» на незамороженном документе поднимает версию и показывает тост", () => {
    render(<DocsRegistry />);
    fireEvent.change(screen.getByPlaceholderText("номер / сделка / клиент"), {
      target: { value: "СЧ-0461" },
    });
    const row = screen.getByText("Счёт СЧ-0461").closest("div")?.parentElement
      ?.parentElement as HTMLElement;
    expect(within(row).getByText("v1")).toBeInTheDocument();

    fireEvent.click(screen.getByTitle("Изменить (новая версия)"));

    // тост о новой версии + бейдж версии на строке поднялся до v2
    expect(screen.getByText(/Новая версия/)).toBeInTheDocument();
    expect(within(row).getByText("v2")).toBeInTheDocument();
    expect(within(row).queryByText("v1")).not.toBeInTheDocument();
  });

  it("«Пометить на удаление» шлёт тост и увеличивает счётчик помеченных", () => {
    render(<DocsRegistry />);
    fireEvent.change(screen.getByPlaceholderText("номер / сделка / клиент"), {
      target: { value: "СЧ-0461" },
    });
    expect(scoreCard("помечено на удаление")).toHaveTextContent("0");

    fireEvent.click(screen.getByTitle("Пометить на удаление"));

    expect(screen.getByText(/Помечен: Счёт СЧ-0461/)).toBeInTheDocument();
    expect(screen.getByText(/на удалении/)).toBeInTheDocument();
    expect(scoreCard("помечено на удаление")).toHaveTextContent("1");
  });

  it("замороженный (подписанный) документ показывает Lock и блокирует правку/пометку", () => {
    render(<DocsRegistry />);
    fireEvent.change(screen.getByPlaceholderText("номер / сделка / клиент"), {
      target: { value: "ДГ-0118" },
    });
    // кнопки правки и пометки заменены на Lock-кнопки в «запрещающем» красном стиле
    expect(screen.getByTitle("Заморожен (юр. сила) — правка запрещена").className).toMatch(/red/);
    expect(screen.getByTitle("Заморожен — пометка запрещена").className).toMatch(/red/);
    // обычной кнопки «Изменить» для этого документа нет
    expect(screen.queryByTitle("Изменить (новая версия)")).not.toBeInTheDocument();
  });

  it("уже помеченный документ (взгляд директора) виден как «на удалении» с основанием и заблокированной отправкой", () => {
    render(<DocsRegistry />);
    fireEvent.click(screen.getByRole("button", { name: /Директор/ }));
    fireEvent.change(screen.getByPlaceholderText("номер / сделка / клиент"), {
      target: { value: "КП-0288" },
    });
    expect(screen.getByText(/на удалении/)).toBeInTheDocument();
    expect(screen.getByText(/основание: устаревшие цены/)).toBeInTheDocument();
    // отправка помеченного запрещена — вместо «Отправить» красная блок-кнопка
    expect(
      screen.getByTitle("Помечен на удаление — отправка запрещена").className,
    ).toMatch(/red/);
    expect(screen.queryByTitle("Отправить")).not.toBeInTheDocument();
  });

  it("фильтр по типу «Счёт» оставляет только 3 счёта (роль директор)", () => {
    render(<DocsRegistry />);
    fireEvent.click(screen.getByRole("button", { name: /Директор/ }));
    const kindSelect = screen.getAllByRole("combobox")[1];
    fireEvent.change(kindSelect, { target: { value: "Счёт" } });
    expect(scoreCard("документов видно")).toHaveTextContent("3");
    expect(screen.getByText("Счёт СЧ-0461")).toBeInTheDocument();
    expect(screen.getByText("Счёт СЧ-0420")).toBeInTheDocument();
    expect(screen.getByText("Счёт СЧ-0455")).toBeInTheDocument();
    expect(screen.queryByText("Договор ДГ-0118")).not.toBeInTheDocument();
  });

  it("фильтр по статусу «оплачен» оставляет ровно 2 документа (роль директор)", () => {
    render(<DocsRegistry />);
    fireEvent.click(screen.getByRole("button", { name: /Директор/ }));
    const statusSelect = screen.getAllByRole("combobox")[4];
    fireEvent.change(statusSelect, { target: { value: "оплачен" } });
    expect(scoreCard("документов видно")).toHaveTextContent("2");
    expect(screen.getByText("Счёт СЧ-0420")).toBeInTheDocument();
    expect(screen.getByText("Счёт СЧ-0455")).toBeInTheDocument();
  });

  it("фильтр по контрагенту «Белтранс» оставляет 2 документа его сделки (роль директор)", () => {
    render(<DocsRegistry />);
    fireEvent.click(screen.getByRole("button", { name: /Директор/ }));
    const clientSelect = screen.getAllByRole("combobox")[0];
    fireEvent.change(clientSelect, { target: { value: "Белтранс" } });
    expect(scoreCard("документов видно")).toHaveTextContent("2");
    expect(screen.getByText("Договор ДГ-0118")).toBeInTheDocument();
    expect(screen.getByText("Счёт СЧ-0420")).toBeInTheDocument();
  });

  it("период «с 13.06.2026» сужает до 4 документов, «Сбросить» возвращает все 10 (роль директор)", () => {
    render(<DocsRegistry />);
    fireEvent.click(screen.getByRole("button", { name: /Директор/ }));
    fireEvent.change(screen.getByTitle("дата с"), { target: { value: "2026-06-13" } });
    expect(scoreCard("документов видно")).toHaveTextContent("4");

    fireEvent.click(screen.getByRole("button", { name: "Сбросить" }));
    expect(scoreCard("документов видно")).toHaveTextContent("10");
    expect(screen.getByTitle("дата с")).toHaveValue("");
  });

  it("чекбокс «только помеченные» оставляет единственный помеченный документ (роль директор)", () => {
    render(<DocsRegistry />);
    fireEvent.click(screen.getByRole("button", { name: /Директор/ }));
    fireEvent.click(screen.getByRole("checkbox"));
    expect(scoreCard("документов видно")).toHaveTextContent("1");
    expect(screen.getByText("КП-0288")).toBeInTheDocument();
  });

  it("группировка «плоско» рисует одну группу «Все документы» с полным счётом и суммой", () => {
    render(<DocsRegistry />);
    fireEvent.click(screen.getByRole("button", { name: /Директор/ }));
    const groupSelect = screen.getAllByRole("combobox")[5];
    fireEvent.change(groupSelect, { target: { value: "flat" } });
    expect(screen.getByText("Все документы")).toBeInTheDocument();
    const header = screen.getByText("Все документы").closest("div")?.parentElement as HTMLElement;
    expect(within(header).getByText("10")).toBeInTheDocument();
  });

  it("группировка «по типу» рисует отдельные заголовки-группы для каждого вида документа", () => {
    render(<DocsRegistry />);
    fireEvent.click(screen.getByRole("button", { name: /Директор/ }));
    const groupSelect = screen.getAllByRole("combobox")[5];
    fireEvent.change(groupSelect, { target: { value: "kind" } });
    // заголовки групп = названия видов документов (не отделов); "Заказ-наряд"
    // встречается дважды — заголовок группы и бейдж вида в строке документа
    const headers = screen.getAllByText("Заказ-наряд");
    expect(headers.length).toBeGreaterThanOrEqual(2);
    expect(headers.some((el) => el.closest("div")?.className.includes("border-b"))).toBe(true);
  });

  it("смена роли на «Менеджер» сбрасывает активный фильтр по менеджеру, выставленный директором", () => {
    render(<DocsRegistry />);
    fireEvent.click(screen.getByRole("button", { name: /Директор/ }));
    const mgrSelect = screen.getAllByRole("combobox")[3];
    fireEvent.change(mgrSelect, { target: { value: "Морозов Д." } });
    expect(scoreCard("документов видно")).toHaveTextContent("2");

    fireEvent.click(screen.getByRole("button", { name: /Менеджер/ }));
    expect(screen.getAllByRole("combobox")[3]).toHaveValue("");
    // видимость снова сузилась до 3 документов Сидорова К.
    expect(scoreCard("документов видно")).toHaveTextContent("3");
  });

  it("«Снять пометку» возвращает помеченный документ в обычный статус", () => {
    render(<DocsRegistry />);
    fireEvent.click(screen.getByRole("button", { name: /Директор/ }));
    fireEvent.change(screen.getByPlaceholderText("номер / сделка / клиент"), {
      target: { value: "КП-0288" },
    });
    expect(scoreCard("помечено на удаление")).toHaveTextContent("1");

    fireEvent.click(screen.getByTitle("Снять пометку"));

    expect(screen.getByText(/Пометка снята: КП-0288/)).toBeInTheDocument();
    expect(screen.queryByText(/на удалении/)).not.toBeInTheDocument();
    expect(scoreCard("помечено на удаление")).toHaveTextContent("0");
  });

  it("оплаченный, но не подписанный документ тоже считается замороженным (правка запрещена)", () => {
    render(<DocsRegistry />);
    fireEvent.change(screen.getByPlaceholderText("номер / сделка / клиент"), {
      target: { value: "СЧ-0420" },
    });
    expect(screen.getByTitle("Заморожен (юр. сила) — правка запрещена")).toBeInTheDocument();
    expect(screen.queryByTitle("Изменить (новая версия)")).not.toBeInTheDocument();
  });

  it("«Просмотр» и «Отправить» шлют тосты с номером конкретного документа", () => {
    render(<DocsRegistry />);
    fireEvent.change(screen.getByPlaceholderText("номер / сделка / клиент"), {
      target: { value: "СЧ-0461" },
    });
    fireEvent.click(screen.getByTitle("Просмотр"));
    expect(screen.getByText("Предпросмотр: Счёт СЧ-0461")).toBeInTheDocument();

    fireEvent.click(screen.getByTitle("Отправить"));
    expect(screen.getByText("Отправка: Счёт СЧ-0461")).toBeInTheDocument();
  });
});
