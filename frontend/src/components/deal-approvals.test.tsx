import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", () => ({
  fetchApprovals: vi.fn(),
  requestApproval: vi.fn(),
  decideApproval: vi.fn(),
}));

import { DealApprovals } from "@/components/deal-approvals";
import * as api from "@/lib/api";

const mock = (fn: unknown) => fn as ReturnType<typeof vi.fn>;
beforeEach(() => vi.clearAllMocks());

describe("DealApprovals", () => {
  it("пустой список и отправка на согласование", async () => {
    mock(api.fetchApprovals).mockResolvedValue([]);
    mock(api.requestApproval).mockResolvedValue(true);
    render(<DealApprovals dealId="1" />);
    expect(await screen.findByText("Пока нет согласований")).toBeInTheDocument();
    fireEvent.click(screen.getByText("На согласование"));
    await waitFor(() => expect(api.requestApproval).toHaveBeenCalledWith("1", "deal.contract"));
  });

  it("показывает pending-согласование и согласует его", async () => {
    mock(api.fetchApprovals).mockResolvedValue([
      { id: 1, kind: "deal.contract", entity_ref: "deal:1", subject: "s", route: "Юрист", status: "pending", requested_by: "М", decided_by: null },
    ]);
    mock(api.decideApproval).mockResolvedValue(true);
    render(<DealApprovals dealId="1" />);
    expect(await screen.findByText(/Юрист/)).toBeInTheDocument();
    fireEvent.click(screen.getByTitle("Согласовать"));
    await waitFor(() => expect(api.decideApproval).toHaveBeenCalledWith(1, true, "Согласующий"));
  });

  it("смена вида согласования и отклонение", async () => {
    mock(api.fetchApprovals).mockResolvedValue([
      { id: 2, kind: "deal.discount", entity_ref: "deal:1", subject: "s", route: "РОП", status: "pending", requested_by: "М", decided_by: null },
    ]);
    mock(api.requestApproval).mockResolvedValue(true);
    mock(api.decideApproval).mockResolvedValue(true);
    render(<DealApprovals dealId="1" />);
    await screen.findByText(/РОП/);
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "payment.large" } });
    fireEvent.click(screen.getByText("На согласование"));
    await waitFor(() => expect(api.requestApproval).toHaveBeenCalledWith("1", "payment.large"));
    fireEvent.click(screen.getByTitle("Отклонить"));
    await waitFor(() => expect(api.decideApproval).toHaveBeenCalledWith(2, false, "Согласующий"));
  });
});
