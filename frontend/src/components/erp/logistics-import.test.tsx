import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// Мокаем только сетевые фетчи слоя logistics-api; остальное (patchImportStage для drawer,
// типы) берём из реального модуля. Чистые хелперы (totalFreightByn, formatByn) НЕ мокаем —
// пусть считают/форматируют по-настоящему: их результат и есть тестируемое поведение.
vi.mock("@/lib/logistics-api", async (importActual) => {
  const actual = await importActual<typeof import("@/lib/logistics-api")>();
  return {
    ...actual,
    fetchImportBoard: vi.fn(),
    fetchImports: vi.fn(),
  };
});

import { LogisticsImport } from "@/components/erp/logistics-import";
import * as api from "@/lib/logistics-api";
import type {
  ImportBoard,
  ImportShipment,
} from "@/lib/logistics-api";
import type { FunnelCard, FunnelStage } from "@/lib/types";

function card(over: Partial<FunnelCard> = {}): FunnelCard {
  return {
    id: 1,
    code: "IMP-1",
    title: "Контейнер",
    subtitle: "поставка",
    flag: "🇨🇳",
    amount: null,
    priority: "",
    status_tag: "",
    owner: "",
    date: "",
    progress: null,
    next_step: "",
    insight: "",
    tags: [],
    ...over,
  };
}

function stage(id: string, title: string, count: number, cards: FunnelCard[] = []): FunnelStage {
  return { id, title, color: "#94A3B8", count, sum: 0, cards };
}

function imp(over: Partial<ImportShipment> = {}): ImportShipment {
  return {
    id: 1,
    number: "IMP-0001",
    supplier: "Shenzhen Co",
    flag: "🇨🇳",
    container_no: "ABCU1234567",
    route: "Шэньчжэнь → Минск",
    incoterms: "FOB",
    mode: "sea",
    cargo: "АКБ 190",
    qty: 100,
    amount: 12000,
    priority: "Средний",
    owner: "Иванов",
    stage: "warehouse",
    customs_status: "",
    eta: null,
    po_ref: "PO-7",
    ...over,
  };
}

// Полная доска: 9 поставок, из них в движении (не factory/warehouse) — 5, на таможне 1, принято 2.
function fullBoard(cards: FunnelCard[] = []): ImportBoard {
  return {
    stages: [
      stage("factory", "Фабрика", 2),
      stage("consolidation", "Консолидация", 1),
      stage("in_transit", "В пути", 3, cards),
      stage("customs", "Таможня", 1),
      stage("warehouse", "Приёмка на склад", 2),
    ],
  };
}

const mockBoard = api.fetchImportBoard as ReturnType<typeof vi.fn>;
const mockImports = api.fetchImports as ReturnType<typeof vi.fn>;

beforeEach(() => vi.clearAllMocks());

