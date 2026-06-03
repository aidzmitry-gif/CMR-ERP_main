import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", () => ({ lookupCounterparty: vi.fn() }));

import { CreateDealModal } from "@/components/kanban/create-deal-modal";
import * as api from "@/lib/api";
import type { Stage } from "@/lib/types";

const mock = (fn: unknown) => fn as ReturnType<typeof vi.fn>;
const stages: Stage[] = [{ id: "new", title: "Новая заявка", color: "#000", count: 0, sum: 0, deals: [] }];
beforeEach(() => vi.clearAllMocks());

describe("CreateDealModal", () => {
  it("заполнение и отправка формы вызывает onCreate", async () => {
    const onCreate = vi.fn().mockResolvedValue(true);
    render(<CreateDealModal stages={stages} defaultStage="new" onClose={() => {}} onCreate={onCreate} />);
    fireEvent.change(screen.getByPlaceholderText("CRM-2024-0200"), { target: { value: "CRM-NEW" } });
    fireEvent.change(screen.getByPlaceholderText("ООО ..."), { target: { value: "ООО Икс" } });
    fireEvent.change(screen.getByPlaceholderText("Поставка ..."), { target: { value: "Поставка АКБ" } });
    fireEvent.click(screen.getByRole("button", { name: "Создать" }));
    await waitFor(() =>
      expect(onCreate).toHaveBeenCalledWith(
        expect.objectContaining({ number: "CRM-NEW", counterparty: "ООО Икс", title: "Поставка АКБ" }),
      ),
    );
  });

  it("поиск по УНП подставляет контрагента", async () => {
    mock(api.lookupCounterparty).mockResolvedValue({
      unp: "191234567",
      name: "ООО Найдено",
      address: "Минск",
      status: "Действующий",
    });
    render(<CreateDealModal stages={stages} defaultStage="new" onClose={() => {}} onCreate={vi.fn()} />);
    fireEvent.change(screen.getByPlaceholderText("191234567"), { target: { value: "191234567" } });
    fireEvent.click(screen.getByRole("button", { name: /Найти/ }));
    await waitFor(() => expect(api.lookupCounterparty).toHaveBeenCalledWith("191234567"));
    expect((screen.getByPlaceholderText("ООО ...") as HTMLInputElement).value).toBe("ООО Найдено");
  });

  it("сообщает, если по УНП ничего не найдено", async () => {
    mock(api.lookupCounterparty).mockResolvedValue(null);
    render(<CreateDealModal stages={stages} defaultStage="new" onClose={() => {}} onCreate={vi.fn()} />);
    fireEvent.change(screen.getByPlaceholderText("191234567"), { target: { value: "000" } });
    fireEvent.click(screen.getByRole("button", { name: /Найти/ }));
    expect(await screen.findByText(/ничего не найдено/i)).toBeInTheDocument();
  });

  it("меняет приоритет, стадию, ответственного и сумму", async () => {
    const onCreate = vi.fn().mockResolvedValue(true);
    const twoStages = [
      stages[0],
      { id: "won", title: "Закрыто", color: "#000", count: 0, sum: 0, deals: [] },
    ];
    render(<CreateDealModal stages={twoStages} defaultStage="new" onClose={() => {}} onCreate={onCreate} />);
    fireEvent.change(screen.getByPlaceholderText("CRM-2024-0200"), { target: { value: "CRM-F" } });
    fireEvent.change(screen.getByPlaceholderText("ООО ..."), { target: { value: "ООО Ф" } });
    fireEvent.change(screen.getByPlaceholderText("Поставка ..."), { target: { value: "Тест" } });
    fireEvent.change(screen.getByPlaceholderText("Иванов И.И."), { target: { value: "Сидоров" } });
    const [amount] = screen.getAllByRole("spinbutton") as HTMLInputElement[];
    fireEvent.change(amount, { target: { value: "7000" } });
    const selects = screen.getAllByRole("combobox") as HTMLSelectElement[];
    fireEvent.change(selects[0], { target: { value: "Высокий" } });
    fireEvent.change(selects[1], { target: { value: "won" } });

    fireEvent.click(screen.getByRole("button", { name: "Создать" }));
    await waitFor(() =>
      expect(onCreate).toHaveBeenCalledWith(
        expect.objectContaining({ owner: "Сидоров", amount: 7000, priority: "Высокий", stage: "won" }),
      ),
    );
  });
});
