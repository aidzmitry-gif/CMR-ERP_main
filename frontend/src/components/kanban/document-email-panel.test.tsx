import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { DocumentEmail, EmailOptions } from "@/lib/document-email-api";
import { DocumentEmailPanel } from "./document-email-panel";

const options: EmailOptions = { sender: "crm@example.test", enabled: true, configuration_error: null,
  documents: [{ id: 11, number: "INV-11", kind: "invoice", version: 2, status: "posted", available: true, superseded_by_id: null }] };
const prepared: DocumentEmail = { id: "email-1", sender: "crm@example.test", to: ["control@example.test"], cc: [],
  subject: "Документы по вашей сделке", body: "Направляем документы по вашей сделке.", status: "prepared",
  created_at: "2026-09-09T01:00:00Z", accepted_at: null, next_attempt_at: null, attempt_count: 0, last_reason: null,
  message_id: "<email-1@example.test>", attachments: [{ document_id: 11, version: 2, number: "INV-11",
    filename: "invoice-11-v2.pdf", size: 3000, sha256: "abc" }] };
let rows: DocumentEmail[];
let fetcher: ReturnType<typeof vi.fn>;

beforeEach(() => {
  rows = [];
  fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    let value: unknown = rows;
    if (url.endsWith("/options")) value = options;
    if (url.endsWith("/prepare")) { rows = [{ ...prepared }]; value = rows[0]; }
    if (url.endsWith("/send") || url.endsWith("/retry")) { rows = [{ ...prepared, status: "queued" }]; value = rows[0]; }
    return { ok: true, json: async () => value, ...(init ? {} : {}) };
  });
  vi.stubGlobal("fetch", fetcher);
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

async function open() {
  render(<DocumentEmailPanel dealId="1" />);
  fireEvent.click(screen.getByRole("button", { name: "Email документов" }));
  await screen.findByLabelText("Кому (To)");
}

describe("Email документов", () => {
  it("показывает адресата, версию и PDF до отдельного подтверждения отправки", async () => {
    await open();
    fireEvent.change(screen.getByLabelText("Кому (To)"), { target: { value: "control@example.test" } });
    fireEvent.click(screen.getByRole("button", { name: "Подготовить и проверить" }));
    await screen.findByRole("button", { name: "Подтвердить отправку" });
    expect(screen.getByText("Кому: control@example.test")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /INV-11 · версия 2 · PDF · 3 КБ/ })).toHaveAttribute("href", "/api/sales/deals/1/emails/email-1/attachments/0");
    expect(fetcher.mock.calls.filter(([url]) => url.endsWith("/send"))).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "Подтвердить отправку" }));
    fireEvent.click(screen.getByRole("button", { name: "Подтвердить отправку" }));
    await screen.findByText("В очереди");
    expect(fetcher.mock.calls.filter(([url]) => url.endsWith("/send"))).toHaveLength(1);
    expect(screen.queryByText("Принято почтовым сервером")).toBeNull();
    expect(screen.queryByText(/Пакет отправлен/)).toBeNull();
  });
  it("принятие SMTP не называет доставкой или прочтением", async () => {
    rows = [{ ...prepared, status: "accepted", attempt_count: 1, accepted_at: "2026-09-09T01:01:00Z" }];
    await open();
    expect(screen.getByText("Принято почтовым сервером")).toBeInTheDocument();
    expect(screen.getByText(/Доставка и прочтение не подтверждены/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Повторить это письмо" })).toBeNull();
  });
  it("неопределённый результат требует явного подтверждения риска дубля", async () => {
    rows = [{ ...prepared, status: "uncertain", attempt_count: 1, last_reason: "response_unknown" }];
    await open();
    expect(screen.getByRole("button", { name: "Повторить это письмо" })).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", { name: /Подтверждаю риск дубля/ }));
    fireEvent.click(screen.getByRole("button", { name: "Повторить это письмо" }));
    await waitFor(() => expect(fetcher.mock.calls.some(([url]) => url.endsWith("/retry"))).toBe(true));
    const call = fetcher.mock.calls.find(([url]) => url.endsWith("/retry"));
    expect(JSON.parse(call![1].body)).toEqual({ expected_attempt: 1, acknowledge_possible_duplicate: true });
  });
  it("ошибка подготовки не выглядит как успешная отправка", async () => {
    await open();
    fetcher.mockImplementation(async (url: string) => url.endsWith("/prepare")
      ? { ok: false, json: async () => ({ detail: "Нет сохранённого оригинала" }) }
      : { ok: true, json: async () => rows });
    fireEvent.change(screen.getByLabelText("Кому (To)"), { target: { value: "control@example.test" } });
    fireEvent.click(screen.getByRole("button", { name: "Подготовить и проверить" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Нет сохранённого оригинала");
    expect(screen.queryByRole("button", { name: "Подтвердить отправку" })).toBeNull();
  });
});
