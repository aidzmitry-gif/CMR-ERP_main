import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// Частичный мок: сетевые функции — моки, чистые хелперы (filterSuppliers/statusLabel/
// emptySupplier) остаются НАСТОЯЩИМИ, чтобы фильтр и подписи считались по-честному.
vi.mock("@/lib/procurement-suppliers", async (importActual) => {
  const actual = await importActual<typeof import("@/lib/procurement-suppliers")>();
  return {
    ...actual,
    fetchSuppliers: vi.fn(),
    createSupplier: vi.fn(),
    updateSupplier: vi.fn(),
  };
});

import { ProcurementSuppliersTable } from "@/components/erp/procurement-suppliers-table";
import * as api from "@/lib/procurement-suppliers";
import type { Supplier } from "@/lib/procurement-suppliers";

function supplier(over: Partial<Supplier> = {}): Supplier {
  return {
    id: 1,
    name: "Shenzhen Power Co",
    unp: "912345678",
    country: "Китай",
    flag: "🇨🇳",
    contact_person: "Li Wei",
    phone: "+86 755 000",
    email: "li@sz.cn",
    payment_terms: "30% предоплата / 70% по факту",
    lead_time_days: 45,
    incoterms: "FOB",
    status: "active",
    notes: "",
    ...over,
  };
}

const rows: Supplier[] = [
  supplier({ id: 1, name: "Shenzhen Power Co", country: "Китай", status: "active" }),
  supplier({
    id: 2,
    name: "МинскМеталл",
    unp: "191000001",
    country: "Беларусь",
    flag: "🇧🇾",
    payment_terms: "по факту",
    lead_time_days: 7,
    incoterms: "DAP",
    status: "active",
  }),
  supplier({
    id: 3,
    name: "Bad Vendor Ltd",
    unp: "500500500",
    country: "Индия",
    flag: "🇮🇳",
    payment_terms: "",
    lead_time_days: null,
    incoterms: "",
    status: "blocked",
  }),
];

const fetchSuppliers = api.fetchSuppliers as ReturnType<typeof vi.fn>;
const createSupplier = api.createSupplier as ReturnType<typeof vi.fn>;
const updateSupplier = api.updateSupplier as ReturnType<typeof vi.fn>;

// Открыть drawer создания и вернуть input названия (Field без htmlFor — берём по метке).
function nameInput(): HTMLInputElement {
  return screen.getByText("Название*").parentElement!.querySelector("input") as HTMLInputElement;
}

beforeEach(() => {
  vi.clearAllMocks();
  // Эффект на маунте всегда зовёт fetchSuppliers — по умолчанию null (не затирать SSR-строки).
  fetchSuppliers.mockResolvedValue(null);
  createSupplier.mockResolvedValue(supplier({ id: 99 }));
  updateSupplier.mockResolvedValue(supplier());
});

