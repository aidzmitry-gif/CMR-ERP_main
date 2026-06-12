import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", () => ({
  fetchDealTasks: vi.fn().mockResolvedValue([
    {
      id: 1, deal_id: 1, title: "Перезвонить", kind: "call", assignee_id: null,
      due_at: "2020-01-01T10:00:00", status: "open", result: null, overdue: true,
    },
    {
      id: 2, deal_id: 1, title: "Готово", kind: "other", assignee_id: null,
      due_at: null, status: "done", result: "ok", overdue: false,
    },
  ]),
  createDealTask: vi.fn().mockResolvedValue(true),
  completeDealTask: vi.fn().mockResolvedValue(true),
}));

import { DealTasks } from "@/components/deal-tasks";

describe("DealTasks", () => {
  it("рендерит задачи, считает открытые и подсвечивает просрочку", async () => {
    render(<DealTasks dealId="1" />);
    await waitFor(() => expect(screen.getByText("Перезвонить")).toBeInTheDocument());
    expect(screen.getByText("Готово")).toBeInTheDocument();
    expect(screen.getByText("(1 откр.)")).toBeInTheDocument(); // только одна открытая
    expect(screen.getByText(/просрочено/)).toBeInTheDocument();
  });
});
