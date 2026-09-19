import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { CrmDirectory } from "./crm-directory";
import { loadDirectory, type DirectoryResult } from "@/lib/crm-directory";

vi.mock("@/lib/crm-directory", () => ({ DIRECTORY_PAGE_SIZE: 50, loadDirectory: vi.fn() }));
const load = vi.mocked(loadDirectory);
const row = { id: 1, name: "Visible company", unp: "123456789", is_active: true, deal_id: 9 };
const ok = (total = 1): DirectoryResult => ({ status: "ok", rows: [row], total });
beforeEach(() => vi.resetAllMocks());

describe("CRM directory pages", () => {
  it("shows loading, real rows and only the supplied deal link", async () => {
    let finish!: (value: DirectoryResult) => void;
    load.mockReturnValue(new Promise((resolve) => { finish = resolve; }));
    render(<CrmDirectory kind="clients" />);
    expect(screen.getByRole("status")).toHaveTextContent("Загрузка клиентов");
    expect(screen.queryByText(/Найдено/)).not.toBeInTheDocument();
    await act(async () => finish(ok()));
    expect(screen.getByText("Visible company")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Открыть сделку" })).toHaveAttribute("href", "/crm/deals/9");
  });
  it("separates a load failure from empty and retries", async () => {
    load.mockResolvedValueOnce({ status: "error" }).mockResolvedValueOnce({ status: "ok", rows: [], total: 0 });
    render(<CrmDirectory kind="clients" />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Не удалось загрузить");
    expect(screen.queryByText(/Нет доступных записей/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Повторить" }));
    expect(await screen.findByText("Найдено: 0")).toBeInTheDocument();
    expect(screen.getByText(/Нет доступных записей/)).toBeInTheDocument();
  });
  it.each(["forbidden", "unauthorized"] as const)("shows %s without records", async (status) => {
    load.mockResolvedValue({ status });
    render(<CrmDirectory kind="contacts" />);
    expect(await screen.findByRole("alert")).toHaveTextContent(status === "forbidden" ? "запрещён" : "Сессия истекла");
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
  it("paginates and resets the page on submitted search", async () => {
    load.mockResolvedValue(ok(51));
    render(<CrmDirectory kind="clients" />);
    await screen.findByText("Найдено: 51");
    fireEvent.click(screen.getByRole("button", { name: "Далее" }));
    await waitFor(() => expect(load).toHaveBeenLastCalledWith("clients", "", 50, expect.any(AbortSignal)));
    await screen.findByText("Страница 2");
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "  New name  " } });
    fireEvent.click(screen.getByRole("button", { name: "Найти" }));
    await waitFor(() => expect(load).toHaveBeenLastCalledWith("clients", "New name", 0, expect.any(AbortSignal)));
    await screen.findByText("Страница 1");
  });
  it("ignores late results after a new search and clears old records immediately", async () => {
    let late!: (value: DirectoryResult) => void;
    load.mockReturnValueOnce(new Promise((resolve) => { late = resolve; }));
    load.mockResolvedValueOnce({ status: "ok", rows: [], total: 0 });
    render(<CrmDirectory kind="clients" />);
    const oldSignal = load.mock.calls[0][3];
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "new" } });
    fireEvent.click(screen.getByRole("button", { name: "Найти" }));
    await screen.findByText("По вашему запросу ничего не найдено.");
    await act(async () => late(ok()));
    expect(oldSignal?.aborted).toBe(true);
    expect(screen.queryByText("Visible company")).not.toBeInTheDocument();
  });
  it("renders contact details without fabricating a deal", async () => {
    load.mockResolvedValue({ status: "ok", total: 1, rows: [{ id: 2, full_name: "Person",
      phone: null, email: "person@example.invalid", is_primary: true,
      counterparty_id: 1, counterparty_name: "Company", deal_id: null }] });
    render(<CrmDirectory kind="contacts" />);
    expect(await screen.findByText("Person")).toBeInTheDocument();
    expect(screen.getByText("Company")).toBeInTheDocument();
    expect(screen.getByText("Телефон не указан")).toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });
  it("aborts and ignores late results after unmount", async () => {
    let finish!: (value: DirectoryResult) => void;
    load.mockReturnValueOnce(new Promise((resolve) => { finish = resolve; }));
    const view = render(<CrmDirectory kind="clients" />);
    const signal = load.mock.calls[0][3];
    view.unmount();
    expect(signal?.aborted).toBe(true);
    await act(async () => finish(ok()));
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
});
