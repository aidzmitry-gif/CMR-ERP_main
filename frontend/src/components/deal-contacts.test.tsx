import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", () => ({
  fetchContacts: vi.fn(),
  addContact: vi.fn(),
  setPrimaryContact: vi.fn(),
}));

import { DealContacts } from "@/components/deal-contacts";
import * as api from "@/lib/api";

const mock = (fn: unknown) => fn as ReturnType<typeof vi.fn>;
beforeEach(() => vi.clearAllMocks());

describe("DealContacts", () => {
  it("пустой список → добавление контакта", async () => {
    mock(api.fetchContacts).mockResolvedValue([]);
    mock(api.addContact).mockResolvedValue(true);
    render(<DealContacts dealId="1" />);
    expect(await screen.findByText("Контактов пока нет")).toBeInTheDocument();

    fireEvent.click(screen.getByText("Добавить"));
    fireEvent.change(screen.getByPlaceholderText("ФИО контакта"), { target: { value: "Анна Иванова" } });
    fireEvent.click(screen.getByText("Сохранить контакт"));
    await waitFor(() =>
      expect(api.addContact).toHaveBeenCalledWith("1", expect.objectContaining({ full_name: "Анна Иванова", is_primary: true })),
    );
  });

  it("назначение контакта основным", async () => {
    mock(api.fetchContacts).mockResolvedValue([
      { id: 7, full_name: "Борис", phone: null, email: null, is_primary: false },
    ]);
    mock(api.setPrimaryContact).mockResolvedValue(true);
    render(<DealContacts dealId="1" />);
    expect(await screen.findByText("Борис")).toBeInTheDocument();
    fireEvent.click(screen.getByTitle("Сделать основным"));
    await waitFor(() => expect(api.setPrimaryContact).toHaveBeenCalledWith(7));
  });
});
