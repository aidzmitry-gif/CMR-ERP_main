import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", () => ({
  fetchContactsResult: vi.fn(),
  addContact: vi.fn(),
  setPrimaryContact: vi.fn(),
}));

import { DealContacts } from "@/components/deal-contacts";
import * as api from "@/lib/api";

const mock = (fn: unknown) => fn as ReturnType<typeof vi.fn>;
beforeEach(() => vi.resetAllMocks());

const contact = (id: number, full_name: string, is_primary = false) => ({
  id, full_name, phone: null, email: null, is_primary,
});

function ok(data: unknown) {
  return { status: "ok" as const, data };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((res) => { resolve = res; });
  return { promise, resolve };
}

describe("DealContacts", () => {
  it("не показывает пустой список во время загрузки", async () => {
    const pending = deferred<ReturnType<typeof ok>>();
    mock(api.fetchContactsResult).mockReturnValueOnce(pending.promise);
    render(<DealContacts dealId="1" />);

    expect(screen.getByRole("status")).toHaveTextContent("Загрузка контактов");
    expect(screen.queryByText("Контактов пока нет")).not.toBeInTheDocument();
    expect(screen.queryByText("(0)")).not.toBeInTheDocument();

    pending.resolve(ok([]));
    expect(await screen.findByText("Контактов пока нет")).toBeInTheDocument();
  });

  it.each([
    [{ status: "http_error", httpStatus: 503 }, "HTTP 503"],
    [{ status: "network_error" }, "ошибка сети"],
    [{ status: "malformed_response" }, "некорректные данные"],
  ] as const)("ошибка %s показывает ошибку и retry вместо empty", async (failure, text) => {
    mock(api.fetchContactsResult)
      .mockResolvedValueOnce(failure)
      .mockResolvedValueOnce(ok([contact(2, "Ирина", true)]));
    render(<DealContacts dealId="1" />);

    expect(await screen.findByRole("alert")).toHaveTextContent(text);
    expect(screen.queryByText("Контактов пока нет")).not.toBeInTheDocument();
    expect(screen.queryByText("(0)")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Повторить" }));
    expect(await screen.findByText("Ирина")).toBeInTheDocument();
  });

  it("пустой список → добавление контакта", async () => {
    mock(api.fetchContactsResult).mockResolvedValue(ok([]));
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
    mock(api.fetchContactsResult).mockResolvedValue(ok([contact(7, "Борис")]));
    mock(api.setPrimaryContact).mockResolvedValue(true);
    render(<DealContacts dealId="1" />);
    expect(await screen.findByText("Борис")).toBeInTheDocument();
    fireEvent.click(screen.getByTitle("Сделать основным"));
    await waitFor(() => expect(api.setPrimaryContact).toHaveBeenCalledWith(7));
  });

  it.each(["false", "rejection"])("сохраняет поля контакта при %s, разрешает успешный повтор", async (failure) => {
    vi.mocked(api.fetchContactsResult).mockResolvedValueOnce(ok([]));
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
    expect(api.fetchContactsResult).toHaveBeenCalledTimes(1);

    vi.mocked(api.fetchContactsResult).mockResolvedValueOnce(ok([{
      id: 8, full_name: "Анна Иванова", phone: "+375291112233", email: "anna@x.by", is_primary: true,
    }]));
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
    const boris = contact(7, "Борис");
    vi.mocked(api.fetchContactsResult).mockResolvedValueOnce(ok([boris]));
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
    expect(api.fetchContactsResult).toHaveBeenCalledTimes(1);

    vi.mocked(api.fetchContactsResult).mockResolvedValueOnce(ok([{ ...boris, is_primary: true }]));
    fireEvent.click(primary);
    expect(await screen.findByText("основной")).toBeInTheDocument();
    expect(setPrimary).toHaveBeenNthCalledWith(2, 7);
    expect(screen.queryByTitle("Сделать основным")).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("после успешного добавления отдельно показывает ошибку refresh и не повторяет add", async () => {
    vi.mocked(api.fetchContactsResult)
      .mockResolvedValueOnce(ok([]))
      .mockResolvedValueOnce({ status: "network_error" });
    vi.mocked(api.addContact).mockResolvedValue(true);
    render(<DealContacts dealId="1" />);
    await screen.findByText("Контактов пока нет");
    fireEvent.click(screen.getByText("Добавить"));
    fireEvent.change(screen.getByPlaceholderText("ФИО контакта"), { target: { value: "Анна" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить контакт" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Контакт сохранён");
    expect(alert).toHaveTextContent("список контактов не удалось обновить");
    expect(alert).not.toHaveTextContent("Не удалось сохранить контакт");
    expect(api.addContact).toHaveBeenCalledTimes(1);
    expect(screen.queryByPlaceholderText("ФИО контакта")).not.toBeInTheDocument();
    expect(screen.getByText(/последний успешно загруженный список/)).toBeInTheDocument();
    expect(screen.queryByText("Контактов пока нет")).not.toBeInTheDocument();
    expect(screen.queryByText("(0)")).not.toBeInTheDocument();
  });

  it("после успешного назначения отдельно показывает ошибку refresh", async () => {
    vi.mocked(api.fetchContactsResult)
      .mockResolvedValueOnce(ok([contact(7, "Борис")]))
      .mockResolvedValueOnce({ status: "malformed_response" });
    vi.mocked(api.setPrimaryContact).mockResolvedValue(true);
    render(<DealContacts dealId="1" />);
    fireEvent.click(await screen.findByTitle("Сделать основным"));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Основной контакт обновлён");
    expect(alert).toHaveTextContent("некорректные данные");
    expect(alert).not.toHaveTextContent("Не удалось назначить основной контакт");
    expect(api.setPrimaryContact).toHaveBeenCalledTimes(1);
    expect(screen.getByText("Борис")).toBeInTheDocument();
    expect(screen.getByText(/последний успешно загруженный список/)).toBeInTheDocument();
  });

  it("при смене сделки игнорирует поздний ответ предыдущей загрузки", async () => {
    const first = deferred<ReturnType<typeof ok>>();
    const second = deferred<ReturnType<typeof ok>>();
    vi.mocked(api.fetchContactsResult)
      .mockImplementationOnce(() => first.promise)
      .mockImplementationOnce(() => second.promise);
    const { rerender } = render(<DealContacts dealId="1" />);
    rerender(<DealContacts dealId="2" />);

    second.resolve(ok([contact(2, "Контакт сделки 2", true)]));
    expect(await screen.findByText("Контакт сделки 2")).toBeInTheDocument();
    expect(screen.queryByText("Контакт сделки 1")).not.toBeInTheDocument();

    await act(async () => {
      first.resolve(ok([contact(1, "Контакт сделки 1", true)]));
      await first.promise;
    });
    expect(screen.getByText("Контакт сделки 2")).toBeInTheDocument();
    expect(screen.queryByText("Контакт сделки 1")).not.toBeInTheDocument();
  });

  it("после unmount успешная pending mutation не запускает refresh", async () => {
    const pendingAdd = deferred<boolean>();
    vi.mocked(api.fetchContactsResult).mockResolvedValueOnce(ok([contact(1, "Анна", true)]));
    vi.mocked(api.addContact).mockReturnValueOnce(pendingAdd.promise);
    const { unmount } = render(<DealContacts dealId="1" />);
    await screen.findByText("Анна");
    fireEvent.click(screen.getByText("Добавить"));
    fireEvent.change(screen.getByPlaceholderText("ФИО контакта"), { target: { value: "Борис" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить контакт" }));
    await waitFor(() => expect(api.addContact).toHaveBeenCalledTimes(1));

    unmount();
    await act(async () => {
      pendingAdd.resolve(true);
      await pendingAdd.promise;
    });
    expect(api.fetchContactsResult).toHaveBeenCalledTimes(1);
  });

  it("при A→B pending mutation не меняет B и не запускает повторный GET A", async () => {
    const pendingAdd = deferred<boolean>();
    const pendingB = deferred<ReturnType<typeof ok>>();
    vi.mocked(api.fetchContactsResult)
      .mockResolvedValueOnce(ok([contact(1, "Контакт A", true)]))
      .mockReturnValueOnce(pendingB.promise);
    vi.mocked(api.addContact).mockReturnValueOnce(pendingAdd.promise);
    const { rerender } = render(<DealContacts dealId="A" />);
    await screen.findByText("Контакт A");
    fireEvent.click(screen.getByText("Добавить"));
    fireEvent.change(screen.getByPlaceholderText("ФИО контакта"), { target: { value: "Новый A" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить контакт" }));
    await waitFor(() => expect(api.addContact).toHaveBeenCalledTimes(1));

    rerender(<DealContacts dealId="B" />);
    await waitFor(() => expect(api.fetchContactsResult).toHaveBeenCalledTimes(2));
    await act(async () => {
      pendingAdd.resolve(true);
      await pendingAdd.promise;
    });
    expect(api.fetchContactsResult).toHaveBeenCalledTimes(2);
    expect(screen.queryByText("Контакт A")).not.toBeInTheDocument();

    pendingB.resolve(ok([contact(2, "Контакт B", true)]));
    expect(await screen.findByText("Контакт B")).toBeInTheDocument();
    expect(screen.queryByText("Контакт A")).not.toBeInTheDocument();
  });
});
