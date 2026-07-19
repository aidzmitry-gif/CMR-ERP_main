import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ShipmentStatus } from "@/components/shipments/shipment-status";
// Чистые хелперы форматирования НЕ мокаем. Intl ru-RU ставит узкий неразрывный
// пробел (U+202F/U+00A0) в разряды — строим из вывода хелпера whitespace-толерантный
// regex, иначе точное сравнение строк ломается о разделитель.
import { formatByn } from "@/lib/format";

// Экранируем спецсимволы regex, затем любые пробелы делаем гибкими (\s*).
const wsFlexible = (s: string) =>
  new RegExp(s.replace(/[.()[\]]/g, "\\$&").replace(/\s+/g, "\\s*"));
const bynRe = (n: number) => wsFlexible(formatByn(n));

describe("ShipmentStatus", () => {
  it("рендерит шапку рейса, статус и вес рейса", () => {
    render(<ShipmentStatus />);
    expect(screen.getByText("Статус отгрузки — сквозной")).toBeInTheDocument();
    // статус-чип в шапке рейса (source of truth — логистика)
    expect(screen.getAllByText("В пути до склада").length).toBeGreaterThan(0);
    expect(screen.getByText("Рейс № TR-2026-0418 · авто AB 7421-7")).toBeInTheDocument();
    // вес форматируется через formatNumber → «1 280 кг» (узкий неразрывный пробел ru-RU)
    expect(screen.getAllByText(/1\s*280\s*кг/).length).toBeGreaterThan(0);
  });

  it("готовность пути = 2 из 5 переходов = 40%", () => {
    render(<ShipmentStatus />);
    // doneCount=2, шагов 6 → переходов 5 → round(2/5*100)=40. Если сломать формулу — упадёт.
    expect(screen.getByText("40%")).toBeInTheDocument();
    expect(screen.getByText("сейчас здесь")).toBeInTheDocument();
  });

  it("роль «Продавец» (по умолчанию): видит выручку/маржу и клиента, но НЕ себестоимость", () => {
    render(<ShipmentStatus />);
    // маржа видна продавцу
    expect(screen.getByText("Выручка по рейсу")).toBeInTheDocument();
    expect(screen.getByText(bynRe(61200))).toBeInTheDocument();
    // себестоимость/поставщик скрыты (лейбл-строки нет; substring в ROLE_NOTE не матчится exact)
    expect(screen.queryByText("Поставщик")).not.toBeInTheDocument();
    expect(screen.queryByText("Себестоимость (landed)")).not.toBeInTheDocument();
    // столбец «Клиент» в таблице показан (showFor)
    expect(screen.getByText("Клиент", { selector: "th" })).toBeInTheDocument();
  });

  it("переключение на «Закупщик» раскрывает себестоимость и прячет выручку и клиента", () => {
    render(<ShipmentStatus />);
    fireEvent.click(screen.getByRole("button", { name: "Закупщик" }));

    // теперь видны поставщик и себестоимость
    expect(screen.getByText("Поставщик")).toBeInTheDocument();
    expect(screen.getByText("Себестоимость (landed)")).toBeInTheDocument();
    expect(screen.getByText(bynRe(38400))).toBeInTheDocument();
    // маржа и столбец «Клиент» скрыты для закупщика
    expect(screen.queryByText("Выручка по рейсу")).not.toBeInTheDocument();
    expect(screen.queryByText("Клиент", { selector: "th" })).not.toBeInTheDocument();
  });

  it("роль «Директор» видит и себестоимость, и выручку одновременно", () => {
    render(<ShipmentStatus />);
    fireEvent.click(screen.getByRole("button", { name: "Директор" }));

    expect(screen.getByText("Себестоимость (landed)")).toBeInTheDocument();
    expect(screen.getByText("Выручка по рейсу")).toBeInTheDocument();
    // и себестоимость, и выручка в одной проекции
    expect(screen.getByText(bynRe(38400))).toBeInTheDocument();
    expect(screen.getByText(bynRe(61200))).toBeInTheDocument();
  });

  it("видимость статуса клиенту «Скрыть» убирает и статус, и дату доставки", () => {
    render(<ShipmentStatus />);
    // по умолчанию (Полный) — есть строка статуса и дата доставки
    expect(screen.getByText("В пути до склада → к вам")).toBeInTheDocument();
    expect(screen.getByText("Ожидаемая доставка")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Скрыть" }));

    expect(screen.queryByText("В пути до склада → к вам")).not.toBeInTheDocument();
    expect(screen.queryByText("Ожидаемая доставка")).not.toBeInTheDocument();
  });

  it("видимость «Сокращённый» меняет текст клиентского статуса на «В обработке»", () => {
    render(<ShipmentStatus />);
    fireEvent.click(screen.getByRole("button", { name: "Сокращённый" }));

    expect(screen.getByText("В обработке")).toBeInTheDocument();
    expect(screen.queryByText("В пути до склада → к вам")).not.toBeInTheDocument();
    // дата доставки при сокращённом остаётся видимой (showClientEta)
    expect(screen.getByText("Ожидаемая доставка")).toBeInTheDocument();
  });

  it("видимость «Только дата» прячет статус, но оставляет дату доставки", () => {
    render(<ShipmentStatus />);
    fireEvent.click(screen.getByRole("button", { name: "Только дата" }));

    expect(screen.queryByText("В пути до склада → к вам")).not.toBeInTheDocument();
    expect(screen.queryByText("В обработке")).not.toBeInTheDocument();
    expect(screen.getByText("Ожидаемая доставка")).toBeInTheDocument();
  });
});
