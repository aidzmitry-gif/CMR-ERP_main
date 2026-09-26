import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", () => ({ fetchCallsResult: vi.fn(), triggerIncomingCall: vi.fn() }));

import { CallsWorkspace } from "@/components/calls/calls-workspace";
import * as api from "@/lib/api";

const mock = (fn: unknown) => fn as ReturnType<typeof vi.fn>;
beforeEach(() => vi.clearAllMocks());

describe("CallsWorkspace", () => {
  it("журнал звонков + симуляция входящего", async () => {
    mock(api.fetchCallsResult).mockResolvedValue({ ok: true, rows: [
      {
        id: 1,
        call_id: "c1",
        direction: "in",
        phone_e164: null,
        owner: "Тестовый продавец",
        status: "ended",
        result: "Результат теста",
        started_at: "2026-06-23T10:00:00",
      },
    ] });
    mock(api.triggerIncomingCall).mockResolvedValue(true);
    render(<CallsWorkspace />);
    expect(await screen.findByText("Результат теста")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Симулировать входящий"));
    await waitFor(() => expect(api.triggerIncomingCall).toHaveBeenCalled());
  });

  it("filters unlinked calls and links only an explicitly returned CRM client ID", async () => {
    mock(api.fetchCallsResult).mockResolvedValue({ ok: true, rows: [
      { id: 1, call_id: "synthetic-1", direction: "in", phone_e164: null, owner: "Тест", status: "ended", deal_id: null, counterparty_id: 42, crm_client_id: 420, started_at: "2026-09-01T10:00:00" },
      { id: 2, call_id: "synthetic-2", direction: "out", phone_e164: null, owner: "Тест", status: "ended", deal_id: null, counterparty_id: 42, started_at: "2026-09-01T10:01:00" },
    ] });
    render(<CallsWorkspace />);

    expect(await screen.findByRole("link", { name: "Открыть карточку" })).toHaveAttribute("href", "/crm/clients/420");
    expect(screen.getAllByRole("link").map((link) => link.getAttribute("href"))).not.toContain("/crm/clients/42");
    fireEvent.click(screen.getByRole("checkbox", { name: "Без привязанной сделки" }));
    await waitFor(() => expect(api.fetchCallsResult).toHaveBeenLastCalledWith({ unlinked: true }));
  });

  it("keeps loading failure distinct from an empty result", async () => {
    mock(api.fetchCallsResult).mockResolvedValueOnce({ ok: false, error: "Не удалось загрузить журнал звонков." })
      .mockResolvedValueOnce({ ok: true, rows: [] });
    render(<CallsWorkspace />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Не удалось загрузить журнал звонков");
    expect(screen.queryByText("Звонков по выбранному фильтру нет.")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Повторить" }));
    expect(await screen.findByText("Звонков по выбранному фильтру нет.")).toBeInTheDocument();
  });
});
