import { configureCompany,render,resetCompany,waitForCompany } from "@/test/installation-company";
import { fireEvent,screen,waitFor,within } from "@testing-library/react";
import { beforeEach,beforeEach as configureBeforeEach,describe,expect,it,vi } from "vitest";
vi.mock("@/lib/instance-organization", async () => {
 const fixture = await import("@/test/installation-company");
 return { fetchInstanceOrganization: fixture.fetchTestInstanceOrganization };
});

vi.mock("@/lib/procurement-machine", () => ({ organizations: vi.fn() }));

// Частичный мок: сетевые функции — моки, чистые хелперы (filterSuppliers/statusLabel/
// emptySupplier) остаются НАСТОЯЩИМИ, чтобы фильтр и подписи считались по-честному.
vi.mock("@/lib/procurement-suppliers", async (importActual) => {
  const actual = await importActual<typeof import("@/lib/procurement-suppliers")>();
  return {
    ...actual,
    fetchSuppliers: vi.fn(),
    createSupplier: vi.fn(),
    updateSupplier: vi.fn(),
    searchSupplierCounterparties: vi.fn(),
    fetchSupplierScorecard: vi.fn(),
  };
});

import { ProcurementSuppliersTable } from "@/components/erp/procurement-suppliers-table";
import { organizations } from "@/lib/procurement-machine";
import type { Supplier } from "@/lib/procurement-suppliers";
import * as api from "@/lib/procurement-suppliers";

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
const searchSupplierCounterparties = api.searchSupplierCounterparties as ReturnType<typeof vi.fn>;
const fetchSupplierScorecard = api.fetchSupplierScorecard as ReturnType<typeof vi.fn>;
const fetchOrganizations = organizations as ReturnType<typeof vi.fn>;

// Открыть drawer создания и вернуть input названия (Field без htmlFor — берём по метке).
function nameInput(): HTMLInputElement {
  return screen.getByText("Название").parentElement!.querySelector("input") as HTMLInputElement;
}

async function chooseMdm(name: string) {
  fireEvent.change(screen.getByLabelText("Поиск контрагента MDM"), { target: { value: name } });
  await waitFor(() => expect(searchSupplierCounterparties).toHaveBeenCalledWith(name));
  await screen.findByRole("option", { name: new RegExp(name) });
  fireEvent.change(screen.getByLabelText("Поставщик из справочника"), { target: { value: "12" } });
}

beforeEach(() => {
  vi.clearAllMocks();
  // Эффект на маунте всегда зовёт fetchSuppliers — по умолчанию null (не затирать SSR-строки).
  fetchSuppliers.mockResolvedValue(null);
  createSupplier.mockResolvedValue(supplier({ id: 99 }));
  updateSupplier.mockResolvedValue(supplier());
  searchSupplierCounterparties.mockImplementation(async (name: string) => [{ id: 12, name, unp: "190000012" }]);
  fetchOrganizations.mockResolvedValue([{ id: 7, name: "Компания А", unp: "123" }, { id: 8, name: "Компания Б", unp: "456" }]);
  fetchSupplierScorecard.mockResolvedValue({ organization_id: 7, supplier_id: 1,
    supplier_name: "Shenzhen Power Co", orders_count: 2, on_time_observed_count: 1,
    on_time_count: 1, on_time_rate: 1, won_rfq_count: 1, avg_won_price_byn: "100.00",
    claims_total: null, claims_open: null, claims_closed: null, score: null,
    status: "provisional_claims_unattributed", reason: "Claims unattributed" });
});

