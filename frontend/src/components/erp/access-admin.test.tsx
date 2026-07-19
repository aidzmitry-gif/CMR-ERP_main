import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

// Компонент чисто клиентский и работает на статичном снимке (lib/access-admin-data.ts) —
// внешних data-fetch/router-зависимостей нет, мокать нечего.
import { AccessAdmin } from "@/components/erp/access-admin";

describe("AccessAdmin", () => {
  it("рендерит шапку, вкладки (с бейджем «скоро») и матрицу ролей/модулей по умолчанию", () => {
    render(<AccessAdmin />);

    expect(screen.getByRole("heading", { name: "Управление доступом" })).toBeInTheDocument();

    // готовые и «будущие» вкладки
    expect(screen.getByRole("button", { name: /Доступ к модулям/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Системные функции/ })).toBeInTheDocument();
    const granular = screen.getByRole("button", { name: /Гранулярные права/ });
    expect(granular).toBeDisabled();
    expect(screen.getAllByText("скоро").length).toBe(3); // три ненастроенных уровня

    // строки-роли и столбцы-модули
    expect(screen.getAllByText(/Контролёр/).length).toBeGreaterThan(0);
    expect(screen.getByText("CRM (продажи)")).toBeInTheDocument();
    // сотрудник виден в подписи своей роли (Финансы / офис — Жуковская)
    expect(screen.getByText(/Жуковская О\.Н\./)).toBeInTheDocument();
  });

  it("кнопки «очистить» и «все» в строке роли меняют счётчик доступных модулей", () => {
    render(<AccessAdmin />);
    // controller по умолчанию имеет 10 модулей
    const row = screen.getAllByText(/Контролёр/).find((e) => e.closest("tr"))!.closest("tr") as HTMLElement;
    expect(row.textContent).toContain("· 10");

    fireEvent.click(within(row).getByRole("button", { name: "очистить" }));
    expect(row.textContent).toContain("· 0");

    fireEvent.click(within(row).getByRole("button", { name: "все" }));
    expect(row.textContent).toContain("· 15"); // всего 15 модулей
  });

  it("строка заблокированной роли «Директор» не даёт кнопок редактирования доступа", () => {
    render(<AccessAdmin />);
    const row = screen.getAllByText(/Директор/).find((e) => e.closest("tr"))!.closest("tr") as HTMLElement;
    // директор — locked super-role: доступ править нельзя
    expect(within(row).queryByRole("button", { name: "все" })).toBeNull();
    expect(within(row).queryByRole("button", { name: "очистить" })).toBeNull();
    // и у него всегда полный набор
    expect(row.textContent).toContain("· 15");
  });

  it("«Сбросить к предложенному» возвращает изменённую строку и показывает тост", () => {
    render(<AccessAdmin />);
    const row = screen.getAllByText(/Контролёр/).find((e) => e.closest("tr"))!.closest("tr") as HTMLElement;
    fireEvent.click(within(row).getByRole("button", { name: "очистить" }));
    expect(row.textContent).toContain("· 0");

    fireEvent.click(screen.getByRole("button", { name: /Сбросить к предложенному/ }));
    expect(screen.getByText("Сброшено к предложенному")).toBeInTheDocument();
    expect(row.textContent).toContain("· 10"); // восстановлено
  });

  it("быстрое добавление: логин автогенерится из ФИО, сотрудник попадает в матрицу", () => {
    render(<AccessAdmin />);
    fireEvent.change(screen.getByPlaceholderText("Иванов И.И."), {
      target: { value: "Сидоров Пётр" },
    });
    // логин собран транслитом: фамилия + инициал → sidorov_p
    const loginInput = screen.getByPlaceholderText("ivanov_i") as HTMLInputElement;
    expect(loginInput.value).toBe("sidorov_p");

    fireEvent.click(screen.getByRole("button", { name: "Добавить" }));
    expect(screen.getByText("Добавлен: Сидоров Пётр")).toBeInTheDocument();
    // видно и в тосте, и в подписи роли «Продажи» (роль по умолчанию)
    expect(screen.getAllByText(/Сидоров Пётр/).length).toBeGreaterThan(1);
  });

  it("занятый логин не добавляет дубль, а предупреждает", () => {
    render(<AccessAdmin />);
    // «Макаров» → логин makarov, который уже есть в снимке сотрудников
    fireEvent.change(screen.getByPlaceholderText("Иванов И.И."), {
      target: { value: "Макаров" },
    });
    expect((screen.getByPlaceholderText("ivanov_i") as HTMLInputElement).value).toBe("makarov");
    fireEvent.click(screen.getByRole("button", { name: "Добавить" }));
    expect(screen.getByText("Логин уже занят — поправьте")).toBeInTheDocument();
  });

  it("«Сохранить снимок» показывает JSON матрицы с ролями и модулями", () => {
    render(<AccessAdmin />);
    expect(document.querySelector("pre")).toBeNull(); // до нажатия снимка нет

    fireEvent.click(screen.getByRole("button", { name: /Сохранить снимок/ }));
    expect(screen.getByText(/Снимок матрицы \(JSON\)/)).toBeInTheDocument();

    const pre = document.querySelector("pre") as HTMLElement;
    expect(pre.textContent).toContain('"director"');
    expect(pre.textContent).toContain('"home"');
  });

  it("вкладка «Системные функции»: карточка права и поимённая выдача сотруднику", () => {
    render(<AccessAdmin />);
    fireEvent.click(screen.getByRole("button", { name: /Системные функции/ }));

    // карточка деструктивного спец-права
    expect(screen.getByRole("heading", { name: "Удаление помеченных объектов" })).toBeInTheDocument();
    expect(screen.getByText("purge_marked")).toBeInTheDocument();
    expect(screen.getByText("необратимо")).toBeInTheDocument();
    // администратор всегда имеет функцию — кнопка роли заблокирована
    expect(screen.getByRole("button", { name: /Директор · админ/ })).toBeDisabled();

    // выдаём функцию конкретному сотруднику → появляется персональный чип
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "makarov" } });
    fireEvent.click(screen.getByRole("button", { name: "Выдать" }));
    expect(screen.getByText(/Макаров/)).toBeInTheDocument();
    expect(screen.getByText(/из них 1 — персонально/)).toBeInTheDocument();
  });
});
