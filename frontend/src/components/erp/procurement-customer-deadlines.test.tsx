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
