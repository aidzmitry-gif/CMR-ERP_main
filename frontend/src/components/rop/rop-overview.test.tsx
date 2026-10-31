import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RopOverview } from "./rop-overview";
import type { RopDeal } from "@/lib/rop-overview";

const deal = (id: number, patch: Partial<RopDeal> = {}): RopDeal => ({
  id, number: `D-${id}`, title: `Учебная сделка ${id}`, counterparty: "Учебный клиент",
  stage: "new", owner: "Иван", owner_id: 7, next_step: null,
  next_step_at: null, expected_close_date: null, probability: null, ...patch,
});
const ok = (data: unknown) => ({ ok: true, json: async () => data } as Response);
const failure = (status: number) => ({ ok: false, status } as Response);
const fetchMock = vi.fn();
beforeEach(() => { fetchMock.mockReset(); vi.stubGlobal("fetch", fetchMock); });
afterEach(() => vi.unstubAllGlobals());

describe("ROP native overview", () => {
  it("loads a scoped snapshot with a real detail link and no demo money or inert decisions", async () => {
    let resolve!: (response: Response) => void;
    fetchMock.mockReturnValue(new Promise<Response>(done => { resolve = done; }));
    render(<RopOverview />);
    expect(screen.getByRole("status")).toHaveTextContent("Загружаем");
    expect(screen.queryByText("Воронка сейчас")).not.toBeInTheDocument();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(fetchMock).toHaveBeenCalledWith("/api/sales/deals", expect.objectContaining({ cache: "no-store", signal: expect.any(AbortSignal) }));
    await act(async () => resolve(ok([deal(41)])));
    expect(await screen.findByRole("link", { name: /Учебная сделка 41/ })).toHaveAttribute("href", "/crm/deals/41");
    expect(screen.getByText(/Данные ERP · снимок/)).toBeInTheDocument();
    expect(screen.getByText(/ID сотрудника: 7/)).toBeInTheDocument();
    expect(screen.queryByText(/BYN|Июнь 2026|5 000 000/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Согласовать|Отклонить/ })).not.toBeInTheDocument();
    expect(screen.getByText(/Пока не рассчитаны/)).toBeInTheDocument();
  });

  it("qualifies a successful empty snapshot by visibility instead of claiming global absence", async () => {
    fetchMock.mockResolvedValue(ok([]));
    render(<RopOverview />);
    expect(await screen.findByText("В доступной области сделок пока нет")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Открыть сделки" })).toHaveAttribute("href", "/crm/deals");
    expect(screen.queryByText("Воронка сейчас")).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it.each([[401, "Сессия истекла"], [403, "Нет доступа"], [500, "Не удалось загрузить"]])("shows HTTP %i as a failure, never as an empty snapshot", async (status, message) => {
    fetchMock.mockResolvedValue(failure(status));
    render(<RopOverview />);
    expect(await screen.findByRole("alert")).toHaveTextContent(message);
    expect(screen.queryByText("В доступной области сделок пока нет")).not.toBeInTheDocument();
    expect(screen.queryByText(/Данные ERP · снимок/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Обновить" })).toBeEnabled();
  });

  it.each(["network", "malformed"])("rejects %s failure without substituting demo metrics", async kind => {
    if (kind === "network") fetchMock.mockRejectedValue(new Error("network"));
    else fetchMock.mockResolvedValue(ok([{ id: 1 }]));
    render(<RopOverview />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Не удалось прочитать");
    expect(screen.queryByText("Воронка сейчас")).not.toBeInTheDocument();
  });

  it("clears the previous snapshot immediately on refresh and keeps it cleared after denied read", async () => {
    let resolve!: (response: Response) => void;
    fetchMock.mockResolvedValueOnce(ok([deal(41)])).mockReturnValueOnce(new Promise<Response>(done => { resolve = done; }));
    render(<RopOverview />);
    await screen.findByRole("link", { name: /Учебная сделка 41/ });
    fireEvent.click(screen.getByRole("button", { name: "Обновить" }));
    expect(screen.queryByRole("link", { name: /Учебная сделка 41/ })).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toBeInTheDocument();
    await act(async () => resolve(failure(403)));
    expect(await screen.findByRole("alert")).toHaveTextContent("Нет доступа");
    expect(screen.queryByText(/ID сотрудника/)).not.toBeInTheDocument();
    fetchMock.mockResolvedValueOnce(ok([deal(52, { owner_id: 8 })]));
    fireEvent.click(screen.getByRole("button", { name: "Обновить" }));
    expect(await screen.findByRole("link", { name: /Учебная сделка 52/ })).toBeInTheDocument();
    expect(screen.queryByText(/ID сотрудника: 7/)).not.toBeInTheDocument();
  });

  it("aborts an unmounted read and prevents its late response from replacing the next mount", async () => {
    let oldResolve!: (response: Response) => void;
    fetchMock.mockReturnValueOnce(new Promise<Response>(done => { oldResolve = done; }));
    const first = render(<RopOverview />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const signal: AbortSignal = fetchMock.mock.calls[0][1].signal;
    first.unmount();
    expect(signal.aborted).toBe(true);
    fetchMock.mockResolvedValueOnce(ok([deal(52)]));
    render(<RopOverview />);
    await screen.findByRole("link", { name: /Учебная сделка 52/ });
    await act(async () => oldResolve(ok([deal(41)])));
    expect(screen.queryByRole("link", { name: /Учебная сделка 41/ })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Учебная сделка 52/ })).toBeInTheDocument();
  });

  it("filters attention and reveals remaining actual records without issuing writes or rereads", async () => {
    fetchMock.mockResolvedValue(ok([
      ...Array.from({ length: 10 }, (_, index) => deal(index + 1)),
      deal(11, { next_step: "Уточнить заявку", next_step_at: "2020-01-01T09:00:00" }),
      deal(12, { stage: "won" }),
    ]));
    render(<RopOverview />);
    await screen.findByText("Воронка сейчас");
    expect(screen.getAllByRole("link", { name: /Учебная сделка/ })).toHaveLength(8);
    fireEvent.click(screen.getByRole("button", { name: /Показать ещё/ }));
    expect(screen.getAllByRole("link", { name: /Учебная сделка/ })).toHaveLength(11);
    const filters = within(screen.getByRole("group", { name: "Фильтр внимания" }));
    fireEvent.click(filters.getByRole("button", { name: /Просрочен шаг/ }));
    expect(screen.getAllByRole("link", { name: /Учебная сделка/ })).toHaveLength(1);
    expect(screen.getByRole("link", { name: /Учебная сделка 11/ })).toBeInTheDocument();
    fireEvent.click(filters.getByRole("button", { name: /Прошла дата закрытия/ }));
    expect(screen.getByText("В этом фильтре сделок нет.")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