describe("LogisticsImport", () => {
  it("показывает индикатор загрузки, затем KPI после ответа бэкенда", async () => {
    mockBoard.mockResolvedValue(fullBoard());
    mockImports.mockResolvedValue([]);
    render(<LogisticsImport />);

    // синхронно после маунта фетч ещё не завершён → индикатор загрузки
    expect(screen.getByText("Загрузка…")).toBeInTheDocument();

    // после резолва промисов — панель с KPI
    expect(await screen.findByText("Всего поставок")).toBeInTheDocument();
    expect(screen.queryByText("Загрузка…")).not.toBeInTheDocument();
  });

  it("сбой доски (null) показывает честную ошибку, а не пустые нули", async () => {
    mockBoard.mockResolvedValue(null); // backend недоступен
    mockImports.mockResolvedValue([]);
    render(<LogisticsImport />);

    expect(await screen.findByText(/Не удалось загрузить цепочку импорта/)).toBeInTheDocument();
    // не притворяемся, что данные есть: KPI-плиток нет
    expect(screen.queryByText("Всего поставок")).not.toBeInTheDocument();
  });

  it("исключение фетча тоже даёт экран ошибки (catch в useEffect)", async () => {
    mockBoard.mockRejectedValue(new Error("network"));
    mockImports.mockResolvedValue([]);
    render(<LogisticsImport />);

    expect(await screen.findByText(/Не удалось загрузить цепочку импорта/)).toBeInTheDocument();
  });

  it("KPI считает всего/в движении/на таможне/принято из счётчиков стадий", async () => {
    mockBoard.mockResolvedValue(fullBoard([card({ id: 1 })]));
    mockImports.mockResolvedValue([imp({ id: 1 })]);
    render(<LogisticsImport />);

    const tile = async (label: string) =>
      (await screen.findByText(label)).closest("div")?.parentElement as HTMLElement;

    // total = 2+1+3+1+2 = 9
    expect(await tile("Всего поставок")).toHaveTextContent("9");
    // inTransit = consolidation+in_transit+customs = 1+3+1 = 5 (без factory/warehouse)
    expect(await tile("В движении")).toHaveTextContent("5");
    expect(await tile("На таможне")).toHaveTextContent("1");
    expect(await tile("Принято на склад")).toHaveTextContent("2");
  });

  it("Σ фрахт импорта суммирует только принятые (warehouse, amount>0), а не всё подряд", async () => {
    mockBoard.mockResolvedValue(fullBoard([card({ id: 1 })]));
    // 12000 (warehouse) учитывается; 5000 (в пути) и 0 (warehouse без суммы) — нет.
    mockImports.mockResolvedValue([
      imp({ id: 1, stage: "warehouse", amount: 12000 }),
      imp({ id: 2, stage: "in_transit", amount: 5000 }),
      imp({ id: 3, stage: "warehouse", amount: 0 }),
    ]);
    render(<LogisticsImport />);

    const tile = (await screen.findByText("Σ фрахт импорта")).closest("div")?.parentElement as HTMLElement;
    // ровно 12000 BYN; сравниваем без пробелов-разрядов (formatByn ставит неразрывный пробел)
    const money = (tile.textContent ?? "").replace(/\s/g, "");
    expect(money).toContain("12000BYN");
    // если бы суммировалось всё (17000) — было бы иначе
    expect(money).not.toContain("17000BYN");

    // есть принятые → показывается баннер про учёт фрахта в финансах
    expect(screen.getByText(/двойного учёта НЕТ/)).toBeInTheDocument();
  });

  it("пустая цепочка (0 поставок) показывает подсказку и пилюли всех стадий", async () => {
    mockBoard.mockResolvedValue({
      stages: [
        stage("factory", "Фабрика", 0),
        stage("customs", "Таможня", 0),
        stage("warehouse", "Приёмка на склад", 0),
      ],
    });
    mockImports.mockResolvedValue([]);
    render(<LogisticsImport />);

    expect(await screen.findByText(/Импортных поставок пока нет/)).toBeInTheDocument();
    // подписи стадий выведены как пилюли-подсказки
    expect(screen.getByText("Фабрика")).toBeInTheDocument();
    expect(screen.getByText("Таможня")).toBeInTheDocument();
    // ни одной колонки-канбана (нет поставок) → нет карточек
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("рендерит карточки поставок и сумму фрахта на карточке (amount>0)", async () => {
    mockBoard.mockResolvedValue(
      fullBoard([card({ id: 1, title: "Контейнер ABCU", code: "IMP-42", amount: 8000, priority: "Высокий" })]),
    );
    mockImports.mockResolvedValue([imp({ id: 1 })]);
    render(<LogisticsImport />);

    expect(await screen.findByText(/Контейнер ABCU/)).toBeInTheDocument();
    expect(screen.getByText("IMP-42")).toBeInTheDocument();
    // сумма на карточке (разряды через неразрывный пробел — матчим без пробелов)
    expect(screen.getByText((c) => c.replace(/\s/g, "") === "8000BYN")).toBeInTheDocument();
    expect(screen.getByText("Высокий")).toBeInTheDocument(); // приоритет-пилюля
  });

  it("клик по карточке открывает drawer поставки с её деталями", async () => {
    mockBoard.mockResolvedValue(fullBoard([card({ id: 77, title: "Контейнер X" })]));
    mockImports.mockResolvedValue([
      imp({ id: 77, supplier: "Дунгуань Электрик", cargo: "Аккумуляторы", stage: "customs" }),
    ]);
    render(<LogisticsImport />);

    fireEvent.click(await screen.findByText(/Контейнер X/));

    // drawer раскрыл деталь именно этой поставки (id 77 → импорт найден)
    expect(await screen.findByText("Поставщик")).toBeInTheDocument();
    expect(screen.getByText("Дунгуань Электрик")).toBeInTheDocument();
    expect(screen.getByText("Цепочка")).toBeInTheDocument(); // секция шагов drawer
  });

  it("drawer закрывается по кнопке «Закрыть»", async () => {
    mockBoard.mockResolvedValue(fullBoard([card({ id: 77, title: "Контейнер X" })]));
    mockImports.mockResolvedValue([imp({ id: 77 })]);
    render(<LogisticsImport />);

    fireEvent.click(await screen.findByText(/Контейнер X/));
    expect(await screen.findByText("Поставщик")).toBeInTheDocument();

    // «Закрыть» есть и на фоне (aria-label), и в шапке (текст) — жмём первую
    fireEvent.click(screen.getAllByRole("button", { name: "Закрыть" })[0]);

    await waitFor(() => expect(screen.queryByText("Поставщик")).not.toBeInTheDocument());
  });

  it("клик по карточке без совпадающей поставки не открывает drawer (imp не найден)", async () => {
    // карточка id 5, но в списке импортов такого id нет → find вернёт undefined → null
    mockBoard.mockResolvedValue(fullBoard([card({ id: 5, title: "Осиротевшая" })]));
    mockImports.mockResolvedValue([imp({ id: 999 })]);
    render(<LogisticsImport />);

    fireEvent.click(await screen.findByText(/Осиротевшая/));

    // drawer не должен появиться
    await waitFor(() => {
      expect(screen.queryByText("Цепочка")).not.toBeInTheDocument();
    });
  });
});
