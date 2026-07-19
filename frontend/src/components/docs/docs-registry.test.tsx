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
});
