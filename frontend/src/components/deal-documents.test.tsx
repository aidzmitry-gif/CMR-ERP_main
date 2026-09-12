import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", () => ({
  fetchDocuments: vi.fn(),
  createDocumentResult: vi.fn(),
  decideDocument: vi.fn(),
}));

import { DealDocuments } from "@/components/deal-documents";
import * as api from "@/lib/api";

const mock = (fn: unknown) => fn as ReturnType<typeof vi.fn>;
beforeEach(() => vi.clearAllMocks());
afterEach(() => vi.unstubAllGlobals());

const issuedInvoice: api.DealDoc = {
  id: 50, kind: "invoice", number: "СЧ-50", status: "posted", amount: 360,
  onec_ref: null, valid_until: null, reserve_status: "unreserved", reserve_mode: "on_order",
  original_state: "issued", version: 1,
};

function moneySummary() {
  return within(screen.getByRole("region", { name: "Оплата и деньги" }));
}

describe("DealDocuments — сумма выпущенного счёта", () => {
  it.each(["posted", "paid"])("сумма с НДС 360 берётся из оригинала %s, оплата и остаток неизвестны", async (status) => {
    mock(api.fetchDocuments).mockResolvedValue([{ ...issuedInvoice, status }]);
    render(<DealDocuments dealId="1" />);
    expect(await moneySummary().findByText("360 BYN")).toBeInTheDocument();
    expect(moneySummary().getByText("Сумма счёта (с НДС)")).toBeInTheDocument();
    expect(moneySummary().getByRole("link")).toHaveAttribute("href", "/api/sales/documents/50/render");
    expect(moneySummary().getAllByText("Нет данных")).toHaveLength(2);
    expect(moneySummary().queryByText("0 BYN")).toBeNull();
    expect(screen.getAllByText("Под заказ — товар не зарезервирован")).toHaveLength(2);
  });

  it("сохраняет копейки и исходную валюту счёта", async () => {
    mock(api.fetchDocuments).mockResolvedValue([{ ...issuedInvoice, amount: 360.12 }]);
    render(<DealDocuments dealId="1" />);
    expect(await moneySummary().findByText("360,12 BYN")).toBeInTheDocument();
  });

  it.each([
    [],
    [{ ...issuedInvoice, status: "draft", original_state: "draft" }],
    [{ ...issuedInvoice, status: "cancelled" }],
    [{ ...issuedInvoice, superseded_by_id: 51 }],
    [{ ...issuedInvoice, original_state: "legacy_unavailable" }],
    [{ ...issuedInvoice, original_state: undefined }],
    [{ ...issuedInvoice, amount: NaN }],
    [{ ...issuedInvoice, amount: -10 }],
    [issuedInvoice, { ...issuedInvoice, id: 51 }],
    [issuedInvoice, { ...issuedInvoice, id: 51, original_state: "legacy_unavailable" }],
  ].map((docs, index) => ({ docs, index })))("нет единственного подтверждённого актуального оригинала: $index", async ({ docs }) => {
    mock(api.fetchDocuments).mockResolvedValue(docs);
    await act(async () => { render(<DealDocuments dealId="1" />); });
    expect(moneySummary().getAllByText("Нет данных")).toHaveLength(3);
    expect(moneySummary().queryByRole("link")).toBeNull();
    expect(moneySummary().queryByText(/BYN/)).toBeNull();
  });

  it("черновик замены сохраняет старый итог; выпуск обновляет сумму без переноса оплаты", async () => {
    const old = { ...issuedInvoice, status: "paid" };
    const next = { ...issuedInvoice, id: 51, number: "СЧ-51", version: 2, amount: 480, supersedes_id: 50, status: "draft", original_state: "draft" };
    mock(api.fetchDocuments).mockResolvedValueOnce([old, next])
      .mockResolvedValue([{ ...old, superseded_by_id: 51 }, { ...next, status: "posted", original_state: "issued" }]);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true }));
    render(<DealDocuments dealId="1" />);
    await moneySummary().findByText("360 BYN");
    fireEvent.click(screen.getByText("Выпустить версию"));
    await moneySummary().findByText("480 BYN");
    expect(moneySummary().queryByText("360 BYN")).toBeNull();
    expect(moneySummary().getByRole("link")).toHaveAttribute("href", "/api/sales/documents/51/render");
    expect(moneySummary().getAllByText("Нет данных")).toHaveLength(2);
    expect(screen.getByText(/Заменён документом #51; оплата: оплачен/)).toBeInTheDocument();
  });

  it("смена сделки скрывает прежнюю сумму и игнорирует запоздавший ответ", async () => {
    let finishOld!: (docs: api.DealDoc[]) => void;
    mock(api.fetchDocuments).mockReturnValueOnce(new Promise<api.DealDoc[]>((resolve) => { finishOld = resolve; }))
      .mockResolvedValueOnce([{ ...issuedInvoice, id: 70, amount: 720 }]);
    const { rerender } = render(<DealDocuments dealId="1" />);
    rerender(<DealDocuments dealId="2" />);
    await moneySummary().findByText("720 BYN");
    await act(async () => { finishOld([issuedInvoice]); });
    expect(moneySummary().getByText("720 BYN")).toBeInTheDocument();
    expect(moneySummary().queryByText("360 BYN")).toBeNull();
    mock(api.fetchDocuments).mockReturnValueOnce(new Promise(() => {}));
    rerender(<DealDocuments dealId="3" />);
    expect(moneySummary().queryByText("720 BYN")).toBeNull();
    expect(moneySummary().getAllByText("Нет данных")).toHaveLength(3);
  });
});

