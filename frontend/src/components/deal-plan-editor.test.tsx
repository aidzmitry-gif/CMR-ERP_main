import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { PlanRow } from "@/lib/api";

// nextMonthKey зависит от текущей даты — фиксируем, чтобы <input type="month"> был детерминирован.
vi.mock("@/lib/plan-constructor", () => ({
  nextMonthKey: () => "2026-08",
}));

// API данных плана — моки: компонент тестируем изолированно от сети.
vi.mock("@/lib/api", () => ({
  fetchPlans: vi.fn(),
  submitPlan: vi.fn(),
}));
// Действия согласования РОПа — моки.
vi.mock("@/lib/planning-api", () => ({
  decidePlanComment: vi.fn(),
  reopenPlan: vi.fn(),
}));

import { DealPlanEditor } from "@/components/deal-plan-editor";
import * as api from "@/lib/api";
import * as planningApi from "@/lib/planning-api";

const fetchPlans = api.fetchPlans as ReturnType<typeof vi.fn>;
const submitPlan = api.submitPlan as ReturnType<typeof vi.fn>;
const decidePlanComment = planningApi.decidePlanComment as ReturnType<typeof vi.fn>;
const reopenPlan = planningApi.reopenPlan as ReturnType<typeof vi.fn>;

/** Фабрика строки плана PlanRow под конкретную метрику/статус/значение. */
function row(
  metric: string,
  target: number,
  status: PlanRow["status"],
  overrides: Partial<PlanRow & { rop_comment?: string | null }> = {},
): PlanRow & { rop_comment?: string | null } {
  return {
    id: metric.length, // стабильный ненулевой id
    owner_id: 7,
    metric,
    period_type: "month",
    period_key: "2026-08",
    target,
    status,
    approved_by: null,
    approved_at: null,
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  fetchPlans.mockResolvedValue([]);
  submitPlan.mockResolvedValue(true);
  decidePlanComment.mockResolvedValue(true);
  reopenPlan.mockResolvedValue(true);
});

