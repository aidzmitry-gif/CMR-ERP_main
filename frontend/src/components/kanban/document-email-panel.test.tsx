import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { DocumentEmail, EmailOptions } from "@/lib/document-email-api";
import { DocumentEmailPanel } from "./document-email-panel";

const options: EmailOptions = { sender: "crm@example.test", enabled: true, configuration_error: null,
  signature_preview: "Иван Иванов\nМенеджер", signature_configuration_error: null,
  documents: [{ id: 11, number: "INV-11", kind: "invoice", version: 2, status: "posted", available: true, superseded_by_id: null }] };
const prepared: DocumentEmail = { id: "email-1", sender: "crm@example.test", to: ["control@example.test"], cc: [],
  subject: "Документы по вашей сделке", body: "Направляем документы по вашей сделке.", status: "prepared",
  created_at: "2026-09-09T01:00:00Z", accepted_at: null, next_attempt_at: null, attempt_count: 0, last_reason: null,
  message_id: "<email-1@example.test>", can_confirm: true, can_retry: false, attachments: [{ document_id: 11, version: 2, number: "INV-11",
    filename: "invoice-11-v2.pdf", size: 3000, sha256: "abc" }] };
let rows: DocumentEmail[];
let fetcher: ReturnType<typeof vi.fn>;
let prepareFailures = 0;
let prepareBodies: Record<string, unknown>[];
const incoming = {
  receipt_id: "receipt-1", direction: "incoming", deal_id: 1, owner_id: 7, owner: "Иван Иванов",
  sender: "control@example.test", to: ["order@microchips.by"], cc: [], subject: "Нужен счёт",
  received_at: "2026-09-09T02:00:00Z", message_date: null, message_id: "<incoming@example.test>",
  routing_status: "matched", routing_reason: "technical_reference_match", attachments: [],
};
const incomingSecond = { ...incoming, receipt_id: "receipt-2", subject: "Второе входящее", received_at: "2026-09-09T00:00:00Z" };
const incomingDetail = { ...incoming, body_text: "Нужен счёт <script>steal()</script>", headers: {}, raw_sha256: "raw" };
let incomingPages: Record<string, unknown>;

