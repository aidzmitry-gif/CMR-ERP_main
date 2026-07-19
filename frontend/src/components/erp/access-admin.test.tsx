import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

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

  it("клик по ячейке матрицы переключает доступ конкретной незаблокированной роли к модулю", () => {
    render(<AccessAdmin />);
    const row = screen.getAllByText(/Контролёр/).find((e) => e.closest("tr"))!.closest("tr") as HTMLElement;
    expect(row.textContent).toContain("· 10");

    // столбец "Финансы" — у controller его нет по умолчанию (DEFAULT_MATRIX);
    // ячейки без доступного имени — берём по индексу столбца через заголовки таблицы
    const headers = screen.getAllByRole("columnheader");
    const financeIdx = headers.findIndex((h) => h.textContent === "Финансы");
    const cells = within(row).getAllByRole("cell");
    // первая ячейка — название роли, далее по одному на модуль (индекс совпадает с MODULES)
    const targetCell = cells[financeIdx];

    fireEvent.click(targetCell);
    expect(row.textContent).toContain("· 11"); // добавили модуль

    fireEvent.click(targetCell);
    expect(row.textContent).toContain("· 10"); // вернули как было
  });

  it("«Директор» (заблокированная роль): клик по ячейке модуля не меняет счётчик", () => {
    render(<AccessAdmin />);
    const row = screen.getAllByText(/Директор/).find((e) => e.closest("tr"))!.closest("tr") as HTMLElement;
    expect(row.textContent).toContain("· 15");
    const cells = within(row).getAllByRole("cell");
    fireEvent.click(cells[1]); // первая ячейка после названия роли
    expect(row.textContent).toContain("· 15"); // без изменений — locked
  });

  it("логин можно править вручную — дальнейшая правка ФИО его больше не перегенерирует", () => {
    render(<AccessAdmin />);
    const loginInput = screen.getByPlaceholderText("ivanov_i") as HTMLInputElement;
    fireEvent.change(loginInput, { target: { value: "custom_login" } });
    expect(loginInput.value).toBe("custom_login");

    fireEvent.change(screen.getByPlaceholderText("Иванов И.И."), {
      target: { value: "Петров Пётр" },
    });
    // логин не перезаписан автогенерацией, т.к. поле уже правили руками
    expect(loginInput.value).toBe("custom_login");
  });

  it("кнопка «Добавить» заблокирована, пока не заполнены ФИО и логин", () => {
    render(<AccessAdmin />);
    const addBtn = screen.getByRole("button", { name: "Добавить" });
    expect(addBtn).toBeDisabled();

    fireEvent.change(screen.getByPlaceholderText("Иванов И.И."), {
      target: { value: "Тестов Т." },
    });
    expect(addBtn).not.toBeDisabled();
  });

  it("«Копировать» в снимке матрицы модулей пишет JSON в буфер обмена и показывает тост", () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    render(<AccessAdmin />);

    fireEvent.click(screen.getByRole("button", { name: /Сохранить снимок/ }));
    fireEvent.click(screen.getByRole("button", { name: "Копировать" }));

    expect(writeText).toHaveBeenCalledTimes(1);
    expect(writeText.mock.calls[0][0]).toContain('"director"');
  });

  it("Системные функции: выдача роли (не-админ) переключается и учитывается в счётчике «имеют функцию»", () => {
    render(<AccessAdmin />);
    fireEvent.click(screen.getByRole("button", { name: /Системные функции/ }));

    // изначально функцию имеют только 2 админа (director + commercial)
    expect(screen.getByText(/Сейчас функцию имеют:/).textContent).toContain("2");

    const controllerBtn = screen.getByRole("button", { name: "Контролёр" });
    fireEvent.click(controllerBtn);
    expect(controllerBtn.textContent).toContain("✓");
    // ни одного сотрудника с ролью controller в demo-данных нет → счётчик остаётся 2
    expect(screen.getByText(/Сейчас функцию имеют:/).textContent).toContain("2");

    fireEvent.click(controllerBtn);
    expect(controllerBtn.textContent).not.toContain("✓");
  });

  it("Системные функции: отзыв персональной выдачи (✕) убирает сотрудника из держателей", () => {
    render(<AccessAdmin />);
    fireEvent.click(screen.getByRole("button", { name: /Системные функции/ }));

    fireEvent.change(screen.getByRole("combobox"), { target: { value: "makarov" } });
    fireEvent.click(screen.getByRole("button", { name: "Выдать" }));
    expect(screen.getByText(/из них 1 — персонально/)).toBeInTheDocument();

    fireEvent.click(screen.getByTitle("Забрать функцию"));
    // персональный чип (и его кнопка отзыва) исчез — сотрудник больше не держатель функции лично
    expect(screen.queryByTitle("Забрать функцию")).toBeNull();
    expect(screen.queryByText(/персонально/)).toBeNull();
  });

  it("Системные функции: «Сохранить снимок» отдаёт JSON с выданными ролями/пользователями", () => {
    render(<AccessAdmin />);
    fireEvent.click(screen.getByRole("button", { name: /Системные функции/ }));

    fireEvent.click(screen.getByRole("button", { name: "Контролёр" }));
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "makarov" } });
    fireEvent.click(screen.getByRole("button", { name: "Выдать" }));

    fireEvent.click(screen.getByRole("button", { name: /Сохранить снимок/ }));
    const pre = document.querySelector("pre") as HTMLElement;
    const parsed = JSON.parse(pre.textContent ?? "{}");
    expect(parsed.purge_marked.roles).toEqual(expect.arrayContaining(["director", "commercial", "controller"]));
    expect(parsed.purge_marked.users).toEqual(["makarov"]);
  });
});
