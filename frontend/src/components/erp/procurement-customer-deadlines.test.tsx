import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { ProcurementCustomerDeadlines } from "./procurement-customer-deadlines";
import { fetchCustomerDeadlines } from "@/lib/procurement-machine";
vi.mock("@/lib/procurement-machine", () => ({ fetchCustomerDeadlines: vi.fn() }));
beforeEach(() => vi.resetAllMocks());
it("shows dated and unknown customer requirements without claiming full coverage", async () => {
  vi.mocked(fetchCustomerDeadlines).mockResolvedValue({ organization_id: 1, order_id: 7, status: "live_review", source: "outstanding_expected_reservations", earliest_required_arrival: "2026-12-28", unresolved_deadlines: 1, complete_customer_demand: false, at_risk: true, items: [] });
  render(<ProcurementCustomerDeadlines org={1} orderId={7} />);
  fireEvent.click(screen.getByText("Проверить клиентские сроки"));
  expect(await screen.findByText(/Есть риск опоздания/)).toBeInTheDocument();
  expect(screen.getByText(/Неопределённые сроки: 1/)).toBeInTheDocument();
  expect(screen.getByText(/Полнота потребностей и штрафы/)).toBeInTheDocument();
});
it("shows read failure and permits retry", async () => {
  vi.mocked(fetchCustomerDeadlines).mockRejectedValue(new Error("Нет доступа"));
  render(<ProcurementCustomerDeadlines org={1} orderId={7} />);
  fireEvent.click(screen.getByText("Проверить клиентские сроки"));
  expect(await screen.findByRole("alert")).toHaveTextContent("Нет доступа");
  await waitFor(() => expect(screen.getByRole("button")).toBeEnabled());
});

it("refreshes the date before copying it into the unsaved plan", async () => {
  const onUseDate = vi.fn();
  const value = { organization_id: 1, order_id: 7, status: "live_review" as const, source: "outstanding_expected_reservations" as const, earliest_required_arrival: "2026-12-28", unresolved_deadlines: 0, complete_customer_demand: false as const, at_risk: true, items: [] };
  vi.mocked(fetchCustomerDeadlines).mockResolvedValueOnce(value).mockResolvedValueOnce({ ...value, earliest_required_arrival: "2026-12-20" });
  render(<ProcurementCustomerDeadlines org={1} orderId={7} onUseDate={onUseDate} />);
  fireEvent.click(screen.getByText("Проверить клиентские сроки"));
  fireEvent.click(await screen.findByText("Обновить сроки и подставить дату в план"));
  await waitFor(() => expect(onUseDate).toHaveBeenCalledWith("2026-12-20"));
  expect(fetchCustomerDeadlines).toHaveBeenCalledTimes(2);
});

it("discards a pending response when the order context changes", async () => {
  let resolve!: (value: Awaited<ReturnType<typeof fetchCustomerDeadlines>>) => void;
  vi.mocked(fetchCustomerDeadlines).mockImplementationOnce(() => new Promise(r => { resolve = r; }));
  const view = render(<ProcurementCustomerDeadlines org={1} orderId={7} />);
  fireEvent.click(screen.getByText("Проверить клиентские сроки"));
  view.rerender(<ProcurementCustomerDeadlines org={2} orderId={8} />);
  resolve({ organization_id: 1, order_id: 7, status: "live_review", source: "outstanding_expected_reservations", earliest_required_arrival: "2026-12-28", unresolved_deadlines: 0, complete_customer_demand: false, at_risk: true, items: [] });
  await waitFor(() => expect(screen.getByText("Проверить клиентские сроки")).toBeEnabled());
  expect(screen.queryByText(/Есть риск опоздания/)).not.toBeInTheDocument();
});


it("shows scoped signed slack and saved penalty terms without claiming a monetary penalty", async () => {
  vi.mocked(fetchCustomerDeadlines).mockResolvedValue({ organization_id: 1, order_id: 7,
    status: "live_review", source: "outstanding_expected_reservations", earliest_required_arrival: "2026-07-02",
    slack_days: -91, unresolved_deadlines: 0, complete_customer_demand: false, at_risk: true,
    items: [{ reservation_id: 11, deal_id: 21, deal_number: "SD-2", sku_code: "A", outstanding_qty: "1.00",
      ship_deadline: "2026-07-05", required_arrival: "2026-07-02", deadline_status: "dated", at_risk: true,
      slack_days: -91, penalty_rate_pct: "1.00", penalty_cap_pct: "10.00", penalty_terms: "По договору" }] });
  render(<ProcurementCustomerDeadlines org={1} orderId={7} />);
  fireEvent.click(screen.getByRole("button", { name: "Проверить клиентские сроки" }));
  expect(await screen.findByText(/Запас по известным срокам/)).toHaveTextContent("-91");
  const item = screen.getByText(/Сделка SD-2:/);
  expect(item).toHaveTextContent("ставка штрафа 1.00%, предел 10.00%");
  expect(item).toHaveTextContent("По договору");
  expect(item).toHaveTextContent("Денежный штраф здесь не рассчитывается");
});
it("renders an explicit zero penalty separately from unknown cap and terms", async () => {
  vi.mocked(fetchCustomerDeadlines).mockResolvedValue({ organization_id: 1, order_id: 7,
    status: "live_review", source: "outstanding_expected_reservations", earliest_required_arrival: "2026-12-28",
    slack_days: 0, unresolved_deadlines: 0, complete_customer_demand: false, at_risk: false,
    items: [{ reservation_id: 11, deal_id: 21, sku_code: "A", outstanding_qty: "1.00",
      ship_deadline: "2026-12-31", required_arrival: "2026-12-28", deadline_status: "dated", at_risk: false,
      slack_days: 0, penalty_rate_pct: "0.00", penalty_cap_pct: null, penalty_terms: null }] });
  render(<ProcurementCustomerDeadlines org={1} orderId={7} />);
  fireEvent.click(screen.getByRole("button", { name: "Проверить клиентские сроки" }));
  const item = await screen.findByText(/Сделка #21:/);
  expect(item).toHaveTextContent("ставка штрафа 0.00%, предел не указан; условия: не указаны");
});