describe("ProcurementSuppliersTable", () => {
  it("считает KPI: всего / активных / заблокировано по статусам", () => {
    render(<ProcurementSuppliersTable initial={rows} />);
    // 3 всего, 2 active, 1 blocked — проверяем внутри плитки (label+value в одном контейнере)
    expect(screen.getByText("Поставщиков").parentElement).toHaveTextContent("3");
    expect(screen.getByText("Активных").parentElement).toHaveTextContent("2");
    expect(screen.getByText("Заблокировано").parentElement).toHaveTextContent("1");
  });

  it("рендерит строки поставщиков с человекочитаемым статусом и прочерком для пустых полей", () => {
    render(<ProcurementSuppliersTable initial={rows} />);
    expect(screen.getByText("Shenzhen Power Co")).toBeInTheDocument();
    expect(screen.getByText("МинскМеталл")).toBeInTheDocument();
    // statusLabel (настоящий): active → «Активен», blocked → «Заблокирован»
    expect(screen.getAllByText("Активен")).toHaveLength(2);
    expect(screen.getByText("Заблокирован")).toBeInTheDocument();
    // страна показана с флагом; пустые payment_terms/incoterms → «—»
    expect(screen.getByText(/🇨🇳\s*Китай/)).toBeInTheDocument();
    const badRow = screen.getByText("Bad Vendor Ltd").closest("tr")!;
    expect(within(badRow).getAllByText("—").length).toBeGreaterThanOrEqual(2);
  });

  it("пустой список показывает призыв добавить первого поставщика", () => {
    render(<ProcurementSuppliersTable initial={[]} />);
    expect(screen.getByText("Поставщиков пока нет — добавьте первого")).toBeInTheDocument();
  });

  it("поиск фильтрует строки по подстроке, а без совпадений — «Ничего не найдено»", () => {
    render(<ProcurementSuppliersTable initial={rows} />);
    const search = screen.getByPlaceholderText("Поиск: имя, УНП, страна");

    fireEvent.change(search, { target: { value: "минск" } });
    expect(screen.getByText("МинскМеталл")).toBeInTheDocument();
    expect(screen.queryByText("Shenzhen Power Co")).not.toBeInTheDocument();

    fireEvent.change(search, { target: { value: "нет-такого" } });
    expect(screen.getByText("Ничего не найдено")).toBeInTheDocument();
    // это НЕ «добавьте первого» — строки в источнике есть, просто не нашлись
    expect(screen.queryByText("Поставщиков пока нет — добавьте первого")).not.toBeInTheDocument();
  });

  it("«Обновить» подтягивает свежие строки из API", async () => {
    render(<ProcurementSuppliersTable initial={rows} />);
    expect(screen.queryByText("Свежий Поставщик")).not.toBeInTheDocument();

    fetchSuppliers.mockResolvedValueOnce([supplier({ id: 7, name: "Свежий Поставщик" })]);
    fireEvent.click(screen.getByRole("button", { name: /Обновить/ }));

    expect(await screen.findByText("Свежий Поставщик")).toBeInTheDocument();
    expect(screen.queryByText("Shenzhen Power Co")).not.toBeInTheDocument();
  });

  it("сохранение нового поставщика без имени блокируется валидацией, API не зовётся", () => {
    render(<ProcurementSuppliersTable initial={rows} />);
    fireEvent.click(screen.getByRole("button", { name: /Добавить/ }));
    expect(screen.getByRole("heading", { name: "Новый поставщик" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    expect(screen.getByText("Имя поставщика обязательно")).toBeInTheDocument();
    expect(createSupplier).not.toHaveBeenCalled();
  });

  it("создание с именем шлёт createSupplier, закрывает форму и обновляет список", async () => {
    render(<ProcurementSuppliersTable initial={rows} />);
    fireEvent.click(screen.getByRole("button", { name: /Добавить/ }));
    fireEvent.change(nameInput(), { target: { value: "ООО Ромашка" } });

    // refresh после сохранения вернёт список с новым поставщиком
    fetchSuppliers.mockResolvedValueOnce([...rows, supplier({ id: 99, name: "ООО Ромашка" })]);
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));

    await waitFor(() =>
      expect(createSupplier).toHaveBeenCalledWith(expect.objectContaining({ name: "ООО Ромашка" })),
    );
    expect(updateSupplier).not.toHaveBeenCalled(); // создание, не правка
    // форма закрылась
    await waitFor(() =>
      expect(screen.queryByRole("heading", { name: "Новый поставщик" })).not.toBeInTheDocument(),
    );
    expect(await screen.findByText("ООО Ромашка")).toBeInTheDocument();
  });

  it("сбой сохранения показывает ошибку и не закрывает форму", async () => {
    createSupplier.mockResolvedValueOnce(null); // сеть/сервер упали
    render(<ProcurementSuppliersTable initial={rows} />);
    fireEvent.click(screen.getByRole("button", { name: /Добавить/ }));
    fireEvent.change(nameInput(), { target: { value: "ООО Сбой" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));

    expect(await screen.findByText("Не удалось сохранить — попробуйте ещё раз")).toBeInTheDocument();
    // форма осталась открытой (не потеряли ввод пользователя)
    expect(screen.getByRole("heading", { name: "Новый поставщик" })).toBeInTheDocument();
  });

  it("клик по строке открывает правку с предзаполненным именем и шлёт updateSupplier(id, …)", async () => {
    render(<ProcurementSuppliersTable initial={rows} />);
    fireEvent.click(screen.getByText("МинскМеталл"));

    // drawer правки — заголовок «Поставщик» (не «Новый поставщик»), имя предзаполнено
    expect(screen.getByRole("heading", { name: "Поставщик" })).toBeInTheDocument();
    const input = nameInput();
    expect(input.value).toBe("МинскМеталл");

    fireEvent.change(input, { target: { value: "МинскМеталл Плюс" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));

    await waitFor(() =>
      expect(updateSupplier).toHaveBeenCalledWith(
        2,
        expect.objectContaining({ name: "МинскМеталл Плюс" }),
      ),
    );
    expect(createSupplier).not.toHaveBeenCalled(); // правка, не создание
  });
});
