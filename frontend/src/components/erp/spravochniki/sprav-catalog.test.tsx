import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// next/link → простая <a> в jsdom (роутер App Router в тесте недоступен).
vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

import { SpravCatalog } from "@/components/erp/spravochniki/sprav-catalog";
import type { ReferenceCatalog, ReferenceMeta } from "@/lib/reference-data";

// crud-справочник: endpoint под /system/refs/ → строки тянутся GET /api<endpoint>.
const unitsRef: ReferenceMeta = {
  key: "core.units",
  title: "Единицы измерения",
  module: "core",
  endpoint: "/system/refs/units",
  owner_schema: "public",
  columns: [
    { name: "code", label: "Код", type: "string", editable: true, semantic: "" },
    { name: "title", label: "Наименование", type: "string", editable: true, semantic: "" },
    { name: "is_active", label: "Статус", type: "bool", editable: true, semantic: "" },
  ],
  permissions: ["reference.read"],
  archivable: true,
  versioned: false,
  ai_exposed: false,
  description: "Справочник единиц",
};

const banksRef: ReferenceMeta = {
  key: "core.banks",
  title: "Банки",
  module: "core",
  endpoint: "/system/refs/banks",
  owner_schema: "public",
  columns: [
    { name: "code", label: "Код", type: "string", editable: true, semantic: "" },
    { name: "title", label: "Наименование", type: "string", editable: true, semantic: "" },
    { name: "is_active", label: "Статус", type: "bool", editable: true, semantic: "" },
  ],
  permissions: [],
  archivable: false,
  versioned: false,
  ai_exposed: false,
  description: "Банки-получатели",
};

// lookup-only: endpoint НЕ под /system/refs/ + ключ из LOOKUP_ONLY_KEYS →
// список целиком не выгружается, экран рисует пояснение вместо таблицы.
const counterpartyRef: ReferenceMeta = {
  key: "core.counterparties",
  title: "Контрагенты",
  module: "core",
  endpoint: "/system/mdm/counterparties",
  owner_schema: "public",
  columns: [],
  permissions: [],
  archivable: false,
  versioned: false,
  ai_exposed: true,
  description: "Golden record контрагентов",
};

const catalog: ReferenceCatalog = {
  departments: {
    Общие: [unitsRef, banksRef],
    Продажи: [counterpartyRef],
  },
};

const unitRows: Record<string, unknown>[] = [
  { id: 1, code: "шт", title: "Штука", is_active: true },
  { id: 2, code: "кг", title: "Килограмм", is_active: false },
  { id: 3, code: "л", title: null, is_active: true },
];

function okJson(payload: unknown) {
  return { ok: true, json: async () => payload } as Response;
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(okJson([])));
});

afterEach(() => vi.unstubAllGlobals());

