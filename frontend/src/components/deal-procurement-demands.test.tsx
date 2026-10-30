import { configureCompany,render,resetCompany,waitForCompany } from "@/test/installation-company";
import { fireEvent,screen,waitFor } from "@testing-library/react";
import { beforeEach,beforeEach as configureBeforeEach,expect,it,vi } from "vitest";
vi.mock("@/lib/instance-organization", async () => {
 const fixture = await import("@/test/installation-company");
 return { fetchInstanceOrganization: fixture.fetchTestInstanceOrganization };
});

vi.mock("@/lib/procurement-machine", () => ({ organizations: vi.fn() }));
vi.mock("@/lib/procurement-deal-demand", () => ({ fetchDealDemands: vi.fn(), createDealDemand: vi.fn() }));

import { DealProcurementDemands } from "@/components/deal-procurement-demands";
import { createDealDemand,fetchDealDemands } from "@/lib/procurement-deal-demand";
import { organizations } from "@/lib/procurement-machine";

const item = { id: 7, sku_id: 2, code: "AKB-60", title: "Аккумулятор", unit: "шт", qty: 2, unit_price: null, last_price: null, min_price: null };
const demand = { id: 9, organization_id: 1, deal_id: 5, deal_item_id: 7, sku_id: 2, sku_code: "AKB-60", qty: "2.00", ordered_qty: "0.00", free_qty: "2.00", document_id: null, request_key: "11111111-1111-4111-8111-111111111111", allocations: [] };

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(organizations).mockResolvedValue([{ id: 1, name: "Компания", unp: "123456789" }]);
  vi.mocked(fetchDealDemands).mockResolvedValue([]);
});

it("не читает и не создаёт потребность без настроенного юрлица", async () => {
  resetCompany(0); render(<DealProcurementDemands dealId="5" items={[item]} />);
  expect(await screen.findByRole("alert")).toBeInTheDocument();
  expect(fetchDealDemands).not.toHaveBeenCalled();
  expect(createDealDemand).not.toHaveBeenCalled();
});

it("передаёт только выбранную строку сделки и показывает её непокрытый остаток", async () => {
  vi.mocked(fetchDealDemands).mockResolvedValueOnce([]).mockResolvedValueOnce([demand]);
  vi.mocked(createDealDemand).mockResolvedValue(demand);
  render(<DealProcurementDemands dealId="5" items={[item, { ...item, id: 8, title: "Вторая позиция" }]} />);
  await waitForCompany();
  await waitForCompany();
  await configureCompany("1");
  await waitFor(() => expect(fetchDealDemands).toHaveBeenCalledWith(1, 5));
  fireEvent.click(screen.getAllByRole("button", { name: "В закупки" })[0]);
  await waitFor(() => expect(createDealDemand).toHaveBeenCalledWith(1, 5, 7, "2.00", expect.any(String)));
  expect(await screen.findByText("Потребность 2.00; закреплено за заказом 0.00; осталось обеспечить 2.00")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "В закупки" })).toBeInTheDocument();
});

it("даёт честную навигацию в план без заказа и сохраняет строку для сверки заказа", async () => {
  vi.mocked(fetchDealDemands).mockResolvedValueOnce([demand]);
  render(<DealProcurementDemands dealId="5" items={[item]} />);
  await waitForCompany();
  expect(screen.queryByRole("option", { name: "Компания · 123456789" })).not.toBeInTheDocument();
  await waitFor(() => expect(fetchDealDemands).toHaveBeenCalledWith(1, 5));
  await waitForCompany();
  await configureCompany("1");
  expect(await screen.findByRole("link", { name: "Открыть план закупок юрлица #1" })).toHaveAttribute("href", "/erp/procurement/planning?org=1");
  vi.mocked(fetchDealDemands).mockResolvedValueOnce([{ ...demand, allocations: [{ id: 4, order_id: 12, order_line_id: 34, qty: "1.00" }] }]);
  await configureCompany("");
  await configureCompany("1");
  expect(await screen.findByRole("link", { name: "Заказ поставщику #12, строка #34" })).toHaveAttribute("href", "/erp/procurement/orders/12?org=1");
  expect(screen.queryByRole("link", { name: "Открыть план закупок юрлица #1" })).toBeNull();
});

it("при отказе сохраняет количество и повторяет команду с тем же ключом", async () => {
  vi.mocked(createDealDemand).mockRejectedValueOnce(new Error("Не удалось создать потребность закупки (403)"));
  render(<DealProcurementDemands dealId="5" items={[item]} />);
  await waitForCompany();
  await waitForCompany();
  await configureCompany("1");
  await waitFor(() => expect(fetchDealDemands).toHaveBeenCalledWith(1, 5));
  fireEvent.change(screen.getByLabelText("Количество в потребность Аккумулятор"), { target: { value: "1.5" } });
  fireEvent.click(screen.getByRole("button", { name: "В закупки" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("403");
  expect(screen.getByLabelText("Количество в потребность Аккумулятор")).toHaveValue(1.5);
  vi.mocked(createDealDemand).mockResolvedValue(demand);
  fireEvent.click(screen.getByRole("button", { name: "В закупки" }));
  await waitFor(() => expect(createDealDemand).toHaveBeenCalledTimes(2));
  const firstKey = vi.mocked(createDealDemand).mock.calls[0][4];
  expect(vi.mocked(createDealDemand).mock.calls[1][4]).toBe(firstKey);
});

configureBeforeEach(() => resetCompany(1));