describe("ProcurementSuppliersTable", () => {
  it("не выдаёт отсутствие данных за ноль и восстанавливает подтверждённый пустой список вручную", async () => {
    const serverFetch = vi.spyOn(globalThis, "fetch").mockResolvedValue({ ok: false } as Response);
    const initial = await api.fetchSuppliersServer("procurement_head");
    serverFetch.mockRestore();
    render(<ProcurementSuppliersTable initial={initial} />);
    await waitForCompany();
    expect(await screen.findByRole("alert")).toHaveTextContent("Не удалось загрузить поставщиков");
    expect(screen.queryByText("Поставщиков пока нет — добавьте первого")).not.toBeInTheDocument();
    for (const label of ["Поставщиков", "Активных", "Заблокировано"]) {
      expect(within(screen.getByText(label, { exact: true }).parentElement!).getByText("—")).toBeInTheDocument();
    }
    fetchSuppliers.mockResolvedValueOnce([]);
    fireEvent.click(screen.getByRole("button", { name: /Обновить/ }));
    expect(await screen.findByText("Поставщиков пока нет — добавьте первого")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
    for (const label of ["Поставщиков", "Активных", "Заблокировано"]) {
      expect(within(screen.getByText(label, { exact: true }).parentElement!).getByText("0")).toBeInTheDocument();
    }
  });

  it("сохраняет загруженные данные и явно предупреждает о неудачном обновлении", async () => {
    render(<ProcurementSuppliersTable initial={rows} />);
    await waitForCompany();
    expect(await screen.findByRole("alert")).toHaveTextContent("Показаны ранее загруженные данные");
    expect(screen.getByText("Shenzhen Power Co")).toBeInTheDocument();
    expect(within(screen.getByText("Поставщиков", { exact: true }).parentElement!).getByText("3")).toBeInTheDocument();
  });

  it("читает показатели только при открытии поставщика в юрлице установки и показывает неполноту данных", async () => {
    render(<ProcurementSuppliersTable initial={rows} />);
  await waitForCompany();
    expect(fetchSupplierScorecard).not.toHaveBeenCalled();
    expect(screen.queryByRole("combobox", { name: /Юрлицо/ })).not.toBeInTheDocument();
    fireEvent.click(within(screen.getByText("Shenzhen Power Co").closest("tr")!).getByRole("button", { name: "Открыть показатели" }));
    await waitFor(() => expect(fetchSupplierScorecard).toHaveBeenCalledWith(7, 1));
    const panel = await screen.findByRole("region", { name: "Показатели поставщика" });
    expect(within(panel).getByText(/Претензии и общий балл: нет надёжной привязки/)).toBeInTheDocument();
    expect(within(panel).getByText(/Доля своевременных: 100%/)).toBeInTheDocument();
  });

  it("при смене юрлица скрывает прежние показатели до ответа нового юрлица", async () => {
    let resolveOther!: (value: unknown) => void;
    fetchSupplierScorecard.mockImplementation((org: number) => org === 7
      ? Promise.resolve({ organization_id: 7, supplier_id: 1, supplier_name: "A", orders_count: 2,
        on_time_observed_count: 1, on_time_count: 1, on_time_rate: 1, won_rfq_count: 0,
        avg_won_price_byn: null, claims_total: null, claims_open: null, claims_closed: null,
        score: null, status: "provisional_claims_unattributed", reason: "Claims unattributed" })
      : new Promise(resolve => { resolveOther = resolve; }));
    render(<ProcurementSuppliersTable initial={rows} />);
  await waitForCompany();
    await waitForCompany();
    fireEvent.click(within(screen.getByText("Shenzhen Power Co").closest("tr")!).getByRole("button", { name: "Открыть показатели" }));
    await screen.findByText(/Заказов: 2/);
    await configureCompany("8");
    expect(screen.queryByText(/Заказов: 2/)).toBeNull();
    expect(fetchSupplierScorecard).toHaveBeenCalledTimes(1);
    fireEvent.click(within(screen.getByText("Shenzhen Power Co").closest("tr")!).getByRole("button", { name: "Открыть показатели" }));
    await waitFor(() => expect(fetchSupplierScorecard).toHaveBeenCalledWith(8, 1));
    expect(screen.queryByText(/Заказов: 2/)).toBeNull();
    resolveOther({ organization_id: 8, supplier_id: 1, supplier_name: "B", orders_count: 1,
      on_time_observed_count: 0, on_time_count: 0, on_time_rate: null, won_rfq_count: 0,
      avg_won_price_byn: null, claims_total: null, claims_open: null, claims_closed: null,
      score: null, status: "provisional_claims_unattributed", reason: "Claims unattributed" });
    await screen.findByText(/Заказов: 1/);
  });
  it("считает KPI: всего / активных / заблокировано по статусам", async () => {
    render(<ProcurementSuppliersTable initial={rows} />);
  await waitForCompany();
    // 3 всего, 2 active, 1 blocked — проверяем внутри плитки (label+value в одном контейнере)
    expect(screen.getByText("Поставщиков").parentElement).toHaveTextContent("3");
    expect(screen.getByText("Активных").parentElement).toHaveTextContent("2");
    expect(screen.getByText("Заблокировано").parentElement).toHaveTextContent("1");
  });

  it("рендерит строки поставщиков с человекочитаемым статусом и прочерком для пустых полей", async () => {
    render(<ProcurementSuppliersTable initial={rows} />);
  await waitForCompany();
    fireEvent.click(screen.getByRole("button", { name: "Открыть карточку Shenzhen Power Co", exact: true }));
    expect(screen.getByRole("dialog", { name: "Поставщик", exact: true })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Закрыть карточку поставщика", exact: true }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
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

  it("пустой список показывает призыв добавить первого поставщика", async () => {
    render(<ProcurementSuppliersTable initial={[]} />);
  await waitForCompany();
    expect(screen.getByText("Поставщиков пока нет — добавьте первого")).toBeInTheDocument();
  });

  it("поиск фильтрует строки по подстроке, а без совпадений — «Ничего не найдено»", async () => {
    render(<ProcurementSuppliersTable initial={rows} />);
  await waitForCompany();
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
  await waitForCompany();
    expect(screen.queryByText("Свежий Поставщик")).not.toBeInTheDocument();

    fetchSuppliers.mockResolvedValueOnce([supplier({ id: 7, name: "Свежий Поставщик" })]);
    fireEvent.click(screen.getByRole("button", { name: /Обновить/ }));

    expect(await screen.findByText("Свежий Поставщик")).toBeInTheDocument();
    expect(screen.queryByText("Shenzhen Power Co")).not.toBeInTheDocument();
  });

  it("сохранение нового поставщика без имени блокируется валидацией, API не зовётся", async () => {
    render(<ProcurementSuppliersTable initial={rows} />);
  await waitForCompany();
    fireEvent.click(screen.getByRole("button", { name: /Добавить/ }));
    expect(screen.getByRole("heading", { name: "Новый поставщик" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    expect(screen.getByText("Выберите поставщика из справочника контрагентов")).toBeInTheDocument();
    expect(createSupplier).not.toHaveBeenCalled();
  });

  it("создание с выбранным MDM ID шлёт createSupplier, закрывает форму и обновляет список", async () => {
    render(<ProcurementSuppliersTable initial={rows} />);
  await waitForCompany();
    fireEvent.click(screen.getByRole("button", { name: /Добавить/ }));
    await chooseMdm("ООО Ромашка");

    // refresh после сохранения вернёт список с новым поставщиком
    fetchSuppliers.mockResolvedValueOnce([...rows, supplier({ id: 99, name: "ООО Ромашка" })]);
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));

    await waitFor(() =>
      expect(createSupplier).toHaveBeenCalledWith(expect.objectContaining({ name: "ООО Ромашка", counterparty_id: 12, unp: "190000012" })),
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
  await waitForCompany();
    fireEvent.click(screen.getByRole("button", { name: /Добавить/ }));
    await chooseMdm("ООО Сбой");
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));

    expect(await screen.findByText("Не удалось сохранить — попробуйте ещё раз")).toBeInTheDocument();
    // форма осталась открытой (не потеряли ввод пользователя)
    expect(screen.getByRole("heading", { name: "Новый поставщик" })).toBeInTheDocument();
  });

  it("исторический профиль сопоставляется с MDM ID без свободного ввода имени", async () => {
    render(<ProcurementSuppliersTable initial={rows} />);
  await waitForCompany();
    fireEvent.click(screen.getByText("МинскМеталл"));

    // drawer правки — заголовок «Поставщик» (не «Новый поставщик»), имя предзаполнено
    expect(screen.getByRole("heading", { name: "Поставщик" })).toBeInTheDocument();
    const input = nameInput();
    expect(input.value).toBe("МинскМеталл");

    expect(input).toHaveAttribute("readonly");
    await chooseMdm("МинскМеталл Плюс");
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));

    await waitFor(() =>
      expect(updateSupplier).toHaveBeenCalledWith(
        2,
        expect.objectContaining({ name: "МинскМеталл Плюс", counterparty_id: 12 }),
      ),
    );
    expect(createSupplier).not.toHaveBeenCalled(); // правка, не создание
  });
});

configureBeforeEach(() => resetCompany(7));
