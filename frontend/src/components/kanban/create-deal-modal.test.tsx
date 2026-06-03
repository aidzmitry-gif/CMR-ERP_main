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
});