describe("DealDocuments", () => {
  it("явный выбор сохраняет ключ после ошибки и сбрасывается при смене сделки/типа", async () => {
    mock(api.fetchDocuments).mockResolvedValue([]);
    mock(api.createDocumentResult).mockResolvedValue({ doc: null, error: "Подтвердите цену каждой позиции" });
    const { rerender } = render(<DealDocuments dealId="1" />);
    const checkbox = screen.getByRole("checkbox", { name: "Под заказ — без резерва" });
    expect(checkbox).not.toBeChecked();
    fireEvent.click(checkbox);
    fireEvent.click(screen.getByText("Сформировать"));
    expect(await screen.findByRole("alert")).toHaveTextContent("Подтвердите цену каждой позиции");
    await waitFor(() => expect(screen.getByText("Сформировать")).not.toBeDisabled());
    fireEvent.click(screen.getByText("Сформировать"));
    await waitFor(() => expect(api.createDocumentResult).toHaveBeenCalledTimes(2));
    const first = mock(api.createDocumentResult).mock.calls[0];
    expect(first).toEqual(["1", "invoice", { reserve_mode: "on_order", request_key: expect.any(String) }]);
    expect(mock(api.createDocumentResult).mock.calls[1]).toEqual(first);
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
    mock(api.createDocumentResult).mockReturnValue(new Promise(() => {}));
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
    mock(api.createDocumentResult).mockResolvedValue({ doc });
    render(<DealDocuments dealId="1" />);
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByText("Сформировать"));
    await screen.findByText("Счёт · СЧ-8");
    expect(screen.getAllByText("Под заказ — товар не зарезервирован")).toHaveLength(2);
    expect(screen.queryByText(/В резерве/)).toBeNull();
    expect(api.createDocumentResult).toHaveBeenCalledWith("1", "invoice", { reserve_mode: "on_order", request_key: expect.any(String) });
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
    mock(api.createDocumentResult).mockResolvedValue({ doc: issuedInvoice });
    render(<DealDocuments dealId="1" />);
    expect(await screen.findByText("Документов пока нет")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Сформировать"));
    await waitFor(() => expect(api.createDocumentResult).toHaveBeenCalledWith("1", "invoice"));
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
    mock(api.createDocumentResult).mockResolvedValue({ doc: issuedInvoice });
    mock(api.decideDocument).mockResolvedValue(true);
    render(<DealDocuments dealId="1" />);
    await screen.findByText(/ДГ-2/);
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "order" } });
    fireEvent.click(screen.getByText("Сформировать"));
    await waitFor(() => expect(api.createDocumentResult).toHaveBeenCalledWith("1", "order"));
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