describe("DealPlanEditor", () => {
  it("состояние загрузки: пока fetchPlans не ответил — «Загрузка плана…»", async () => {
    // висящий промис держит статус loading
    fetchPlans.mockReturnValue(new Promise(() => {}));
    render(<DealPlanEditor ownerId={7} role="seller" />);
    expect(screen.getByText("План на согласовании")).toBeInTheDocument();
    expect(await screen.findByText(/Загрузка плана/)).toBeInTheDocument();
  });

  it("данные: рендерит 5 живых метрик, деньги в BYN и статус-бейдж", async () => {
    fetchPlans.mockResolvedValue([
      row("leads", 120, "pending_approval"),
      row("gross_profit", 50000, "pending_approval"),
      row("new_deals_amount", 300000, "approved"),
    ]);
    render(<DealPlanEditor ownerId={7} role="seller" />);

    // строка «Валовая прибыль» отрисовалась → данные загружены
    expect(await screen.findByText("Валовая прибыль")).toBeInTheDocument();
    expect(screen.getByText("Новые лиды")).toBeInTheDocument();
    // money-метрика форматируется как BYN (formatByn), count — просто число
    expect(screen.getByText("50 000 BYN")).toBeInTheDocument();
    expect(screen.getByText("120")).toBeInTheDocument();
    // хотя бы один бейдж «на согласовании» присутствует
    expect(screen.getAllByText("на согласовании").length).toBeGreaterThan(0);
  });

  it("ошибка загрузки: показывает сообщение и по «Повторить» перезапрашивает", async () => {
    fetchPlans.mockRejectedValueOnce(new Error("boom"));
    render(<DealPlanEditor ownerId={7} role="seller" />);

    expect(await screen.findByText("Не удалось загрузить план.")).toBeInTheDocument();
    expect(fetchPlans).toHaveBeenCalledTimes(1);

    // на повтор отдаём валидные данные
    fetchPlans.mockResolvedValueOnce([row("leads", 10, "draft")]);
    fireEvent.click(screen.getByRole("button", { name: "Повторить" }));

    expect(await screen.findByText("Новые лиды")).toBeInTheDocument();
    await waitFor(() => expect(fetchPlans).toHaveBeenCalledTimes(2));
  });

  it("продавец: «Отправить план РОПу →» шлёт все черновики через submitPlan", async () => {
    fetchPlans.mockResolvedValue([
      row("leads", 100, "draft"),
      row("cold_calls", 200, "draft"),
      row("gross_profit", 50000, "approved"), // не черновик — не отправляется
    ]);
    render(<DealPlanEditor ownerId={7} role="seller" />);

    const send = await screen.findByRole("button", { name: /Отправить план РОПу/ });
    fireEvent.click(send);

    await waitFor(() => expect(submitPlan).toHaveBeenCalledTimes(2));
    // отправлены именно черновики (id = длина имени метрики): leads=5, cold_calls=10
    const ids = submitPlan.mock.calls.map((c) => c[0]).sort((a, b) => a - b);
    expect(ids).toEqual([5, 10]);
  });

  it("продавец: построчная кнопка «На согласование» зовёт submitPlan для этой строки", async () => {
    fetchPlans.mockResolvedValue([row("leads", 100, "draft")]);
    render(<DealPlanEditor ownerId={7} role="seller" />);

    fireEvent.click(await screen.findByRole("button", { name: "На согласование" }));
    await waitFor(() => expect(submitPlan).toHaveBeenCalledWith(5)); // id "leads".length = 5
    expect(await screen.findByText(/Отправлено на согласование/)).toBeInTheDocument();
  });

  it("РОП: комментарий + «Согласовать» вызывает decidePlanComment(id, true, comment)", async () => {
    fetchPlans.mockResolvedValue([row("leads", 100, "pending_approval")]);
    render(<DealPlanEditor ownerId={7} role="rop" />);

    const commentInput = await screen.findByPlaceholderText("комментарий продавцу…");
    fireEvent.change(commentInput, { target: { value: "подними до 150" } });
    fireEvent.click(screen.getByRole("button", { name: "Согласовать" }));

    await waitFor(() =>
      expect(decidePlanComment).toHaveBeenCalledWith(5, true, "подними до 150"),
    );
    expect(await screen.findByText(/Согласовано: leads/)).toBeInTheDocument();
  });

  it("РОП: «Отклонить» вызывает decidePlanComment(id, false, …)", async () => {
    fetchPlans.mockResolvedValue([row("leads", 100, "pending_approval")]);
    render(<DealPlanEditor ownerId={7} role="rop" />);

    fireEvent.click(await screen.findByRole("button", { name: "Отклонить" }));
    // комментарий не вводили → в decide уходит comments[metric] === undefined
    await waitFor(() =>
      expect(decidePlanComment).toHaveBeenCalledWith(5, false, undefined),
    );
    expect(await screen.findByText(/Отклонено: leads/)).toBeInTheDocument();
  });

  it("РОП: согласованную строку можно «Вернуть на доработку» → reopenPlan с причиной", async () => {
    fetchPlans.mockResolvedValue([row("leads", 100, "approved")]);
    render(<DealPlanEditor ownerId={7} role="rop" />);

    const reasonInput = await screen.findByPlaceholderText("причина возврата…");
    fireEvent.change(reasonInput, { target: { value: "пересмотрим" } });
    fireEvent.click(screen.getByRole("button", { name: "Вернуть на доработку" }));

    await waitFor(() => expect(reopenPlan).toHaveBeenCalledWith(5, "пересмотрим"));
    expect(await screen.findByText(/План возвращён в работу/)).toBeInTheDocument();
  });

  it("тоггл доп. метрик: «+ ещё метрики» показывает «Тендеры, сумма», повтор — скрывает", async () => {
    fetchPlans.mockResolvedValue([row("leads", 100, "draft")]);
    render(<DealPlanEditor ownerId={7} role="seller" />);

    await screen.findByText("Новые лиды");
    expect(screen.queryByText("Тендеры, сумма")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /ещё метрики вручную/ }));
    expect(screen.getByText("Тендеры, сумма")).toBeInTheDocument();
    expect(screen.getByText("Поступления с НДС")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /свернуть доп\. метрики/ }));
    expect(screen.queryByText("Тендеры, сумма")).not.toBeInTheDocument();
  });

  it("комментарий РОПа из бэка (rop_comment) отображается под метрикой", async () => {
    fetchPlans.mockResolvedValue([
      row("leads", 100, "rejected", { rop_comment: "мало, добавь холодных" }),
    ]);
    render(<DealPlanEditor ownerId={7} role="seller" />);

    expect(await screen.findByText(/мало, добавь холодных/)).toBeInTheDocument();
    // статус «на доработку» для rejected
    expect(screen.getByText("на доработку")).toBeInTheDocument();
  });

  it("шапка-бейдж «согласовано», когда все живые метрики одобрены", async () => {
    fetchPlans.mockResolvedValue([
      row("leads", 100, "approved"),
      row("cold_calls", 200, "approved"),
      row("gross_profit", 50000, "approved"),
      row("new_deals_amount", 300000, "approved"),
      row("new_deals_count", 12, "approved"),
    ]);
    render(<DealPlanEditor ownerId={7} role="rop" />);

    await screen.findByText("Новые лиды");
    const header = screen.getByText("План на согласовании").closest("div") as HTMLElement;
    expect(within(header).getByText("согласовано")).toBeInTheDocument();
  });
});
