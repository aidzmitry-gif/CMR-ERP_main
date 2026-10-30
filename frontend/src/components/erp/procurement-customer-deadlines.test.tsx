import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { ProcurementCustomerDeadlines } from "./procurement-customer-deadlines";
import { fetchCustomerDeadlines } from "@/lib/procurement-machine";
vi.mock("@/lib/procurement-machine", () => ({ fetchCustomerDeadlines: vi.fn() }));
beforeEach(() => vi.resetAllMocks());

function reviewedTerms(): Awaited<ReturnType<typeof fetchCustomerDeadlines>> {
  return { organization_id: 1, order_id: 7, status: "live_review", source: "outstanding_expected_reservations",
    earliest_required_arrival: "2026-12-28", unresolved_deadlines: 0, complete_customer_demand: false, at_risk: true,
    items: [{ reservation_id: 4, deal_id: 3, sku_code: "A", outstanding_qty: "60.00", ship_deadline: "2026-12-31",
      required_arrival: "2026-12-28", deadline_status: "dated", at_risk: true }],
    risk_details: { version: 1, required_by: "2026-12-31", target_arrival_date: "2027-01-01", slack_days: -4,
      schedule_start_date: "2025-12-23", schedule_start_in_past: true,
      items: [{ reservation_id: 4, number: "DEAL-EXPECTED", counterparty: "Synthetic buyer", required_by: "2026-12-31",
        slack_days: -4, penalty_rate_pct: "1.00", penalty_cap_pct: "10.00", penalty_terms: "Synthetic contract" }] } };
}

it("shows lateness, past schedule start and current contractual terms without calculating a fine", async () => {
  vi.mocked(fetchCustomerDeadlines).mockResolvedValue(reviewedTerms());
  render(<ProcurementCustomerDeadlines org={1} orderId={7} />);
  fireEvent.click(screen.getByText("Проверить клиентские сроки"));
  expect(await screen.findByText(/Опоздание к требуемой дате прихода: 4 дн/)).toBeInTheDocument();
  expect(screen.getByText(/Плановое начало маршрута уже в прошлом/)).toBeInTheDocument();
  expect(screen.getByText(/Сделка DEAL-EXPECTED/)).toBeInTheDocument();
  expect(screen.getByText(/ставка 1.00%; предел 10.00%.*Synthetic contract/)).toBeInTheDocument();
  expect(screen.getByText(/сумма штрафа не рассчитана/)).toBeInTheDocument();
});

it("shows positive slack without calling it lateness", async () => {
  const value = reviewedTerms(); value.risk_details!.slack_days = 5;
  value.risk_details!.schedule_start_in_past = false; value.at_risk = false;
  vi.mocked(fetchCustomerDeadlines).mockResolvedValue(value);
  render(<ProcurementCustomerDeadlines org={1} orderId={7} />);
  fireEvent.click(screen.getByText("Проверить клиентские сроки"));
  expect(await screen.findByText(/Запас до требуемой даты прихода: 5 дн/)).toBeInTheDocument();
  expect(screen.queryByText(/Опоздание к требуемой дате/)).not.toBeInTheDocument();
});

it("keeps missing penalty terms unknown and an explicit zero cap visible", async () => {
  const value = reviewedTerms(); value.risk_details!.slack_days = null;
  value.risk_details!.items[0].penalty_rate_pct = null; value.risk_details!.items[0].penalty_cap_pct = "0.00";
  value.risk_details!.items[0].penalty_terms = null; value.unresolved_deadlines = 1;
  vi.mocked(fetchCustomerDeadlines).mockResolvedValue(value);
  render(<ProcurementCustomerDeadlines org={1} orderId={7} onUseDate={vi.fn()} />);
  fireEvent.click(screen.getByText("Проверить клиентские сроки"));
  expect(await screen.findByText(/Запас по сроку не определён/)).toBeInTheDocument();
  expect(screen.getByText(/ставка не указана; предел 0.00%.*Текст условий не указан/)).toBeInTheDocument();
  expect(screen.getByText("Обновить сроки и подставить дату в план")).toBeDisabled();
});
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
