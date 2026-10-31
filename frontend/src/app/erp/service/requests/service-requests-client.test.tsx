import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ServiceRequestsClient } from "./service-requests-client";

vi.mock("@dnd-kit/core", () => ({
  DndContext: ({ children, onDragEnd }: { children: React.ReactNode; onDragEnd: (e: unknown) => void }) => <div>{children}<button onClick={() => onDragEnd({ active: { id: 7 }, over: { id: "done" } })}>Synthetic drag to done</button></div>,
  DragOverlay: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  PointerSensor: class {}, useSensor: () => ({}), useSensors: () => [],
  useDraggable: () => ({ attributes: {}, listeners: {}, setNodeRef: () => {}, isDragging: false }),
  useDroppable: () => ({ setNodeRef: () => {}, isOver: false }),
}));

const row = { id: 7, title: "Synthetic repair", description: "Synthetic description", status: "new", priority: "normal", counterparty_id: 42, deal_id: 77, created_at: "2026-10-30T10:20:00" };
const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
const request = vi.fn();
beforeEach(() => { vi.resetAllMocks(); vi.stubGlobal("fetch", request); });
afterEach(() => vi.unstubAllGlobals());
const card = () => screen.getByRole("button", { name: "Открыть заявку SR-7: Synthetic repair" });
async function openCreate() { fireEvent.click(await screen.findByRole("button", { name: "Создать заявку" })); fireEvent.change(screen.getByLabelText("Заголовок"), { target: { value: "Synthetic new request" } }); }

