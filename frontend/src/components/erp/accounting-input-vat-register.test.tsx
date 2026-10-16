import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { AccountingInputVatRegister, type InputVatRegisterRow } from "./accounting-input-vat-register";

const row: InputVatRegisterRow = {
  entry_id: 4, line_id: 9, entry_digest: "a".repeat(64), posting_date: "2026-09-01", side: "debit", amount: "20.00", currency: "BYN", source: "vat", source_version: 1, registered: false, deduction_status: "not_assessed",
};
const ok = (data: unknown) => Promise.resolve(new Response(JSON.stringify(data), { status: 200, headers: { "Content-Type": "application/json" } }));

describe("AccountingInputVatRegister", () => {
  it("checks and confirms one explicit register package", async () => {
    const fetcher = vi.fn()
      .mockImplementationOnce(() => ok({ organization_id: 7, source: { entry_id: 4, line_id: 9 }, status: "reviewed_input_vat", register_available: true, statutory_certified: false, deduction_assessed: false, digest: "b".repeat(64) }))
      .mockImplementationOnce(() => ok({ organization_id: 7, principal: "chief", can_confirm: true }))
      .mockImplementationOnce(() => ok({ organization_id: 7, entry_id: 4, line_id: 9, digest: "b".repeat(64), statutory_certified: false, deduction_assessed: false }));
    vi.stubGlobal("fetch", fetcher);
    const onRegistered = vi.fn();
    render(<AccountingInputVatRegister org="7" start="2026-09-01" row={row} onRegistered={onRegistered} />);
    fireEvent.click(screen.getByRole("button", { name: "Записать в реестр НДС" }));
    fireEvent.change(screen.getByLabelText("Документ входного НДС"), { target: { value: "INV-18" } });
    fireEvent.change(screen.getByLabelText("Статус ЭСЧФ"), { target: { value: "provided" } });
    fireEvent.change(screen.getByLabelText("Идентификатор ЭСЧФ"), { target: { value: "ЭСЧФ-18" } });
    fireEvent.change(screen.getByLabelText("Основание права на вычет"), { target: { value: "Проверка первички и политики" } });
    fireEvent.change(screen.getByLabelText("Подтверждение регистрации НДС"), { target: { value: "Сверено с ЭСЧФ и накладной" } });
    fireEvent.click(screen.getByRole("button", { name: "Проверить пакет" }));
    await screen.findByRole("button", { name: "Сохранить запись реестра" });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить запись реестра" }));
    await waitFor(() => expect(onRegistered).toHaveBeenCalledOnce());
    expect(fetcher).toHaveBeenCalledTimes(3);
    expect(fetcher.mock.calls[2][1].headers["X-Expected-Principal"]).toBe("chief");
  });

  it("keeps statutory treatment visibly unconfirmed for a saved row", () => {
    render(<AccountingInputVatRegister org="7" start="2026-09-01" row={{ ...row, registered: true, deduction_status: "eligible", register_eschf_status: "provided", register_eschf_identifier: "ЭСЧФ-18" }} onRegistered={vi.fn()} />);
    expect(screen.getByText(/Статус не является налоговой сертификацией/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Записать в реестр НДС" })).not.toBeInTheDocument();
  });
});
