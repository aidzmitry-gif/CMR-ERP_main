import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const nav = vi.hoisted(() => ({ refresh: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => nav }));
import type { CounterpartyCard } from "@/lib/reference-data";
import { SpravBranches } from "./sprav-branches";

const card: CounterpartyCard = {
  id: 7, name: "Рабочее", legal_name: "Юридическое", unp: "600187521", revision: 4,
  is_active: true, merged_into_id: null, aliases: [], provenance: {}, merged_duplicates: [],
  contacts: [], audit: [], touches: [], touch_summary: null,
  branches: [{ id: 12, legal_entity_id: 7, name: "Брест", address: "Адрес", tax_mode: "shared", portal_branch_code: "0001", is_active: true, revision: 2 }],
};
afterEach(() => { vi.unstubAllGlobals(); nav.refresh.mockReset(); });

describe("SpravBranches", () => {
  it("показывает филиал отдельно от головного и сохраняет ведущие нули кода", () => {
    render(<SpravBranches card={card} />);
    expect(screen.getByRole("link", { name: "Юридическое" })).toHaveAttribute("href", "/erp/spravochniki/counterparty/7");
    expect(screen.getByRole("heading", { name: "Филиал: Брест" })).toHaveAttribute("class");
    expect(screen.getByText("Код филиала для ЭСЧФ: 0001")).toBeInTheDocument();
  });

  it("не даёт создать филиал без подтверждённого имени головного", () => {
    render(<SpravBranches card={{ ...card, legal_name: null }} />);
    expect(screen.getByRole("button", { name: "Добавить филиал" })).toBeDisabled();
  });

  it("отправляет стабильные ID и исходные ревизии, сохраняет draft при конфликте", async () => {
    const fetchMock = vi.fn(async () => ({ ok: false, status: 409, json: async () => ({ detail: { code: "stale_revision", message: "Филиал изменён. Обновите карточку" } }) }));
    vi.stubGlobal("fetch", fetchMock);
    const view = render(<SpravBranches card={card} />);
    fireEvent.click(screen.getByRole("button", { name: "Редактировать филиал Брест" }));
    fireEvent.change(screen.getByLabelText("Название филиала"), { target: { value: "Брест новый" } });
    view.rerender(<SpravBranches card={{ ...card, revision: 5, branches: [{ ...card.branches![0], revision: 3 }] }} />);
    fireEvent.click(screen.getByRole("button", { name: "Сохранить филиал" }));
    await screen.findByRole("alert");
    expect(fetchMock.mock.calls[0][0]).toBe("/api/system/mdm/counterparty/7/branches/12");
    const body = JSON.parse(String(fetchMock.mock.calls[0][1]?.body));
    expect(body.expected_legal_entity_revision).toBe(4);
    expect(body.expected_revision).toBe(2);
    expect(body.manual.portal_branch_code).toBe("0001");
    expect(screen.getByLabelText("Название филиала")).toHaveValue("Брест новый");
    expect(nav.refresh).not.toHaveBeenCalled();
  });

  it("создаёт филиал один раз и ждёт свежую карточку до повторного изменения", async () => {
    let resolve: (value: unknown) => void = () => {};
    const fetchMock = vi.fn(() => new Promise((done) => { resolve = done; }));
    vi.stubGlobal("fetch", fetchMock);
    const view = render(<SpravBranches card={card} />);
    fireEvent.click(screen.getByRole("button", { name: "Добавить филиал" }));
    fireEvent.change(screen.getByLabelText("Название филиала"), { target: { value: "Минск" } });
    const form = screen.getByRole("form", { name: "Редактор филиала" });
    fireEvent.submit(form); fireEvent.submit(form);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    resolve({ ok: true, status: 201, json: async () => ({ id: 13, revision: 1 }) });
    await waitFor(() => expect(nav.refresh).toHaveBeenCalledOnce());
    expect(screen.getByRole("button", { name: "Добавить филиал" })).toBeDisabled();
    view.rerender(<SpravBranches card={{ ...card, branches: [...card.branches!, { ...card.branches![0], id: 13, revision: 1, name: "Минск" }] }} />);
    expect(screen.getByRole("button", { name: "Добавить филиал" })).toBeEnabled();
  });
});
