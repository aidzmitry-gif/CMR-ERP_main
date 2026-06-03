import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn() }) }));
vi.mock("@/lib/api", () => ({ updateDeal: vi.fn() }));

import { DealEditButton } from "@/components/deal-edit-button";
import * as api from "@/lib/api";

const mock = (fn: unknown) => fn as ReturnType<typeof vi.fn>;
beforeEach(() => vi.clearAllMocks());

describe("DealEditButton", () => {
  it("открывает модалку и сохраняет изменения", async () => {
    mock(api.updateDeal).mockResolvedValue(true);
    render(
      <DealEditButton dealId="1" title="Поставка" amount={100} nextStep="Звонок" dealDate="12.05.2024" />,
    );
    fireEvent.click(screen.getByTitle("Редактировать сделку"));
    expect(screen.getByRole("heading", { name: "Редактировать сделку" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    await waitFor(() =>
      expect(api.updateDeal).toHaveBeenCalledWith("1", expect.objectContaining({ title: "Поставка", amount: 100 })),
    );
  });
});