describe("native service kanban", () => {
  it("renders real rows and exact unknown statuses while keeping unsupported SLA unavailable", async () => {
    request.mockResolvedValue(response([row, { ...row, id: 8, status: "external_review", title: "Synthetic external" }]));
    render(<ServiceRequestsClient />); await screen.findByRole("button", { name: /Открыть заявку SR-7/ });
    expect(screen.getByText("Другой статус: external_review", { selector: "div" })).toBeInTheDocument();
    expect(screen.getByText("Нет данных")).toBeInTheDocument();
    expect(screen.getByText("Показано: 2 из 2. Показатели сверху относятся ко всему загруженному списку.")).toBeInTheDocument();
    expect(screen.queryByText("87%")).not.toBeInTheDocument();
    expect(screen.queryByText("Рекламация #SR-007")).not.toBeInTheDocument();
  });
  it("filters by actual status and search without sending unused filters or losing a draft", async () => {
    request.mockResolvedValue(response([row, { ...row, id: 8, status: "done", title: "Synthetic closed" }]));
    render(<ServiceRequestsClient />); await screen.findByText("Synthetic repair"); await openCreate();
    fireEvent.change(screen.getByLabelText("Статус заявок"), { target: { value: "done" } });
    expect(screen.queryByRole("button", { name: /Открыть заявку SR-7/ })).not.toBeInTheDocument();
    expect(screen.getByText("Synthetic closed")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Поиск заявок"), { target: { value: "missing" } });
    expect(screen.getByText("По выбранным условиям заявки не найдены.")).toBeInTheDocument();
    expect(screen.getByLabelText("Заголовок")).toHaveValue("Synthetic new request");
    expect(request).toHaveBeenCalledTimes(1);
  });
  it("distinguishes failed reads from a confirmed empty board and supports recovery", async () => {
    request.mockResolvedValueOnce(response({}, 502)).mockResolvedValueOnce(response([]));
    render(<ServiceRequestsClient />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Не удалось загрузить заявки");
    expect(screen.queryByText("Заявок пока нет. Создайте первую заявку.")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Создать заявку" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Повторить загрузку" }));
    expect(await screen.findByText("Заявок пока нет. Создайте первую заявку.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Создать заявку" })).toBeEnabled();
  });
  it("creates one native request only after ACK and reloads the actual saved row", async () => {
    let resolve!: (r: Response) => void;
    const saved = { ...row, id: 9, title: "Synthetic new request", description: "" };
    request.mockResolvedValueOnce(response([])).mockImplementationOnce(() => new Promise<Response>((r) => { resolve = r; })).mockResolvedValueOnce(response([saved]));
    render(<ServiceRequestsClient />); await screen.findByText("Заявок пока нет. Создайте первую заявку."); await openCreate();
    fireEvent.click(screen.getByRole("button", { name: "Сохранить заявку" }));
    fireEvent.click(screen.getByRole("button", { name: "Сохранение…" }));
    expect(request.mock.calls.filter(([, o]) => o?.method === "POST")).toHaveLength(1);
    expect(screen.queryByRole("button", { name: /Открыть заявку SR-9/ })).not.toBeInTheDocument();
    await act(async () => resolve(response(saved, 201)));
    expect(await screen.findByRole("button", { name: /Открыть заявку SR-9/ })).toBeInTheDocument();
    expect(screen.queryByRole("form", { name: "Новая сервисная заявка" })).not.toBeInTheDocument();
  });
  it("keeps a rejected creation draft and does not expose server error details", async () => {
    request.mockResolvedValueOnce(response([])).mockResolvedValueOnce(response({ detail: "SYNTHETIC-PRIVATE-ERROR" }, 422));
    render(<ServiceRequestsClient />); await screen.findByText("Заявок пока нет. Создайте первую заявку."); await openCreate();
    fireEvent.click(screen.getByRole("button", { name: "Сохранить заявку" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Действие отклонено");
    expect(screen.getByLabelText("Заголовок")).toHaveValue("Synthetic new request");
    expect(screen.queryByText("SYNTHETIC-PRIVATE-ERROR")).not.toBeInTheDocument();
  });
  it("blocks resubmission after lost ACK until a fresh read and explicit result review", async () => {
    request.mockResolvedValueOnce(response([])).mockRejectedValueOnce(new Error("network"))
      .mockResolvedValueOnce(response([{ ...row, id: 9, title: "Synthetic new request", description: "" }]));
    render(<ServiceRequestsClient />); await screen.findByText("Заявок пока нет. Создайте первую заявку."); await openCreate();
    fireEvent.click(screen.getByRole("button", { name: "Сохранить заявку" }));
    await screen.findByText(/Результат действия не подтверждён/);
    expect(screen.getByRole("button", { name: "Сохранить заявку" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Я проверил результат" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Проверить список" }));
    await screen.findByRole("button", { name: /Открыть заявку SR-9/ });
    expect(screen.getByRole("button", { name: "Сохранить заявку" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Я проверил результат" }));
    expect(screen.getByRole("button", { name: "Сохранить заявку" })).toBeEnabled();
    expect(request.mock.calls.filter(([, o]) => o?.method === "POST")).toHaveLength(1);
  });
  it("opens an accessible detail and saves native status/priority with exact related links", async () => {
    const updated = { ...row, status: "in_progress", priority: "urgent" };
    request.mockResolvedValueOnce(response([row])).mockResolvedValueOnce(response(updated)).mockResolvedValueOnce(response([updated]));
    render(<ServiceRequestsClient />); await screen.findByText("Synthetic repair"); fireEvent.click(card());
    const dialog = screen.getByRole("dialog", { name: "Synthetic repair" });
    expect(dialog).toHaveFocus();
    expect(within(dialog).getByRole("link", { name: "Открыть клиента" })).toHaveAttribute("href", "/erp/spravochniki/counterparty/42");
    expect(within(dialog).getByRole("link", { name: "Связанная сделка" })).toHaveAttribute("href", "/crm/deals/77");
    fireEvent.change(screen.getByLabelText("Статус заявки"), { target: { value: "in_progress" } });
    fireEvent.change(screen.getByLabelText("Приоритет заявки"), { target: { value: "urgent" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить изменения" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    await screen.findByText("Synthetic repair");
    const [, options] = request.mock.calls.find(([, o]) => o?.method === "PATCH")!;
    expect(JSON.parse(options.body)).toEqual({ status: "in_progress", priority: "urgent" });
    expect(screen.getByText("Срочный")).toHaveClass("text-red-600");
    card().focus(); fireEvent.click(card()); fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument(); expect(card()).toHaveFocus();
  });
  it("does not optimistically move a request when the native PATCH is rejected", async () => {
    request.mockResolvedValueOnce(response([row])).mockResolvedValueOnce(response({}, 422));
    render(<ServiceRequestsClient />); await screen.findByText("Synthetic repair");
    fireEvent.click(screen.getByRole("button", { name: "Synthetic drag to done" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Действие отклонено");
    const [, options] = request.mock.calls.find(([, o]) => o?.method === "PATCH")!;
    expect(JSON.parse(options.body)).toEqual({ status: "done" });
    fireEvent.change(screen.getByLabelText("Статус заявок"), { target: { value: "new" } });
    expect(card()).toBeInTheDocument();
  });
  it("hides protected cards and drafts after 403 and ignores a late successful older read", async () => {
    let resolve!: (r: Response) => void;
    request.mockResolvedValueOnce(response([row])).mockImplementationOnce(() => new Promise<Response>((r) => { resolve = r; })).mockResolvedValueOnce(response({}, 403));
    render(<ServiceRequestsClient />); await screen.findByText("Synthetic repair"); await openCreate();
    fireEvent.click(screen.getByRole("button", { name: "Обновить список" }));
    await waitFor(() => expect(request).toHaveBeenCalledTimes(2));
    fireEvent.click(screen.getByRole("button", { name: "Обновить список" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Доступ к заявкам не подтверждён");
    await act(async () => resolve(response([row])));
    expect(screen.queryByText("Synthetic repair")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Заголовок")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Создать заявку" })).toBeDisabled();
  });
});
