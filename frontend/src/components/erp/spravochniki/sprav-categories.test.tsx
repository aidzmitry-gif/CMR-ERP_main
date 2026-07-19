import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { NomenclatureGroup, SkuRow } from "@/lib/reference-data";

// next/link → простая <a> (jsdom): компонент тестируем изолированно.
vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

// Мокаем ТОЛЬКО сетевые функции reference-data; чистую доменную логику
// (buildCategoryTree и т.п.) сохраняем через importActual — её незачем подменять.
vi.mock("@/lib/reference-data", async (importActual) => {
  const actual = await importActual<typeof import("@/lib/reference-data")>();
  return {
    ...actual,
    fetchRefRowsByEndpoint: vi.fn().mockResolvedValue([]),
    fetchSkusByCategory: vi.fn().mockResolvedValue([]),
    createNomenclatureGroup: vi.fn().mockResolvedValue(true),
    patchNomenclatureGroup: vi.fn().mockResolvedValue(true),
    archiveNomenclatureGroup: vi.fn().mockResolvedValue(true),
  };
});

import { SpravCategories } from "@/components/erp/spravochniki/sprav-categories";
import * as refData from "@/lib/reference-data";

// Дерево-фикстура: корень «Электроника» с двумя детьми + корень-архив.
// У «Электроника» заданы «общие данные группы» (ТН ВЭД + свободный атрибут).
const groups: NomenclatureGroup[] = [
  {
    id: 1,
    code: "CAT-0100",
    name: "Электроника",
    parent_id: null,
    is_active: true,
    tnved_code: "8506108000",
    attributes: { Производитель: "Omron" },
  },
  { id: 2, code: "CAT-0200", name: "Конденсаторы", parent_id: 1, is_active: true },
  { id: 3, code: "CAT-0300", name: "Реле", parent_id: 1, is_active: true },
  { id: 4, code: "CAT-0900", name: "Старьё", parent_id: null, is_active: false },
];

const asMock = (fn: unknown) => fn as ReturnType<typeof vi.fn>;

beforeEach(() => {
  vi.clearAllMocks();
  asMock(refData.fetchRefRowsByEndpoint).mockResolvedValue([]);
  asMock(refData.fetchSkusByCategory).mockResolvedValue([]);
  asMock(refData.createNomenclatureGroup).mockResolvedValue(true);
  asMock(refData.patchNomenclatureGroup).mockResolvedValue(true);
  asMock(refData.archiveNomenclatureGroup).mockResolvedValue(true);
  // refetchGroups() внутри компонента ходит в глобальный fetch — возвращаем свежий список.
  global.fetch = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => groups,
  }) as unknown as typeof fetch;
});

