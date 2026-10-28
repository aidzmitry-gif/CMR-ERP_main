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
    const approvals = [
      { id: 1, kind: "deal.contract", entity_ref: "deal:1", subject: "s", route: "Юрист", status: "pending", requested_by: "М", decided_by: null },
    ];
    let respond!: (value: typeof approvals) => void;
    const initialResponse = new Promise<typeof approvals>((resolve) => { respond = resolve; });
    mock(api.fetchApprovals).mockReturnValueOnce(initialResponse).mockResolvedValue(approvals);
    mock(api.decideApproval).mockResolvedValue(true);
    render(<DealApprovals dealId="1" />);
    expect(await screen.findByText(/Юрист/)).toBeInTheDocument();
    expect(screen.queryByTitle("Согласовать")).not.toBeInTheDocument();
    expect(api.decideApproval).not.toHaveBeenCalled();
    respond(approvals);
    const approveButton = await screen.findByTitle("Согласовать");
    expect(screen.getByText("deal.contract · Юрист")).toBeInTheDocument();
    fireEvent.click(approveButton);
    await waitFor(() => expect(api.decideApproval).toHaveBeenCalledWith(1, true, "Согласующий"));
    await waitFor(() => expect(approveButton).toBeEnabled());
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
    // Дожидаемся, что pending-кнопка «Отклонить» доступна после возможного re-render
    // (флак на CI: клик улетал до того, как состояние стабилизировалось).
    const rejectBtn = await screen.findByTitle("Отклонить");
    fireEvent.click(rejectBtn);
    await waitFor(() => expect(api.decideApproval).toHaveBeenCalledWith(2, false, "Согласующий"));
  });
});
