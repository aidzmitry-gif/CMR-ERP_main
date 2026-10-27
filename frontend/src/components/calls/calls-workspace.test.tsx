import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", () => ({ fetchCallsResult: vi.fn(), triggerIncomingCall: vi.fn() }));

import { CallsWorkspace } from "@/components/calls/calls-workspace";
import * as api from "@/lib/api";

const mock = (fn: unknown) => fn as ReturnType<typeof vi.fn>;
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

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

    await screen.findAllByRole("link", { name: "Компания" });
    expect(screen.getAllByRole("link").map((link) => link.getAttribute("href"))).toEqual([
      "/crm/clients/420", "/erp/spravochniki/counterparty/42", "/erp/spravochniki/counterparty/42",
    ]);
    expect(screen.getAllByRole("link").map((link) => link.getAttribute("href"))).not.toContain("/crm/clients/42");
    fireEvent.click(screen.getByRole("checkbox", { name: "Без привязанной сделки" }));
    await waitFor(() => expect(api.fetchCallsResult).toHaveBeenLastCalledWith({ unlinked: true }));
  });

  it("navigates_by_exact_counterparty_contact_and_deal_ids", async () => {
    mock(api.fetchCallsResult).mockResolvedValue({ ok: true, rows: [{
      id: 23, call_id: "synthetic-call-23", direction: "in", phone_e164: null, owner: "Synthetic owner",
      status: "ended", result: null, started_at: "2026-08-01T10:00:00", counterparty_id: 42,
      crm_client_id: 420, contact_id: 7, deal_id: 77,
    }] });
    render(<CallsWorkspace />);

    expect(await screen.findByRole("link", { name: "CRM-клиент" })).toHaveAttribute("href", "/crm/clients/420");
    expect(screen.getByRole("link", { name: "Компания" })).toHaveAttribute("href", "/erp/spravochniki/counterparty/42");
    expect(screen.getByRole("link", { name: "Контакт" })).toHaveAttribute("href", "/erp/spravochniki/counterparty/42?contact=7#counterparty-contact-7");
    expect(screen.getByRole("link", { name: "Сделка" })).toHaveAttribute("href", "/crm/deals/77");
    expect(document.getElementById("call-23")).toBeInTheDocument();
  });

  it("keeps_call_results_bound_to_current_counterparty", async () => {
    type Result = Awaited<ReturnType<typeof api.fetchCallsResult>>;
    const pendingA = deferred<Result>();
    const pendingB = deferred<Result>();
    let aRequests = 0;
    mock(api.fetchCallsResult).mockImplementation((params: api.FetchCallsParams) => {
      if (params.counterparty_id === 42) {
        aRequests += 1;
        if (aRequests > 1) return pendingA.promise;
        return Promise.resolve({ ok: true, rows: [{
          id: 42, call_id: "synthetic-call-a", direction: "in", phone_e164: null, owner: "Synthetic owner",
          status: "ended", result: "Synthetic A result", started_at: "2026-08-01T10:00:00", counterparty_id: 42,
        }] });
      }
      return pendingB.promise;
    });
    const { rerender } = render(<CallsWorkspace initialCounterpartyId={42} />);
    expect(await screen.findByText("Synthetic A result")).toBeInTheDocument();

    rerender(<CallsWorkspace initialCounterpartyId={84} />);
    await waitFor(() => expect(api.fetchCallsResult).toHaveBeenLastCalledWith({ unlinked: false, counterparty_id: 84 }));
    expect(screen.getByRole("status")).toHaveTextContent("Загрузка звонков");
    expect(screen.queryByText("Synthetic A result")).not.toBeInTheDocument();

    // Re-enter A while its prior loaded value still matches A, then make its pending response stale.
    rerender(<CallsWorkspace initialCounterpartyId={42} />);
    await waitFor(() => expect(api.fetchCallsResult).toHaveBeenCalledTimes(3));
    expect(screen.getByText("Synthetic A result")).toBeInTheDocument();
    rerender(<CallsWorkspace initialCounterpartyId={84} />);
    await waitFor(() => expect(api.fetchCallsResult).toHaveBeenCalledTimes(4));
    expect(screen.getByRole("status")).toHaveTextContent("Загрузка звонков");
    expect(screen.queryByText("Synthetic A result")).not.toBeInTheDocument();

    await act(async () => {
      pendingA.resolve({ ok: true, rows: [{
        id: 43, call_id: "synthetic-call-a-stale", direction: "in", phone_e164: null, owner: "Synthetic owner",
        status: "ended", result: "Synthetic stale A result", started_at: "2026-08-01T11:00:00", counterparty_id: 42,
      }] });
      await pendingA.promise;
    });
    expect(screen.getByRole("status")).toHaveTextContent("Загрузка звонков");
    expect(screen.queryByText(/Synthetic .*A result/)).not.toBeInTheDocument();

    await act(async () => {
      pendingB.resolve({ ok: true, rows: [{
        id: 84, call_id: "synthetic-call-b", direction: "in", phone_e164: null, owner: "Synthetic owner",
        status: "ended", result: "Synthetic B result", started_at: "2026-08-02T10:00:00", counterparty_id: 84,
      }] });
      await pendingB.promise;
    });
    expect(await screen.findByText("Synthetic B result")).toBeInTheDocument();
    expect(screen.queryByText("Synthetic A result")).not.toBeInTheDocument();
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
