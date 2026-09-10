import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", () => ({
  fetchDocuments: vi.fn(),
  createDocument: vi.fn(),
  decideDocument: vi.fn(),
}));

import { DealDocuments } from "@/components/deal-documents";
import * as api from "@/lib/api";

const mock = (fn: unknown) => fn as ReturnType<typeof vi.fn>;
beforeEach(() => vi.clearAllMocks());

describe("DealDocuments", () => {
  it("явный выбор сохраняет ключ после ошибки и сбрасывается при смене сделки/типа", async () => {
    mock(api.fetchDocuments).mockResolvedValue([]);
    mock(api.createDocument).mockResolvedValue(null);
    const { rerender } = render(<DealDocuments dealId="1" />);
    const checkbox = screen.getByRole("checkbox", { name: "Под заказ — без резерва" });
    expect(checkbox).not.toBeChecked();
    fireEvent.click(checkbox);
    fireEvent.click(screen.getByText("Сформировать"));
    await screen.findByRole("alert");
    await waitFor(() => expect(screen.getByText("Сформировать")).not.toBeDisabled());
    fireEvent.click(screen.getByText("Сформировать"));
    await waitFor(() => expect(api.createDocument).toHaveBeenCalledTimes(2));
    const first = mock(api.createDocument).mock.calls[0];
    expect(first).toEqual(["1", "invoice", { reserve_mode: "on_order", request_key: expect.any(String) }]);
    expect(mock(api.createDocument).mock.calls[1]).toEqual(first);
    await waitFor(() => expect(screen.getByRole("combobox")).not.toBeDisabled());
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "contract" } });
    expect(screen.queryByRole("checkbox")).toBeNull();
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "invoice" } });
    expect(screen.getByRole("checkbox")).not.toBeChecked();
    fireEvent.click(screen.getByRole("checkbox"));
    rerender(<DealDocuments dealId="2" />);
    expect(screen.getByRole("checkbox")).not.toBeChecked();
  });

  it("ожидание запроса не показывает созданный резерв", async () => {
    mock(api.fetchDocuments).mockResolvedValue([]);
    mock(api.createDocument).mockReturnValue(new Promise(() => {}));
    render(<DealDocuments dealId="1" />);
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByText("Сформировать"));
    expect(screen.getByRole("checkbox")).toBeDisabled();
    expect(screen.queryByText(/В резерве/)).toBeNull();
    expect(screen.queryByText("Под заказ — товар не зарезервирован")).toBeNull();
  });

  it("успешный счёт отображает сохранённый режим после обновления списка", async () => {
    const doc = { id: 8, kind: "invoice", number: "СЧ-8", status: "posted", amount: 100, reserve_status: "unreserved", reserve_mode: "on_order" };
    mock(api.fetchDocuments).mockResolvedValueOnce([]).mockResolvedValue([doc]);
    mock(api.createDocument).mockResolvedValue(doc);
    render(<DealDocuments dealId="1" />);
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByText("Сформировать"));
    await screen.findByText("Счёт · СЧ-8");
    expect(screen.getAllByText("Под заказ — товар не зарезервирован")).toHaveLength(2);
    expect(screen.queryByText(/В резерве/)).toBeNull();
    expect(api.createDocument).toHaveBeenCalledWith("1", "invoice", { reserve_mode: "on_order", request_key: expect.any(String) });
  });

  it.each([undefined, "stock", "on_order"])("показывает сохранённый режим %s", async (reserve_mode) => {
    mock(api.fetchDocuments).mockResolvedValue([{ id: 8, kind: "invoice", number: "СЧ-8", status: "draft", amount: 100, reserve_status: "unreserved", reserve_mode }]);
    render(<DealDocuments dealId="1" />);
    await screen.findByText("Счёт · СЧ-8");
    expect(screen.queryAllByText("Под заказ — товар не зарезервирован").length).toBe(reserve_mode === "on_order" ? 2 : 0);
    expect(screen.queryByText(/В резерве/)).toBeNull();
  });

  it("пустой список → формирование документа (счёт по умолчанию)", async () => {
    mock(api.fetchDocuments).mockResolvedValue([]);
    mock(api.createDocument).mockResolvedValue(true);
    render(<DealDocuments dealId="1" />);
    expect(await screen.findByText("Документов пока нет")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Сформировать"));
    await waitFor(() => expect(api.createDocument).toHaveBeenCalledWith("1", "invoice"));
  });

  it("договор на согласовании → проведение в 1С", async () => {
    mock(api.fetchDocuments).mockResolvedValue([
      { id: 3, kind: "contract", number: "ДГ-1", status: "pending_approval", onec_ref: null, amount: 1000, reserve_status: "none", valid_until: null },
    ]);
    mock(api.decideDocument).mockResolvedValue(true);
    render(<DealDocuments dealId="1" />);
    expect(await screen.findByText(/ДГ-1/)).toBeInTheDocument();
    fireEvent.click(screen.getByTitle("Согласовать и провести в 1С"));
    await waitFor(() => expect(api.decideDocument).toHaveBeenCalledWith(3, true, "Юрист"));
  });

  it("смена типа документа и отклонение", async () => {
    mock(api.fetchDocuments).mockResolvedValue([
      { id: 4, kind: "contract", number: "ДГ-2", status: "pending_approval", onec_ref: null, amount: 1, reserve_status: "none", valid_until: null },
    ]);
    mock(api.createDocument).mockResolvedValue(true);
    mock(api.decideDocument).mockResolvedValue(true);
    render(<DealDocuments dealId="1" />);
    await screen.findByText(/ДГ-2/);
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "order" } });
    fireEvent.click(screen.getByText("Сформировать"));
    await waitFor(() => expect(api.createDocument).toHaveBeenCalledWith("1", "order"));
    fireEvent.click(screen.getByTitle("Отклонить"));
    await waitFor(() => expect(api.decideDocument).toHaveBeenCalledWith(4, false, "Юрист"));
  });

  it("счёт в резерве → бейдж срока действия", async () => {
    mock(api.fetchDocuments).mockResolvedValue([
      {
        id: 7,
        kind: "invoice",
        number: "СЧ-1",
        status: "posted",
        onec_ref: "1С-СЧ-1",
        amount: 5000,
        reserve_status: "reserved",
        valid_until: "2099-01-05",
      },
    ]);
    render(<DealDocuments dealId="1" />);
    expect(await screen.findByText(/В резерве/)).toBeInTheDocument();
    expect(screen.getByText(/05\.01\.2099/)).toBeInTheDocument();
  });
});
