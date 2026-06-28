import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn() }) }));
vi.mock("@/lib/api", () => ({ updateDeal: vi.fn() }));

import { DealEditButton } from "@/components/deal-edit-button";
import * as api from "@/lib/api";

const mock = (fn: unknown) => fn as ReturnType<typeof vi.fn>;
beforeEach(() => vi.clearAllMocks());

function open() {
  render(<DealEditButton dealId="1" title="Поставка" amount={100} nextStep="Звонок" dealDate="12.05.2024" />);
  fireEvent.click(screen.getByTitle("Редактировать сделку"));
}

describe("DealEditButton", () => {
  it("редактирует поля и сохраняет изменения", async () => {
    mock(api.updateDeal).mockResolvedValue(true);
    open();
    expect(screen.getByRole("heading", { name: "Редактировать сделку" })).toBeInTheDocument();

    const textboxes = screen.getAllByRole("textbox") as HTMLInputElement[];
    fireEvent.change(textboxes[0], { target: { value: "Новая поставка" } }); // Описание
    fireEvent.change(textboxes[2], { target: { value: "Встреча" } }); // Следующий шаг
    fireEvent.change(screen.getByPlaceholderText("12.05.2024"), { target: { value: "01.06.2026" } });
    // Несколько number-инпутов (сумма + штраф %/день + потолок) — сумма первая.
    fireEvent.change(screen.getAllByRole("spinbutton")[0], { target: { value: "555" } });

    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    await waitFor(() =>
      expect(api.updateDeal).toHaveBeenCalledWith(
        "1",
        expect.objectContaining({
          title: "Новая поставка",
          amount: 555,
          deal_date: "01.06.2026",
          next_step: "Встреча",
        }),
      ),
    );
  });

  it("закрывается по кнопке Отмена", () => {
    open();
    fireEvent.click(screen.getByRole("button", { name: "Отмена" }));
    expect(screen.queryByRole("heading", { name: "Редактировать сделку" })).toBeNull();
  });

  it("закрывается по крестику", () => {
    open();
    const closeBtn = screen.getByRole("heading", { name: "Редактировать сделку" }).nextElementSibling as HTMLElement;
    fireEvent.click(closeBtn);
    expect(screen.queryByRole("heading", { name: "Редактировать сделку" })).toBeNull();
  });
});