beforeEach(() => {
  rows = [];
  prepareFailures = 0;
  prepareBodies = [];
  incomingPages = { "0": { items: [incoming], next_offset: null } };
  fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    let value: unknown = rows;
    if (url.endsWith("/options")) value = options;
    if (url.includes("/incoming-emails/receipt-1")) value = incomingDetail;
    if (url.includes("/incoming-emails/receipt-2")) value = { ...incomingSecond, body_text: "Второе входящее", headers: {}, raw_sha256: "raw-2" };
    if (url.includes("/incoming-emails?")) {
      const offset = new URL(url, "http://crm.test").searchParams.get("offset") ?? "0";
      value = incomingPages[offset] ?? { items: [], next_offset: null };
    }
    if (url.endsWith("/prepare")) {
      prepareBodies.push(JSON.parse(String(init?.body)) as Record<string, unknown>);
      rows = [{ ...prepared }];
      if (prepareFailures > 0) { prepareFailures -= 1; throw new Error("Ответ CRM не получен"); }
      value = rows[0];
    }
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
    expect(screen.getAllByRole("link", { name: /INV-11 · версия 2 · PDF · 3 КБ/ })[0]).toHaveAttribute("href", "/api/sales/deals/1/emails/email-1/attachments/0");
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
    rows = [{ ...prepared, status: "uncertain", attempt_count: 1, last_reason: "response_unknown", can_retry: true }];
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
  it("передаёт разрешённый upload и скрывает подтверждение чужого письма", async () => {
    rows = [{ ...prepared, can_confirm: false }];
    await open();
    expect(screen.queryByRole("button", { name: "Подтвердить отправку" })).toBeNull();
    expect(screen.getByText(/доступно для текущей сессии/)).toBeInTheDocument();
    const file = new File(["hello"], "note.txt", { type: "" });
    const officeFile = new File(["docx"], "contract.docx", { type: "" });
    fireEvent.change(screen.getByLabelText(/Файлы/), { target: { files: [file, officeFile] } });
    fireEvent.change(screen.getByLabelText("Кому (To)"), { target: { value: "control@example.test" } });
    fireEvent.click(screen.getByRole("button", { name: "Подготовить и проверить" }));
    await screen.findByRole("button", { name: "Подтвердить отправку" });
    const call = fetcher.mock.calls.find(([url]) => url.endsWith("/prepare"));
    expect(JSON.parse(call![1].body).uploads).toEqual([
      { filename: "note.txt", content_type: "text/plain", content_base64: "aGVsbG8=" },
      { filename: "contract.docx", content_type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document", content_base64: "ZG9jeA==" },
    ]);
  });
  it("отклоняет upload сверх клиентского лимита", async () => {
    await open();
    const file = new File([new Uint8Array(14 * 1024 * 1024 + 1)], "large.txt", { type: "text/plain" });
    fireEvent.change(screen.getByLabelText(/Файлы/), { target: { files: [file] } });
    expect(await screen.findByRole("alert")).toHaveTextContent("14 MiB");
    expect(screen.queryByText("large.txt")).toBeNull();
  });
  it("догружает bounded incoming page и сохраняет старшее письмо в переписке", async () => {
    incomingPages = {
      "0": { items: [incoming], next_offset: 1 },
      "1": { items: [incomingSecond], next_offset: null },
    };
    await open();
    fireEvent.click(screen.getByRole("button", { name: "Загрузить ещё входящие" }));
    expect(await screen.findByRole("button", { name: /Второе входящее/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Нужен счёт/ })).toBeInTheDocument();
  });
  it("показывает входящий текст безопасно и заполняет explicit reply", async () => {
    await open();
    fireEvent.click(screen.getByRole("button", { name: /Нужен счёт/ }));
    expect(await screen.findByText(/Нужен счёт <script>steal\(\)<\/script>/)).toBeInTheDocument();
    await screen.findByText("Ответственный: Иван Иванов");
    fireEvent.click(screen.getByRole("button", { name: "Ответить" }));
    expect(screen.getByLabelText("Кому (To)")).toHaveValue("control@example.test");
    expect(screen.getByLabelText("Тема")).toHaveValue("Re: Нужен счёт");
    fireEvent.change(screen.getByLabelText("Текст письма"), { target: { value: "Ответ менеджера" } });
    fireEvent.click(screen.getByRole("button", { name: "Подготовить и проверить" }));
    await waitFor(() => expect(fetcher.mock.calls.some(([url]) => url.endsWith("/prepare"))).toBe(true));
    const call = fetcher.mock.calls.find(([url]) => url.endsWith("/prepare"));
    expect(JSON.parse(call![1].body)).toMatchObject({ to: ["control@example.test"], reply_to_receipt_id: "receipt-1" });
  });
  it("сохраняет request key до чтения файла и повторяет тот же ввод после потери ответа", async () => {
    prepareFailures = 1;
    await open();
    fireEvent.change(screen.getByLabelText("Кому (To)"), { target: { value: "control@example.test" } });
    fireEvent.change(screen.getByLabelText(/Файлы/), { target: { files: [new File(["hello"], "note.txt", { type: "" })] } });
    fireEvent.click(screen.getByRole("button", { name: "Подготовить и проверить" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Ответ CRM не получен");
    fireEvent.click(screen.getByRole("button", { name: "Email документов" }));
    fireEvent.click(screen.getByRole("button", { name: "Email документов" }));
    await screen.findByLabelText("Кому (To)");
    fireEvent.click(screen.getByRole("button", { name: "Подготовить и проверить" }));
    await screen.findByRole("button", { name: "Подтвердить отправку" });
    expect(prepareBodies).toHaveLength(2);
    expect(prepareBodies[1].request_key).toBe(prepareBodies[0].request_key);
    expect(prepareBodies[1].uploads).toEqual(prepareBodies[0].uploads);
  });
  it("не переносит письмо и черновик между разными сделками", async () => {
    const view = render(<DocumentEmailPanel key="deal-1" dealId="1" />);
    fireEvent.click(screen.getByRole("button", { name: "Email документов" }));
    await screen.findByLabelText("Кому (To)");
    fireEvent.change(screen.getByLabelText("Кому (To)"), { target: { value: "first@example.test" } });
    fireEvent.click(screen.getByRole("button", { name: "Подготовить и проверить" }));
    await screen.findByRole("button", { name: "Подтвердить отправку" });
    view.rerender(<DocumentEmailPanel key="deal-2" dealId="2" />);
    fireEvent.click(screen.getByRole("button", { name: "Email документов" }));
    await screen.findByLabelText("Кому (To)");
    expect(screen.getByLabelText("Кому (To)")).toHaveValue("");
    expect(screen.queryByText("Кому: first@example.test")).toBeNull();
  });
  it("отмена ответа очищает reply identity, а успешная отправка снимает режим ответа", async () => {
    await open();
    fireEvent.click(screen.getByRole("button", { name: /Нужен счёт/ }));
    await screen.findByRole("button", { name: "Ответить" });
    fireEvent.click(screen.getByRole("button", { name: "Ответить" }));
    expect(screen.getByRole("button", { name: "Отменить ответ" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Новое письмо" }));
    expect(screen.queryByText(/Ответ будет связан/)).toBeNull();
    fireEvent.change(screen.getByLabelText("Кому (To)"), { target: { value: "new@example.test" } });
    fireEvent.click(screen.getByRole("button", { name: "Подготовить и проверить" }));
    await screen.findByRole("button", { name: "Подтвердить отправку" });
    const preparedBody = prepareBodies.at(-1);
    expect(preparedBody?.reply_to_receipt_id).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Подтвердить отправку" }));
    await screen.findByText("В очереди");
    expect(screen.queryByText(/Ответ будет связан/)).toBeNull();
  });
});
