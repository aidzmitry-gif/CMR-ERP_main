import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "@/lib/api";
import * as salesMail from "@/lib/sales-mail-api";
import { SalesMailInbox } from "./sales-mail-inbox";

vi.mock("@/lib/sales-mail-api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/sales-mail-api")>("@/lib/sales-mail-api");
  return { ...actual, fetchInboxPage: vi.fn(), fetchInboxDetail: vi.fn(), fetchSalesDeals: vi.fn(), assignInboxEmail: vi.fn() };
});
vi.mock("@/lib/api", () => ({ createDeal: vi.fn() }));

const item = {
  receipt_id: "receipt-1", direction: "incoming" as const, deal_id: null, owner_id: null, owner: null,
  sender: "client@example.test", to: ["order@microchips.by"], cc: [], subject: "Нужен счёт",
  received_at: "2026-09-09T01:00:00Z", message_date: null, message_id: "<incoming@example.test>",
  routing_status: "unmatched", routing_reason: "unknown_chain", attachments: [],
};
const detail = { ...item, body_text: "Нужен счёт и договор", headers: {}, raw_sha256: "abc" };
const item2 = { ...item, receipt_id: "receipt-2", subject: "Вторая заявка", received_at: "2026-09-09T00:00:00Z" };
const detail2 = { ...item2, body_text: "Вторая заявка", headers: {}, raw_sha256: "def" };
const deal = { id: 42, number: "CRM-42", title: "Запрос документов", counterparty: "ООО Клиент", owner: null };

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(salesMail.fetchInboxPage).mockResolvedValue({ items: [item], next_offset: null });
  vi.mocked(salesMail.fetchInboxDetail).mockResolvedValue(detail);
  vi.mocked(salesMail.fetchSalesDeals).mockResolvedValue([deal]);
});
afterEach(() => cleanup());

describe("SalesMailInbox", () => {
  it("отличает head403 от пустой очереди", async () => {
    vi.mocked(salesMail.fetchInboxPage).mockRejectedValue(new salesMail.SalesMailHttpError(403, "forbidden"));
    render(<SalesMailInbox />);
    expect(await screen.findByRole("alert")).toHaveTextContent("нет доступа");
    expect(screen.queryByText("В очереди нет неразобранных писем.")).toBeNull();
  });
  it("назначает только выбранную scoped сделку из локального поиска", async () => {
    vi.mocked(salesMail.assignInboxEmail).mockResolvedValue({ ...item, deal_id: 42, routing_status: "assigned" });
    render(<SalesMailInbox />);
    fireEvent.click(await screen.findByRole("button", { name: /Нужен счёт/ }));
    await screen.findByText("Нужен счёт и договор");
    fireEvent.change(screen.getByLabelText("Поиск сделки"), { target: { value: "ООО Клиент" } });
    fireEvent.change(screen.getByRole("combobox", { name: "Существующая сделка" }), { target: { value: "42" } });
    fireEvent.click(screen.getByRole("button", { name: "Назначить" }));
    await waitFor(() => expect(salesMail.assignInboxEmail).toHaveBeenCalledWith("receipt-1", 42));
  });

  it("сбрасывает скрытую поиском выбранную сделку до назначения", async () => {
    render(<SalesMailInbox />);
    fireEvent.click(await screen.findByRole("button", { name: /Нужен счёт/ }));
    await screen.findByText("Нужен счёт и договор");
    fireEvent.change(screen.getByRole("combobox", { name: "Существующая сделка" }), { target: { value: "42" } });
    expect(screen.getByRole("button", { name: "Назначить" })).toBeEnabled();
    fireEvent.change(screen.getByLabelText("Поиск сделки"), { target: { value: "Другая компания" } });
    expect(screen.getByRole("combobox", { name: "Существующая сделка" })).toHaveValue("");
    expect(screen.getByRole("button", { name: "Назначить" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Назначить" }));
    expect(salesMail.assignInboxEmail).not.toHaveBeenCalled();
  });

  it("сохраняет ID новой сделки и повторяет assignment без повторного create", async () => {
    vi.mocked(api.createDeal).mockResolvedValue({ id: "42" } as never);
    vi.mocked(salesMail.fetchInboxPage).mockResolvedValue({ items: [item, item2], next_offset: null });
    vi.mocked(salesMail.fetchInboxDetail).mockImplementation((receiptId) => Promise.resolve(receiptId === "receipt-2" ? detail2 : detail));
    vi.mocked(salesMail.assignInboxEmail)
      .mockRejectedValueOnce(new Error("временная ошибка assignment"))
      .mockResolvedValue({ ...item, deal_id: 42, routing_status: "assigned" });
    render(<SalesMailInbox />);
    fireEvent.click(await screen.findByRole("button", { name: /Нужен счёт/ }));
    expect(await screen.findByText("Нужен счёт и договор")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Создать новую сделку и назначить" }));
    fireEvent.change(screen.getByLabelText("Номер"), { target: { value: "CRM-42" } });
    fireEvent.change(screen.getByLabelText("Компания"), { target: { value: "ООО Клиент" } });
    fireEvent.change(screen.getByLabelText("Описание"), { target: { value: "Запрос документов" } });
    fireEvent.click(screen.getByRole("button", { name: "Создать" }));
    expect(await screen.findByText("42")).toBeInTheDocument();
    await waitFor(() => expect(salesMail.assignInboxEmail).toHaveBeenCalledTimes(1));
    expect(screen.getByText("временная ошибка assignment")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Создать новую сделку и назначить" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Создать новую сделку и назначить" }));
    expect(screen.queryByRole("button", { name: "Создать", exact: true })).toBeNull();
    expect(api.createDeal).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: /Вторая заявка/ }));
    await screen.findByText("Вторая заявка");
    fireEvent.click(screen.getByRole("button", { name: /Нужен счёт/ }));
    await screen.findByText("Нужен счёт и договор");
    fireEvent.click(screen.getByRole("button", { name: "Обновить" }));
    expect(await screen.findByText("42")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Повторить назначение" }));
    await waitFor(() => expect(salesMail.assignInboxEmail).toHaveBeenCalledTimes(2));
    expect(api.createDeal).toHaveBeenCalledTimes(1);
    expect(salesMail.assignInboxEmail).toHaveBeenLastCalledWith("receipt-1", 42);
  });
  it("не позволяет запоздалой детали письма A заменить выбранное письмо B", async () => {
    vi.mocked(salesMail.fetchInboxPage).mockResolvedValue({ items: [item, item2], next_offset: null });
    let resolveA!: (value: typeof detail) => void;
    let resolveB!: (value: typeof detail2) => void;
    vi.mocked(salesMail.fetchInboxDetail).mockImplementation((receiptId) => new Promise((resolve) => {
      if (receiptId === "receipt-1") resolveA = resolve as (value: typeof detail) => void;
      else resolveB = resolve as (value: typeof detail2) => void;
    }));
    render(<SalesMailInbox />);
    fireEvent.click(await screen.findByRole("button", { name: /Нужен счёт/ }));
    fireEvent.click(screen.getByRole("button", { name: /Вторая заявка/ }));
    resolveB(detail2);
    expect(await screen.findByText("Вторая заявка")).toBeInTheDocument();
    resolveA(detail);
    await waitFor(() => expect(screen.queryByText("Нужен счёт и договор")).toBeNull());
    expect(screen.getAllByText("Вторая заявка").length).toBeGreaterThan(0);
  });
});