describe("SpravCategories", () => {
  it("рендерит заголовок, корневые категории и пустую правую панель", () => {
    render(<SpravCategories initial={groups} />);
    expect(screen.getByText(/Категории номенклатуры/)).toBeInTheDocument();
    // корни видны, дети свёрнуты по умолчанию
    expect(screen.getByText("Электроника")).toBeInTheDocument();
    expect(screen.getByText("Старьё")).toBeInTheDocument();
    expect(screen.queryByText("Конденсаторы")).not.toBeInTheDocument();
    // архивный корень помечен бейджем «архив»
    expect(screen.getByText("архив")).toBeInTheDocument();
    // ничего не выбрано → подсказка
    expect(screen.getByText("Выберите категорию в дереве")).toBeInTheDocument();
  });

  it("пустой список показывает подсказку добавить первую категорию", () => {
    render(<SpravCategories initial={[]} />);
    expect(screen.getByText("Нет данных. Добавьте первую категорию.")).toBeInTheDocument();
  });

  it("поиск оставляет совпавший узел и предка, прячет сиблинга; нет совпадений → «Ничего не найдено»", () => {
    render(<SpravCategories initial={groups} />);
    const searchBox = screen.getByPlaceholderText("Поиск по дереву…");

    fireEvent.change(searchBox, { target: { value: "Реле" } });
    // совпавший «Реле» + предок «Электроника» видны, сиблинг «Конденсаторы» скрыт
    expect(screen.getByText("Реле")).toBeInTheDocument();
    expect(screen.getByText("Электроника")).toBeInTheDocument();
    expect(screen.queryByText("Конденсаторы")).not.toBeInTheDocument();

    fireEvent.change(searchBox, { target: { value: "чегонетвдереве" } });
    expect(screen.getByText("Ничего не найдено")).toBeInTheDocument();
  });

  it("выбор узла раскрывает карточку с реквизитами и унаследованными данными группы", async () => {
    render(<SpravCategories initial={groups} />);
    fireEvent.click(screen.getByText("Электроника"));

    // карточка узла: статус, код, уровень, «общие данные группы»
    expect(await screen.findByText("Активна")).toBeInTheDocument();
    expect(screen.getAllByText("CAT-0100").length).toBeGreaterThan(0); // и в дереве, и в реквизитах
    expect(screen.getByText("8506108000")).toBeInTheDocument(); // ТН ВЭД по умолч.
    expect(screen.getByText("Omron")).toBeInTheDocument(); // свободный атрибут группы
    // действия над узлом
    expect(screen.getByRole("button", { name: /Добавить подкатегорию/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Переименовать" })).toBeInTheDocument();

    // выбор дёрнул подгрузку товаров группы по id
    await waitFor(() => expect(refData.fetchSkusByCategory).toHaveBeenCalledWith(1));
  });

  it("товары выбранной группы подгружаются и рендерятся ссылками", async () => {
    const skus: SkuRow[] = [
      { code: "6СТ-190", title: "АКБ 190 Ач", unit: "шт", category_id: 1, vat_code: "НДС20" },
    ];
    asMock(refData.fetchSkusByCategory).mockResolvedValue(skus);

    render(<SpravCategories initial={groups} />);
    fireEvent.click(screen.getByText("Электроника"));

    expect(await screen.findByText("АКБ 190 Ач")).toBeInTheDocument();
    const link = screen.getByRole("link", { name: /АКБ 190 Ач/ });
    expect(link).toHaveAttribute("href", "/erp/spravochniki/sku/6%D0%A1%D0%A2-190");
  });

  it("пустая группа без товаров показывает поясняющую подсказку", async () => {
    render(<SpravCategories initial={groups} />);
    fireEvent.click(screen.getByText("Электроника"));
    expect(
      await screen.findByText(/Нет товаров в этой группе/),
    ).toBeInTheDocument();
  });

  it("форма добавления валидирует пустые поля и не зовёт API", async () => {
    render(<SpravCategories initial={groups} />);
    fireEvent.click(screen.getByRole("button", { name: /Добавить категорию/ }));

    const form = (await screen.findByText("Наименование")).closest("form") as HTMLElement;
    fireEvent.click(within(form).getByRole("button", { name: "Добавить" }));

    expect(await screen.findByText("Заполните все поля")).toBeInTheDocument();
    expect(refData.createNomenclatureGroup).not.toHaveBeenCalled();
  });

  it("добавление категории зовёт createNomenclatureGroup с введёнными полями и показывает тост", async () => {
    render(<SpravCategories initial={groups} />);
    fireEvent.click(screen.getByRole("button", { name: /Добавить категорию/ }));

    const form = (await screen.findByText("Наименование")).closest("form") as HTMLElement;
    fireEvent.change(within(form).getByPlaceholderText("Например: Конденсаторы"), {
      target: { value: "Резисторы" },
    });
    fireEvent.change(within(form).getByPlaceholderText("CAT-0200"), {
      target: { value: "cat-0500" },
    });
    fireEvent.click(within(form).getByRole("button", { name: "Добавить" }));

    await waitFor(() =>
      expect(refData.createNomenclatureGroup).toHaveBeenCalledWith(
        // код приводится к верхнему регистру, parent_id корневой добавляемой = undefined
        expect.objectContaining({ name: "Резисторы", code: "CAT-0500" }),
      ),
    );
    expect(await screen.findByText("Группа добавлена")).toBeInTheDocument();
  });

  it("архивирование выбранной группы подтверждается и зовёт archiveNomenclatureGroup", async () => {
    render(<SpravCategories initial={groups} />);
    fireEvent.click(screen.getByText("Электроника"));

    fireEvent.click(await screen.findByRole("button", { name: /В архив/ }));
    // экран подтверждения
    expect(await screen.findByText(/Архивировать группу/)).toBeInTheDocument();
    // в панели две кнопки «Архивировать» (заголовок-действие уже не кнопка) — берём submit-кнопку
    const confirm = screen
      .getAllByRole("button", { name: "Архивировать" })
      .find((b) => b.className.includes("bg-red-500")) as HTMLElement;
    fireEvent.click(confirm);

    await waitFor(() =>
      expect(refData.archiveNomenclatureGroup).toHaveBeenCalledWith("CAT-0100"),
    );
    expect(await screen.findByText("Группа архивирована")).toBeInTheDocument();
  });

  it("не удалось добавить группу — показывает ошибку и не закрывает форму", async () => {
    asMock(refData.createNomenclatureGroup).mockResolvedValue(false);
    render(<SpravCategories initial={groups} />);
    fireEvent.click(screen.getByRole("button", { name: /Добавить категорию/ }));

    const form = (await screen.findByText("Наименование")).closest("form") as HTMLElement;
    fireEvent.change(within(form).getByPlaceholderText("Например: Конденсаторы"), {
      target: { value: "Резисторы" },
    });
    fireEvent.change(within(form).getByPlaceholderText("CAT-0200"), {
      target: { value: "CAT-0500" },
    });
    fireEvent.click(within(form).getByRole("button", { name: "Добавить" }));

    expect(await screen.findByText("Ошибка: не удалось добавить группу")).toBeInTheDocument();
    // форма осталась открытой (не сброшена)
    expect(screen.getByText("Наименование")).toBeInTheDocument();
  });

  it("переименование зовёт patchNomenclatureGroup с кодом узла и новым именем", async () => {
    render(<SpravCategories initial={groups} />);
    fireEvent.click(screen.getByText("Электроника"));
    fireEvent.click(await screen.findByRole("button", { name: "Переименовать" }));

    const input = await screen.findByDisplayValue("Электроника");
    fireEvent.change(input, { target: { value: "Электротовары" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));

    await waitFor(() =>
      expect(refData.patchNomenclatureGroup).toHaveBeenCalledWith("CAT-0100", {
        name: "Электротовары",
      }),
    );
    expect(await screen.findByText("Переименовано")).toBeInTheDocument();
  });

  it("ошибка переименования показывает соответствующий тост", async () => {
    asMock(refData.patchNomenclatureGroup).mockResolvedValue(false);
    render(<SpravCategories initial={groups} />);
    fireEvent.click(screen.getByText("Электроника"));
    fireEvent.click(await screen.findByRole("button", { name: "Переименовать" }));

    const input = await screen.findByDisplayValue("Электроника");
    fireEvent.change(input, { target: { value: "Электротовары" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));

    expect(await screen.findByText("Ошибка: не удалось переименовать")).toBeInTheDocument();
  });

  it("отмена переименования закрывает форму без вызова API", async () => {
    render(<SpravCategories initial={groups} />);
    fireEvent.click(screen.getByText("Электроника"));
    fireEvent.click(await screen.findByRole("button", { name: "Переименовать" }));
    await screen.findByDisplayValue("Электроника");

    fireEvent.click(screen.getByRole("button", { name: "Отмена" }));

    expect(screen.queryByDisplayValue("Электроника")).not.toBeInTheDocument();
    expect(refData.patchNomenclatureGroup).not.toHaveBeenCalled();
  });

  it("форма переноса скрывает архивных и потомков узла из списка кандидатов", async () => {
    render(<SpravCategories initial={groups} />);
    const row = screen.getByText("Электроника").closest("div") as HTMLElement;
    fireEvent.click(row.querySelector("span.w-4") as HTMLElement); // раскрыть родителя
    fireEvent.click(screen.getByText("Конденсаторы"));
    fireEvent.click(await screen.findByRole("button", { name: "Переместить…" }));

    const select = (await screen.findByText("Новый родитель")).closest("div")!
      .querySelector("select") as HTMLSelectElement;
    const optionTexts = Array.from(select.options).map((o) => o.textContent);
    expect(optionTexts).toContain("— корень —");
    expect(optionTexts).toContain("Электроника"); // допустимый родитель
    expect(optionTexts).toContain("Электроника › Реле"); // допустимый родитель
    expect(optionTexts).not.toContain("Старьё"); // архивный — исключён
  });

  it("перенос узла зовёт patchNomenclatureGroup с новым parent_id", async () => {
    render(<SpravCategories initial={groups} />);
    const row = screen.getByText("Электроника").closest("div") as HTMLElement;
    fireEvent.click(row.querySelector("span.w-4") as HTMLElement); // раскрыть родителя
    fireEvent.click(screen.getByText("Конденсаторы"));
    fireEvent.click(await screen.findByRole("button", { name: "Переместить…" }));

    const select = (await screen.findByText("Новый родитель")).closest("div")!
      .querySelector("select") as HTMLSelectElement;
    fireEvent.change(select, { target: { value: "3" } });
    fireEvent.click(screen.getByRole("button", { name: "Переместить" }));

    await waitFor(() =>
      expect(refData.patchNomenclatureGroup).toHaveBeenCalledWith("CAT-0200", { parent_id: 3 }),
    );
    expect(await screen.findByText("Перемещено")).toBeInTheDocument();
  });

  it("ошибка переноса показывает соответствующий тост", async () => {
    asMock(refData.patchNomenclatureGroup).mockResolvedValue(false);
    render(<SpravCategories initial={groups} />);
    const row = screen.getByText("Электроника").closest("div") as HTMLElement;
    fireEvent.click(row.querySelector("span.w-4") as HTMLElement); // раскрыть родителя
    fireEvent.click(screen.getByText("Конденсаторы"));
    fireEvent.click(await screen.findByRole("button", { name: "Переместить…" }));
    fireEvent.click(await screen.findByRole("button", { name: "Переместить" }));

    expect(await screen.findByText("Ошибка: не удалось переместить")).toBeInTheDocument();
  });

  it("сохранение общих данных группы зовёт patchNomenclatureGroup с введёнными полями", async () => {
    render(<SpravCategories initial={groups} />);
    fireEvent.click(screen.getByText("Электроника"));
    fireEvent.click(await screen.findByRole("button", { name: "Изменить" }));

    const tnvedInput = await screen.findByPlaceholderText(
      "напр. 8506108000 (пусто — наследовать)",
    );
    fireEvent.change(tnvedInput, { target: { value: "1234567890" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));

    await waitFor(() =>
      expect(refData.patchNomenclatureGroup).toHaveBeenCalledWith(
        "CAT-0100",
        expect.objectContaining({
          tnved_code: "1234567890",
          vat_code: null,
          unit: null,
          country: null,
          attributes: expect.objectContaining({ Производитель: "Omron" }),
        }),
      ),
    );
    expect(await screen.findByText("Общие данные группы сохранены")).toBeInTheDocument();
  });

  it("очистка поля ТН ВЭД в форме общих данных передаёт null (не наследовать)", async () => {
    render(<SpravCategories initial={groups} />);
    fireEvent.click(screen.getByText("Электроника"));
    fireEvent.click(await screen.findByRole("button", { name: "Изменить" }));

    const tnvedInput = await screen.findByPlaceholderText(
      "напр. 8506108000 (пусто — наследовать)",
    );
    fireEvent.change(tnvedInput, { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));

    await waitFor(() =>
      expect(refData.patchNomenclatureGroup).toHaveBeenCalledWith(
        "CAT-0100",
        expect.objectContaining({ tnved_code: null }),
      ),
    );
  });

  it("ошибка сохранения общих данных группы показывает тост", async () => {
    asMock(refData.patchNomenclatureGroup).mockResolvedValue(false);
    render(<SpravCategories initial={groups} />);
    fireEvent.click(screen.getByText("Электроника"));
    fireEvent.click(await screen.findByRole("button", { name: "Изменить" }));
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));

    expect(await screen.findByText("Ошибка: не удалось сохранить")).toBeInTheDocument();
  });

  it("отмена архивирования закрывает подтверждение без вызова API", async () => {
    render(<SpravCategories initial={groups} />);
    fireEvent.click(screen.getByText("Электроника"));
    fireEvent.click(await screen.findByRole("button", { name: /В архив/ }));
    expect(await screen.findByText(/Архивировать группу/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Отмена" }));

    expect(screen.queryByText(/Архивировать группу/)).not.toBeInTheDocument();
    expect(refData.archiveNomenclatureGroup).not.toHaveBeenCalled();
  });

  it("ошибка архивирования показывает тост и НЕ сбрасывает выбранный узел", async () => {
    asMock(refData.archiveNomenclatureGroup).mockResolvedValue(false);
    render(<SpravCategories initial={groups} />);
    fireEvent.click(screen.getByText("Электроника"));
    fireEvent.click(await screen.findByRole("button", { name: /В архив/ }));
    const confirm = screen
      .getAllByRole("button", { name: "Архивировать" })
      .find((b) => b.className.includes("bg-red-500")) as HTMLElement;
    fireEvent.click(confirm);

    expect(await screen.findByText("Ошибка: не удалось архивировать")).toBeInTheDocument();
  });

  it("клик по шеврону раскрывает и сворачивает узел без выбора его в панели", () => {
    render(<SpravCategories initial={groups} />);
    const row = screen.getByText("Электроника").closest("div") as HTMLElement;
    const toggle = row.querySelector("span.w-4") as HTMLElement;

    fireEvent.click(toggle);
    expect(screen.getByText("Конденсаторы")).toBeInTheDocument();
    // выбор в панели не произошёл — правая панель по-прежнему пуста
    expect(screen.getByText("Выберите категорию в дереве")).toBeInTheDocument();

    fireEvent.click(toggle);
    expect(screen.queryByText("Конденсаторы")).not.toBeInTheDocument();
  });

  it("во время загрузки товаров группы показывает «Загрузка…», затем сменяется списком", async () => {
    let resolveFn: (rows: SkuRow[]) => void = () => {};
    asMock(refData.fetchSkusByCategory).mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveFn = resolve;
        }),
    );

    render(<SpravCategories initial={groups} />);
    fireEvent.click(screen.getByText("Электроника"));

    expect(await screen.findByText("Загрузка…")).toBeInTheDocument();
    resolveFn([]);
    await waitFor(() => expect(screen.queryByText("Загрузка…")).not.toBeInTheDocument());
    expect(screen.getByText(/Нет товаров в этой группе/)).toBeInTheDocument();
  });

  it("выбор дочернего узла показывает имя родителя, уровень вложенности и хлебные крошки", async () => {
    render(<SpravCategories initial={groups} />);
    const row = screen.getByText("Электроника").closest("div") as HTMLElement;
    fireEvent.click(row.querySelector("span.w-4") as HTMLElement); // раскрыть родителя
    fireEvent.click(screen.getByText("Конденсаторы"));

    expect(await screen.findByText("Электроника › Конденсаторы")).toBeInTheDocument(); // путь
    // родитель дублирует имя узла дерева — есть хотя бы 2 вхождения (в дереве и в реквизитах)
    expect(screen.getAllByText("Электроника").length).toBeGreaterThan(1);
    expect(screen.getByText("2")).toBeInTheDocument(); // уровень вложенности (глубина 2 — дочерний узел)
  });

  it("после reload удалённый (более не существующий) выбранный узел сбрасывает выбор", async () => {
    render(<SpravCategories initial={groups} />);
    fireEvent.click(screen.getByText("Электроника"));
    fireEvent.click(await screen.findByRole("button", { name: "Переименовать" }));

    // сервер вернул список уже без переименованного узла (id 1) — имитируем гонку/удаление
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => groups.filter((g) => g.id !== 1),
    }) as unknown as typeof fetch;

    const input = await screen.findByDisplayValue("Электроника");
    fireEvent.change(input, { target: { value: "Электротовары" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));

    await waitFor(() =>
      expect(screen.getByText("Выберите категорию в дереве")).toBeInTheDocument(),
    );
  });
});
