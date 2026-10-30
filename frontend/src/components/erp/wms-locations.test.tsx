import { WmsLocations } from "@/components/erp/wms-locations";
import type { WmsLocation } from "@/lib/wms-ops";
import * as wms from "@/lib/wms-ops";
import { configureCompany,render,resetCompany } from "@/test/installation-company";
import { act,fireEvent,screen,waitFor } from "@testing-library/react";
import { beforeEach,beforeEach as configureBeforeEach,describe,expect,it,vi } from "vitest";
vi.mock("@/lib/instance-organization", async () => {
 const fixture = await import("@/test/installation-company");
 return { fetchInstanceOrganization: fixture.fetchTestInstanceOrganization };
});

vi.mock("next/link", () => ({ default: ({ children, href }: { children: React.ReactNode; href: string }) => <a href={href}>{children}</a> }));
vi.mock("@/lib/wms-ops", async (importActual) => ({
  ...await importActual<typeof import("@/lib/wms-ops")>(),
  fetchLocations: vi.fn(), fetchLocationWarehouses: vi.fn(), createLocation: vi.fn(),
}));

const organizations = [{ id: 7, name: "Учебная А" }, { id: 8, name: "Учебная Б" }];
const locations: WmsLocation[] = [
  { id: 1, organization_id: 7, warehouse: "Главный", zone: "A", code: "A-01", title: "Стеллаж 1", is_active: true },
  { id: 2, organization_id: 7, warehouse: "Главный", zone: "", code: "B-02", title: "", is_active: false },
];
const created: WmsLocation = { id: 3, organization_id: 7, warehouse: "Второй", zone: "Z", code: "Z-09", title: "Верхний ряд", is_active: true };
const mock = (fn: unknown) => fn as ReturnType<typeof vi.fn>;
function show(initial = locations) { return render(<WmsLocations initial={initial} organizations={organizations} />); }
async function chooseCompany(id = 7) {
  await configureCompany(String(id));
  await waitFor(() => expect(screen.getByLabelText("Склад ячейки")).toBeEnabled());
}
function fill() {
  fireEvent.change(screen.getByLabelText("Склад ячейки"), { target: { value: "Второй" } });
  fireEvent.change(screen.getByPlaceholderText("Зона"), { target: { value: "  Z  " } });
  fireEvent.change(screen.getByPlaceholderText("Ячейка*"), { target: { value: "  Z-09  " } });
  fireEvent.change(screen.getByPlaceholderText("Описание"), { target: { value: "  Верхний ряд  " } });
}
beforeEach(() => {
  vi.resetAllMocks();
  mock(wms.fetchLocations).mockImplementation(async (org: number) => locations.filter((row) => row.organization_id === org));
  mock(wms.fetchLocationWarehouses).mockImplementation(async (org: number) => ({ items: [{ organization_id: org, name: "Главный" }, { organization_id: org, name: "Второй" }], truncated: false }));
  mock(wms.createLocation).mockResolvedValue(created);
});