describe("SpravCatalog", () => {
  it("рендерит хаб-ссылки, дерево отделов и таблицу выбранного справочника", () => {
    render(<SpravCatalog catalog={catalog} initialRef={unitsRef} initialRows={unitRows} />);

    // инфо-баннер и хаб-навигация
    expect(screen.getByText("Как это устроено:")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /Номенклатура \(SKU\)/ }),
    ).toHaveAttribute("href", "/erp/spravochniki/sku");

    // дерево: отделы в каноническом порядке (Общие раньше Продаж)
    expect(screen.getByText(/Общие/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Банки" })).toBeInTheDocument();

    // таблица выбранного справочника: заголовки колонок + строки
    expect(screen.getByRole("heading", { name: /Единицы измерения/ })).toBeInTheDocument();
    expect(screen.getByText("Наименование")).toBeInTheDocument();
    expect(screen.getByText("Штука")).toBeInTheDocument();
    expect(screen.getByText("Килограмм")).toBeInTheDocument();
  });

  it("пустой каталог показывает «Каталог недоступен» и подсказку выбрать справочник", () => {
    render(<SpravCatalog catalog={{ departments: {} }} initialRef={null} initialRows={[]} />);
    expect(screen.getByText("Каталог недоступен")).toBeInTheDocument();
    expect(screen.getByText(/Выберите справочник в дереве слева/)).toBeInTheDocument();
    // таблицы нет — заголовок справочника не отрисован
    expect(screen.queryByText("Наименование")).not.toBeInTheDocument();
  });

  it("столбец is_active рендерит бейджи «Активен»/«Архив», а null-значение — тире", () => {
    render(<SpravCatalog catalog={catalog} initialRef={unitsRef} initialRows={unitRows} />);
    // 2 активные строки (шт, л) + 1 архивная (кг)
    expect(screen.getAllByText("Активен")).toHaveLength(2);
    expect(screen.getByText("Архив")).toBeInTheDocument();
    // null в колонке «Наименование» показывается как «—» (не пусто, не "null")
    expect(screen.getByText("—")).toBeInTheDocument();
    expect(screen.queryByText("null")).not.toBeInTheDocument();
  });

  it("поиск по таблице фильтрует строки по значению (регистронезависимо) и показывает «Ничего не найдено»", () => {
    render(<SpravCatalog catalog={catalog} initialRef={unitsRef} initialRows={unitRows} />);
    const search = screen.getByPlaceholderText("Поиск по таблице…");

    // регистронезависимо: «штука» находит «Штука», прочие строки скрыты
    fireEvent.change(search, { target: { value: "штука" } });
    expect(screen.getByText("Штука")).toBeInTheDocument();
    expect(screen.queryByText("Килограмм")).not.toBeInTheDocument();

    // нет совпадений → строка-заглушка
    fireEvent.change(search, { target: { value: "zzz-нет-такого" } });
    expect(screen.queryByText("Штука")).not.toBeInTheDocument();
    expect(screen.getByText("Ничего не найдено")).toBeInTheDocument();
  });

  it("поиск по дереву фильтрует справочники по названию и показывает «Ничего не найдено»", () => {
    render(<SpravCatalog catalog={catalog} initialRef={null} initialRows={[]} />);
    const treeSearch = screen.getByPlaceholderText("Найти справочник…");

    // до фильтра — все справочники в дереве
    expect(screen.getByRole("button", { name: "Единицы измерения" })).toBeInTheDocument();

    fireEvent.change(treeSearch, { target: { value: "банк" } });
    expect(screen.getByRole("button", { name: "Банки" })).toBeInTheDocument();
    // не совпавшие по названию — исчезли (и их отдел свернулся)
    expect(screen.queryByRole("button", { name: "Единицы измерения" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Контрагенты" })).not.toBeInTheDocument();

    fireEvent.change(treeSearch, { target: { value: "zzz-нет" } });
    expect(screen.getByText("Ничего не найдено")).toBeInTheDocument();
  });

  it("клик по crud-справочнику в дереве тянет строки через /api-прокси и рендерит их", async () => {
    const bankRows = [
      { id: 10, code: "ALFABY2X", title: "Альфа-Банк", is_active: true },
    ];
    const fetchMock = vi.fn().mockResolvedValue(okJson(bankRows));
    vi.stubGlobal("fetch", fetchMock);

    render(<SpravCatalog catalog={catalog} initialRef={null} initialRows={[]} />);
    // до выбора — пустое состояние
    expect(screen.getByText(/Выберите справочник в дереве слева/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Банки" }));

    // строки подгрузились и отрисовались
    expect(await screen.findByText("Альфа-Банк")).toBeInTheDocument();
    // фетч ушёл именно на прокси-путь /api<endpoint>
    expect(fetchMock).toHaveBeenCalledWith("/api/system/refs/banks");
    // заголовок сменился на выбранный справочник
    expect(screen.getByRole("heading", { name: /Банки/ })).toBeInTheDocument();
  });

  it("справочник lookup-only показывает пояснение вместо таблицы (список не выгружается)", () => {
    render(
      <SpravCatalog catalog={catalog} initialRef={counterpartyRef} initialRows={[]} />,
    );
    expect(screen.getByText(/Данные у владельца/)).toBeInTheDocument();
    // структурной таблицы нет — нет строки-заглушки «Нет данных»
    expect(screen.queryByText("Нет данных")).not.toBeInTheDocument();
  });

  it("ошибка загрузки строк (не-200) деградирует в «Нет данных», а не падает", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: false, json: async () => ({}) } as Response);
    vi.stubGlobal("fetch", fetchMock);

    render(<SpravCatalog catalog={catalog} initialRef={null} initialRows={[]} />);
    fireEvent.click(screen.getByRole("button", { name: "Банки" }));

    // выбор применился (заголовок), но строк нет → заглушка «Нет данных»
    expect(await screen.findByRole("heading", { name: /Банки/ })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("Нет данных")).toBeInTheDocument());
    expect(fetchMock).toHaveBeenCalledWith("/api/system/refs/banks");
  });
});
