import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

// Дочерние компоненты тянут сеть/сложную логику — мокаем стабами, чтобы проверить
// именно поведение PlanningTabs (тоггл роли, баннер, read-only обёртку, проброс пропсов).
vi.mock("@/components/plan/plan-constructor", () => ({
  PlanConstructor: ({ ownerId }: { ownerId: number }) => (
    <div data-testid="plan-constructor">Конструктор владелец={ownerId}</div>
  ),
}));
vi.mock("@/components/deal-plan-editor", () => ({
  DealPlanEditor: ({ ownerId, role }: { ownerId: number; role: string }) => (
    <div data-testid="deal-plan-editor">
      Редактор владелец={ownerId} роль={role}
    </div>
  ),
}));

import { PlanningTabs } from "@/components/plan/planning-tabs";

describe("PlanningTabs", () => {
  it("для роли продавца стартует в виде «продавец»: без баннера РОПа, редактор получает role=sales", () => {
    render(<PlanningTabs ownerId={7} role="sales" />);

    expect(screen.getByRole("button", { name: "Я — продавец" })).toHaveClass("bg-surface");
    expect(screen.getByRole("button", { name: "Я — РОП" })).not.toHaveClass("bg-surface");
    expect(screen.queryByText(/Режим РОПа/)).not.toBeInTheDocument();
    expect(screen.getByTestId("deal-plan-editor")).toHaveTextContent("роль=sales");
    // конструктор доступен для ввода (не read-only)
    expect(screen.getByTestId("plan-constructor").parentElement).not.toHaveClass("pointer-events-none");
  });

  it("для роли рол (sales_head) стартует в виде «РОП»: показан баннер, конструктор read-only, role=rop", () => {
    render(<PlanningTabs ownerId={9} role="sales_head" />);

    expect(screen.getByRole("button", { name: "Я — РОП" })).toHaveClass("bg-surface");
    expect(screen.getByText(/Режим РОПа · план собрал/)).toBeInTheDocument();
    expect(screen.getByTestId("deal-plan-editor")).toHaveTextContent("роль=rop");
    const wrapper = screen.getByTestId("plan-constructor").parentElement as HTMLElement;
    expect(wrapper).toHaveClass("pointer-events-none");
    expect(wrapper).toHaveAttribute("aria-disabled", "true");
  });

  it("роль не из списка РОПов (напр. незнакомая строка) стартует как продавец", () => {
    render(<PlanningTabs ownerId={1} role="некто" />);
    expect(screen.getByRole("button", { name: "Я — продавец" })).toHaveClass("bg-surface");
    expect(screen.getByTestId("deal-plan-editor")).toHaveTextContent("роль=sales");
  });

  it("клик «Я — РОП» переключает вид: появляется баннер, конструктор блокируется, role=rop у редактора", () => {
    render(<PlanningTabs ownerId={7} role="sales" />);

    fireEvent.click(screen.getByRole("button", { name: "Я — РОП" }));

    expect(screen.getByRole("button", { name: "Я — РОП" })).toHaveClass("bg-surface");
    expect(screen.getByRole("button", { name: "Я — продавец" })).not.toHaveClass("bg-surface");
    expect(screen.getByText(/Режим РОПа · план собрал/)).toBeInTheDocument();
    expect(screen.getByTestId("deal-plan-editor")).toHaveTextContent("роль=rop");
    const wrapper = screen.getByTestId("plan-constructor").parentElement as HTMLElement;
    expect(wrapper).toHaveClass("pointer-events-none");
  });

  it("обратный клик «Я — продавец» из РОП-вида убирает баннер и снимает read-only", () => {
    render(<PlanningTabs ownerId={7} role="sales_head" />);
    // стартуем в РОП-виде
    expect(screen.getByText(/Режим РОПа · план собрал/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Я — продавец" }));

    expect(screen.queryByText(/Режим РОПа/)).not.toBeInTheDocument();
    expect(screen.getByTestId("deal-plan-editor")).toHaveTextContent("роль=sales");
    const wrapper = screen.getByTestId("plan-constructor").parentElement as HTMLElement;
    expect(wrapper).not.toHaveClass("pointer-events-none");
    expect(wrapper).not.toHaveAttribute("aria-disabled");
  });

  it("ownerId пробрасывается в оба дочерних компонента без изменений", () => {
    render(<PlanningTabs ownerId={42} role="sales" />);
    expect(screen.getByTestId("plan-constructor")).toHaveTextContent("владелец=42");
    expect(screen.getByTestId("deal-plan-editor")).toHaveTextContent("владелец=42");
  });
});