describe("WmsLocations", () => {
  it("does not load or create cells without a verified installation company", async () => {
    resetCompany(0); show([]);
    expect(await screen.findByRole("alert")).toHaveTextContent("не настроено");
    expect(wms.fetchLocationWarehouses).not.toHaveBeenCalled();
  });
  it("renders company, label, status and specific print links", async () => {
    show(); await screen.findByText("A · A-01");
    expect(screen.getByText("B-02")).toBeInTheDocument();
    expect(screen.getByText("Активна")).toBeInTheDocument();
    expect(screen.getByText("Архив")).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: /Этикетка/ })[0]).toHaveAttribute("href", "/erp/wms/locations/1/label");
    expect(screen.getAllByRole("link", { name: /Этикетка/ })[1]).toHaveAttribute("href", "/erp/wms/locations/2/label");
  });
  it("does not create a cell with an empty code", async () => {
    show(); await chooseCompany();
    fireEvent.change(screen.getByLabelText("Склад ячейки"), { target: { value: "Второй" } });
    fireEvent.click(screen.getByRole("button", { name: "Добавить" }));
    expect(wms.createLocation).not.toHaveBeenCalled();
    expect(screen.getByPlaceholderText("Ячейка*")).toHaveAttribute("aria-invalid", "true");
  });
  it("sends explicit company and registered warehouse, trims fields and clears only the saved draft", async () => {
    show(); await chooseCompany(); fill();
    fireEvent.click(screen.getByRole("button", { name: "Добавить" }));
    await screen.findByText("Ячейка Z-09 сохранена.");
    expect(wms.createLocation).toHaveBeenCalledWith({ organization_id: 7, warehouse: "Второй", zone: "Z", code: "Z-09", title: "Верхний ряд" });
    expect(screen.getByPlaceholderText("Ячейка*")).toHaveValue("");
    expect(screen.getByPlaceholderText("Описание")).toHaveValue("");
    expect(screen.getByPlaceholderText("Зона")).toHaveValue("  Z  ");
    expect(screen.getByLabelText("Склад ячейки")).toHaveValue("Второй");
    expect(screen.getByText("Z · Z-09")).toBeInTheDocument();
    expect(wms.fetchLocations).toHaveBeenCalledTimes(1);
  });
  it("preserves rejected draft, without refresh or false success", async () => {
    mock(wms.createLocation).mockRejectedValue(new wms.LocationRequestError("Отклонено", 422));
    show(); await chooseCompany(); fill();
    fireEvent.click(screen.getByRole("button", { name: "Добавить" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Отклонено");
    expect(screen.getByPlaceholderText("Ячейка*")).toHaveValue("  Z-09  ");
    expect(screen.getByPlaceholderText("Описание")).toHaveValue("  Верхний ряд  ");
    expect(screen.queryByText(/сохранена/)).not.toBeInTheDocument();
    expect(wms.fetchLocations).toHaveBeenCalledTimes(1);
  });
  it("never defaults an unselected warehouse to Main", async () => {
    show(); await chooseCompany();
    fireEvent.change(screen.getByPlaceholderText("Ячейка*"), { target: { value: "D-01" } });
    fireEvent.click(screen.getByRole("button", { name: "Добавить" }));
    expect(wms.createLocation).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Склад ячейки")).toHaveValue("");
    expect(screen.getByRole("alert")).toHaveTextContent("Выберите зарегистрированный склад");
  });
  it("clears previous company rows and warehouse immediately and ignores late reads", async () => {
    let finish!: (value: WmsLocation[]) => void;
    mock(wms.fetchLocations).mockReturnValueOnce(new Promise<WmsLocation[]>((resolve) => { finish = resolve; })).mockResolvedValueOnce([{ ...locations[0], id: 9, organization_id: 8, code: "B-09" }]);
    show();
    await configureCompany("7");
    expect(screen.queryByText("A · A-01")).not.toBeInTheDocument();
    await configureCompany("8");
    await screen.findByText("A · B-09");
    await act(async () => finish(locations));
    expect(screen.queryByText("A · A-01")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Склад ячейки")).toHaveValue("");
    await configureCompany("");
    expect(screen.queryByText("A · A-01")).not.toBeInTheDocument();
    expect(await screen.findByRole("alert")).toHaveTextContent("не настроено");
  });
  it("keeps read-only company cells visible when creation permission is denied", async () => {
    mock(wms.fetchLocationWarehouses).mockRejectedValue(new wms.LocationRequestError("Нет доступа", 403));
    show(); await configureCompany("7");
    await screen.findByText(/Создание ячеек для выбранной компании недоступно/);
    expect(screen.getByText("A · A-01")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Добавить" })).toBeDisabled();
  });
  it("failed read is not empty success and cannot create until a successful read retry", async () => {
    mock(wms.fetchLocations).mockRejectedValueOnce(new wms.LocationRequestError("Сессия истекла", 401));
    show(); await configureCompany("7");
    expect(await screen.findByRole("alert")).toHaveTextContent("Сессия истекла");
    expect(screen.queryByText("Ячеек в выбранном обзоре нет")).not.toBeInTheDocument();
    expect(screen.queryByText("A · A-01")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Добавить" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Обновить список" }));
    await screen.findByText("A · A-01");
  });
  it("serializes rapid clicks and locks company and draft until the write completes", async () => {
    let finish!: (value: WmsLocation) => void;
    mock(wms.createLocation).mockReturnValue(new Promise<WmsLocation>((resolve) => { finish = resolve; }));
    show(); await chooseCompany(); fill();
    const add = screen.getByRole("button", { name: "Добавить" });
    fireEvent.click(add); fireEvent.click(add);
    expect(wms.createLocation).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("combobox", { name: /Юрлицо|Организация|Компания ячеек|Юридическое лицо/ })).not.toBeInTheDocument();
    expect(screen.getByPlaceholderText("Ячейка*")).toBeDisabled();
    await act(async () => finish(created));
    expect(screen.queryByRole("combobox", { name: /Юрлицо|Организация|Компания ячеек|Юридическое лицо/ })).not.toBeInTheDocument();
  });
  it("blocks resending an unknown write until the list has been checked", async () => {
    mock(wms.createLocation).mockRejectedValue(new wms.LocationRequestError("Результат неизвестен", null, true));
    show(); await chooseCompany(); fill();
    fireEvent.click(screen.getByRole("button", { name: "Добавить" }));
    await screen.findByText("Результат неизвестен");
    expect(screen.getByRole("button", { name: "Добавить" })).toBeDisabled();
    expect(screen.getByPlaceholderText("Ячейка*")).toHaveValue("  Z-09  ");
    fireEvent.click(screen.getByRole("button", { name: "Обновить список" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Добавить" })).toBeEnabled());
    expect(wms.createLocation).toHaveBeenCalledTimes(1);
  });
  it("clears protected rows after write access is refused", async () => {
    mock(wms.createLocation).mockRejectedValue(new wms.LocationRequestError("Нет доступа", 403));
    show(); await chooseCompany(); fill();
    fireEvent.click(screen.getByRole("button", { name: "Добавить" }));
    await waitFor(() => expect(screen.queryByText("A · A-01")).not.toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Добавить" })).toBeDisabled();
    expect(screen.getByPlaceholderText("Ячейка*")).toHaveValue("  Z-09  ");
  });
  it("shows catalogue truncation and performs an explicit search without losing the code", async () => {
    mock(wms.fetchLocationWarehouses).mockResolvedValueOnce({ items: [{ organization_id: 7, name: "Главный" }], truncated: true });
    show(); await chooseCompany();
    expect(screen.getByText(/Показаны первые 50 складов/)).toBeInTheDocument();
    fireEvent.change(screen.getByPlaceholderText("Ячейка*"), { target: { value: "X" } });
    fireEvent.change(screen.getByLabelText("Поиск склада"), { target: { value: "Второй" } });
    fireEvent.click(screen.getByRole("button", { name: "Найти склады" }));
    await waitFor(() => expect(wms.fetchLocationWarehouses).toHaveBeenLastCalledWith(7, "Второй"));
    expect(screen.getByPlaceholderText("Ячейка*")).toHaveValue("X");
    expect(screen.getByLabelText("Склад ячейки")).toHaveValue("");
  });
  it("does not show rows from companies absent in the authorized company list", () => {
    show([{ ...locations[0], organization_id: 999, code: "FOREIGN" }]);
    expect(screen.queryByText(/FOREIGN/)).not.toBeInTheDocument();
  });
});

configureBeforeEach(() => resetCompany(7));
