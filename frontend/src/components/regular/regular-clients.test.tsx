import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RegularClients } from "@/components/regular/regular-clients";
import { formatByn } from "@/lib/format";

// Компонент самодостаточный: demo-данные внутри, из внешнего — только lucide-react
// и @/lib/format (обе работают в jsdom). Моки не нужны — тестируем реальный рендер
// и клиентские взаимодействия (фильтр статусов, раскрытие строки, панель подтверждения).

// formatByn группирует разряды неразрывным пробелом (nbsp) — testing-library
// нормализует пробелы, поэтому сверяем по regex с гибким \s.
const byn = (n: number) => new RegExp(formatByn(n).replace(/\s/g, "\\s"));

describe("RegularClients", () => {
  it("обозначает учебные показатели и отсутствие записи до взаимодействия", () => {
    render(<RegularClients />);
    const notice = screen.getByRole("note", { name: "Учебный режим" });
    expect(notice).toHaveTextContent("Данные и показатели приведены для примера");
    expect(notice).toHaveTextContent("не сохраняются");
    expect(notice).toHaveTextContent("не передаются в закупки");
    fireEvent.click(screen.getByRole("button", { name: /Пора связаться/ }));
    expect(notice).toBeInTheDocument();
  });

  it("учебная отметка не обещает сохранение и сбрасывается при повторном открытии", () => {
    render(<RegularClients />);
    fireEvent.click(screen.getByText(/СтройБаза/));
    fireEvent.click(screen.getByRole("button", { name: /Скорректировать/ }));
    fireEvent.change(screen.getByRole("spinbutton"), { target: { value: "12" } });
    fireEvent.click(screen.getByRole("button", { name: "Подтвердить в демо" }));
    expect(screen.getByRole("button", { name: "Отмечено в демо" })).toBeDisabled();
    fireEvent.click(screen.getByText(/СтройБаза/));
    fireEvent.click(screen.getByText(/СтройБаза/));
    expect(screen.getByRole("button", { name: "Подтвердить в демо" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Отмечено в демо" })).not.toBeInTheDocument();
  });

  it("после изменения количества прежняя учебная отметка снимается", () => {
    render(<RegularClients />);
    fireEvent.click(screen.getByText(/СтройБаза/));
    fireEvent.click(screen.getByRole("button", { name: /Скорректировать/ }));
    const quantity = screen.getByRole("spinbutton");
    fireEvent.change(quantity, { target: { value: "12" } });
    fireEvent.click(screen.getByRole("button", { name: "Подтвердить в демо" }));
    fireEvent.change(quantity, { target: { value: "13" } });
    expect(screen.queryByRole("button", { name: "Отмечено в демо" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Подтвердить в демо" })).toBeEnabled();
  });

  it("не выдаёт выигрыш сделки за оплату и не обещает автоматическую эскалацию", () => {
    render(<RegularClients />);
    expect(screen.getByText(/Выигрыш сделки не подтверждает оплату или отгрузку/)).toBeInTheDocument();
    expect(screen.getByText(/Автоматические задачи и эскалация в этом разделе пока не подключены/)).toBeInTheDocument();
    expect(screen.queryByText(/добавляем обработчик/)).not.toBeInTheDocument();
  });

  it("рендерит заголовок и KPI удержания с суммой в BYN", () => {
    render(<RegularClients />);
    expect(screen.getByRole("heading", { name: "Постоянные клиенты" })).toBeInTheDocument();
    // Повторная выручка — форматируется тем же formatByn, что и в компоненте (nbsp-группировка)
    expect(screen.getByText(byn(418200))).toBeInTheDocument();
    // Значение KPI «Постоянных клиентов»
    expect(screen.getByText("38")).toBeInTheDocument();
  });

  it("средний чек клиента показан в BYN (money-колонка)", () => {
    render(<RegularClients />);
    // ООО «СтройБаза», avg 18400 → «18 400 BYN» через formatByn
    expect(screen.getByText(byn(18400))).toBeInTheDocument();
    // ОАО «Нафтан», avg 62800
    expect(screen.getByText(byn(62800))).toBeInTheDocument();
  });

  it("фильтр «Уходят» оставляет только красных клиентов и прячет остальных", () => {
    render(<RegularClients />);
    // до фильтра виден и красный (Нафтан), и жёлтый (Белтранс)
    expect(screen.getByText(/Нафтан/)).toBeInTheDocument();
    expect(screen.getByText(/Белтранс/)).toBeInTheDocument();

    // счётчик на кнопке «Все» = 10 клиентов
    expect(screen.getByRole("button", { name: /Все/ })).toHaveTextContent("10");

    fireEvent.click(screen.getByRole("button", { name: /Уходят/ }));

    // остаются 3 красных, жёлтые/зелёные исчезают
    expect(screen.getByText(/Нафтан/)).toBeInTheDocument();
    expect(screen.getByText(/СтройБаза/)).toBeInTheDocument();
    expect(screen.queryByText(/Белтранс/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Белводхоз/)).not.toBeInTheDocument();
  });

  it("клик по строке раскрывает панель подтверждённого объёма с итогом для закупки", () => {
    render(<RegularClients />);
    // до раскрытия панели нет
    expect(screen.queryByText("Подтверждённый объём под закупку")).not.toBeInTheDocument();

    // раскрываем ОАО «Белтранс» (roll c40 · s12 · i18 → дозаказать 10)
    fireEvent.click(screen.getByText(/Белтранс/));

    expect(screen.getByText("Подтверждённый объём под закупку")).toBeInTheDocument();
    // три опоры решения
    expect(screen.getByText("История / опыт")).toBeInTheDocument();
    expect(screen.getByText("Договорённость с клиентом")).toBeInTheDocument();
    // роллап в план закупки: 40 подтв − 12 склад − 18 в пути = дозаказать 10
    expect(screen.getByText(/дозаказать 10 шт/)).toBeInTheDocument();
  });

  it("«Скорректировать» открывает ввод и пересчитывает роллап закупки на лету", () => {
    render(<RegularClients />);
    // ООО «СтройБаза»: единственная позиция с подтв. объёмом 0 → «объём НЕ подтверждён»
    fireEvent.click(screen.getByText(/СтройБаза/));
    // роллап (не опора-пилар): содержит «· склад 20» — уникальный маркер строки закупки
    expect(screen.getByText(/объём НЕ подтверждён · склад 20/)).toBeInTheDocument();

    // до правки числового поля нет
    expect(document.querySelector('input[type="number"]')).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /Скорректировать/ }));
    const input = document.querySelector('input[type="number"]') as HTMLInputElement;
    expect(input).not.toBeNull();

    // указываем 10 шт → роллап пересчитан: склад 20 покрывает → «достаточно»
    fireEvent.change(input, { target: { value: "10" } });
    expect(screen.getByText(/подтверждено 10 шт · склад 20 · в пути 0 → достаточно/)).toBeInTheDocument();
  });

  it("подтверждение объёма недоступно при 0 и срабатывает после ввода количества", () => {
    render(<RegularClients />);
    fireEvent.click(screen.getByText(/СтройБаза/));

    // при нулевом объёме кнопка подтверждения заблокирована
    const confirmBtn = screen.getByRole("button", { name: "Подтвердить в демо" });
    expect(confirmBtn).toBeDisabled();

    // корректируем количество → кнопка разблокирована
    fireEvent.click(screen.getByRole("button", { name: /Скорректировать/ }));
    const input = document.querySelector('input[type="number"]') as HTMLInputElement;
    fireEvent.change(input, { target: { value: "12" } });

    const confirmBtn2 = screen.getByRole("button", { name: "Подтвердить в демо" });
    expect(confirmBtn2).not.toBeDisabled();

    fireEvent.click(confirmBtn2);

    // Отметка явно учебная, без обещания записи или передачи в закупки.
    expect(screen.getByRole("button", { name: "Отмечено в демо" })).toBeInTheDocument();
    expect(screen.getByText("в этой демонстрации")).toBeInTheDocument();
  });

  it("сворачивает раскрытую строку повторным кликом (single-open)", () => {
    render(<RegularClients />);
    const name = screen.getByText(/Белтранс/);
    fireEvent.click(name);
    expect(screen.getByText("Подтверждённый объём под закупку")).toBeInTheDocument();
    fireEvent.click(name);
    expect(screen.queryByText("Подтверждённый объём под закупку")).not.toBeInTheDocument();
  });
});
