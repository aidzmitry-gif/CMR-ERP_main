import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn() }) }));
vi.mock("@/lib/api", () => ({ updateDealFieldsIfCurrent: vi.fn() }));

import { DealEditButton } from "@/components/deal-edit-button";
import * as api from "@/lib/api";

const mock = (fn: unknown) => fn as ReturnType<typeof vi.fn>;
beforeEach(() => vi.clearAllMocks());

function open() {
  render(<DealEditButton dealId="1" editToken={"a".repeat(64)} title="Поставка" amount={100} nextStep="Звонок" dealDate="12.05.2024" />);
  fireEvent.click(screen.getByTitle("Редактировать сделку"));
}

describe("DealEditButton", () => {
  it("редактирует поля и сохраняет изменения", async () => {
    mock(api.updateDealFieldsIfCurrent).mockResolvedValue("saved");
    open();
    expect(screen.getByRole("heading", { name: "Редактировать сделку" })).toBeInTheDocument();

    const textboxes = screen.getAllByRole("textbox") as HTMLInputElement[];
    fireEvent.change(textboxes[0], { target: { value: "Новая поставка" } }); // Описание
    // next_step теперь datetime-local — не входит в role="textbox", ищем напрямую
    const nextStepInput = document.querySelector('input[type="datetime-local"]') as HTMLInputElement;
    fireEvent.change(nextStepInput, { target: { value: "2026-07-15T09:00" } });
    fireEvent.change(screen.getByPlaceholderText("12.05.2024"), { target: { value: "01.06.2026" } });
    // Несколько number-инпутов (сумма + штраф %/день + потолок) — сумма первая.
    fireEvent.change(screen.getAllByRole("spinbutton")[0], { target: { value: "555" } });

    fireEvent.click(screen.getByRole("button", { name: "Сохранить и закрыть" }));
    await waitFor(() =>
      expect(api.updateDealFieldsIfCurrent).toHaveBeenCalledWith(
        "1",
        expect.objectContaining({
          title: "Новая поставка",
          amount: 555,
          deal_date: "01.06.2026",
          next_step: "2026-07-15T09:00",
        }),
        "a".repeat(64),
      ),
    );
    await waitFor(() => expect(screen.queryByRole("heading", { name: "Редактировать сделку" })).toBeNull());
  });

  it("сохраняет ввод и форму открытой, если сервер отказал", async () => {
    mock(api.updateDealFieldsIfCurrent).mockResolvedValue("unconfirmed");
    open();
    fireEvent.change(screen.getByRole("textbox", { name: "Описание" }), { target: { value: "Исправленная поставка" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить и закрыть" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Сервер не подтвердил сохранение");
    expect(screen.getByRole("textbox", { name: "Описание" })).toHaveValue("Исправленная поставка");
    expect(screen.getByRole("button", { name: "Сохранить и закрыть" })).toBeEnabled();
  });

  it("оставляет конфликтующие правки открытыми для сверки", async () => {
    mock(api.updateDealFieldsIfCurrent).mockResolvedValue("conflict");
    open();
    fireEvent.change(screen.getByRole("textbox", { name: "Описание" }), { target: { value: "Моя версия" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить и закрыть" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Сделка изменена другим сотрудником");
    expect(screen.getByRole("textbox", { name: "Описание" })).toHaveValue("Моя версия");
  });

  it("предупреждает о несохранённых правках при закрытии и уходе со страницы", () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    open();
    fireEvent.change(screen.getByRole("textbox", { name: "Описание" }), { target: { value: "Исправленная поставка" } });
    fireEvent.click(screen.getByRole("button", { name: "Отмена" }));
    expect(screen.getByRole("heading", { name: "Редактировать сделку" })).toBeInTheDocument();
    expect(confirm).toHaveBeenCalledOnce();
    const unload = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(unload);
    expect(unload.defaultPrevented).toBe(true);
    confirm.mockReturnValue(true);
    fireEvent.click(screen.getByRole("button", { name: "Отмена" }));
    expect(screen.queryByRole("heading", { name: "Редактировать сделку" })).toBeNull();
    const afterClose = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(afterClose);
    expect(afterClose.defaultPrevented).toBe(false);
    confirm.mockRestore();
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
