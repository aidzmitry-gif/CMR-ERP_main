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
beforeEach(() => vi.resetAllMocks());

describe("DealContacts", () => {
  it("пустой список → добавление контакта", async () => {
    mock(api.fetchContacts).mockResolvedValue([]);
    mock(api.addContact).mockResolvedValue(true);
    render(<DealContacts dealId="1" />);
    expect(await screen.findByText("Контактов пока нет")).toBeInTheDocument();

    fireEvent.click(screen.getByText("Добавить"));
    fireEvent.change(screen.getByPlaceholderText("ФИО контакта"), { target: { value: "Анна Иванова" } });
    fireEvent.change(screen.getByPlaceholderText("Телефон"), { target: { value: "+375291112233" } });
    fireEvent.change(screen.getByPlaceholderText("Email"), { target: { value: "anna@x.by" } });
    fireEvent.click(screen.getByText("Сохранить контакт"));
    await waitFor(() =>
      expect(api.addContact).toHaveBeenCalledWith(
        "1",
        expect.objectContaining({
          full_name: "Анна Иванова",
          phone: "+375291112233",
          email: "anna@x.by",
          is_primary: true,
        }),
      ),
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

  it.each(["false", "rejection"])("сохраняет поля контакта при %s, разрешает успешный повтор", async (failure) => {
    vi.mocked(api.fetchContacts).mockResolvedValue([]);
    const addContact = vi.mocked(api.addContact);
    if (failure === "false") addContact.mockResolvedValueOnce(false);
    else addContact.mockRejectedValueOnce(new Error("network unavailable"));
    addContact.mockResolvedValueOnce(true);

    render(<DealContacts dealId="1" />);
    await screen.findByText("Контактов пока нет");
    fireEvent.click(screen.getByText("Добавить"));
    const name = screen.getByPlaceholderText("ФИО контакта");
    const phone = screen.getByPlaceholderText("Телефон");
    const email = screen.getByPlaceholderText("Email");
    const save = screen.getByRole("button", { name: "Сохранить контакт" });
    fireEvent.change(name, { target: { value: "Анна Иванова" } });
    fireEvent.change(phone, { target: { value: "+375291112233" } });
    fireEvent.change(email, { target: { value: "anna@x.by" } });
    fireEvent.click(save);

    expect(await screen.findByRole("alert")).toHaveTextContent("Не удалось сохранить контакт");
    expect(name).toHaveValue("Анна Иванова");
    expect(phone).toHaveValue("+375291112233");
    expect(email).toHaveValue("anna@x.by");
    expect(save).toBeEnabled();
    expect(api.fetchContacts).toHaveBeenCalledTimes(1);

    vi.mocked(api.fetchContacts).mockResolvedValueOnce([{
      id: 8, full_name: "Анна Иванова", phone: "+375291112233", email: "anna@x.by", is_primary: true,
    }]);
    fireEvent.click(save);
    expect(await screen.findByText("Анна Иванова")).toBeInTheDocument();
    expect(addContact).toHaveBeenNthCalledWith(2, "1", {
      full_name: "Анна Иванова", phone: "+375291112233", email: "anna@x.by", is_primary: true,
    });
    expect(screen.queryByPlaceholderText("ФИО контакта")).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("Добавить"));
    expect(screen.getByPlaceholderText("ФИО контакта")).toHaveValue("");
    expect(screen.getByPlaceholderText("Телефон")).toHaveValue("");
    expect(screen.getByPlaceholderText("Email")).toHaveValue("");
  });

  it.each(["false", "rejection"])("показывает ошибку основного контакта при %s и разрешает повтор", async (failure) => {
    const contact = { id: 7, full_name: "Борис", phone: null, email: null, is_primary: false };
    vi.mocked(api.fetchContacts).mockResolvedValue([contact]);
    const setPrimary = vi.mocked(api.setPrimaryContact);
    if (failure === "false") setPrimary.mockResolvedValueOnce(false);
    else setPrimary.mockRejectedValueOnce(new Error("network unavailable"));
    setPrimary.mockResolvedValueOnce(true);

    render(<DealContacts dealId="1" />);
    const primary = await screen.findByTitle("Сделать основным");
    fireEvent.click(primary);
    expect(await screen.findByRole("alert")).toHaveTextContent("Не удалось назначить основной контакт");
    expect(primary).toBeEnabled();
    expect(screen.queryByText("основной")).not.toBeInTheDocument();
    expect(api.fetchContacts).toHaveBeenCalledTimes(1);

    vi.mocked(api.fetchContacts).mockResolvedValueOnce([{ ...contact, is_primary: true }]);
    fireEvent.click(primary);
    expect(await screen.findByText("основной")).toBeInTheDocument();
    expect(setPrimary).toHaveBeenNthCalledWith(2, 7);
    expect(screen.queryByTitle("Сделать основным")).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
