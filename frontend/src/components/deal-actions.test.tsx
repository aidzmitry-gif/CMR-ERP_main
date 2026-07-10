import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", () => ({ updateDeal: vi.fn() }));

import { DealActions } from "@/components/deal-actions";
import * as api from "@/lib/api";

const mock = (fn: unknown) => fn as ReturnType<typeof vi.fn>;
beforeEach(() => {
  vi.clearAllMocks();
  mock(api.updateDeal).mockResolvedValue(true);
});

describe("DealActions", () => {
  it("не показывает кнопку «Фокус» (убрана по решению оператора)", () => {
    render(<DealActions dealId="1" starred={false} priority="Средний" />);
    expect(screen.queryByText("Фокус")).toBeNull();
  });

  it("циклически меняет приоритет Средний → Низкий", async () => {
    render(<DealActions dealId="1" starred={false} priority="Средний" />);
    fireEvent.click(screen.getByText("Средний"));
    await waitFor(() => expect(api.updateDeal).toHaveBeenCalledWith("1", { priority: "Низкий" }));
    expect(screen.getByText("Низкий")).toBeInTheDocument();
  });

  it("переключает «Избранное»", async () => {
    render(<DealActions dealId="1" starred={false} priority="Высокий" />);
    fireEvent.click(screen.getByText("В избранное"));
    await waitFor(() => expect(api.updateDeal).toHaveBeenCalledWith("1", { starred: true }));
    expect(screen.getByText("В избранном")).toBeInTheDocument();
  });
});
