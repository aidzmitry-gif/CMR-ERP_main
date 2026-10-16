import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DealTimelineComments } from "./deal-timeline-comments";

afterEach(() => vi.unstubAllGlobals());

function response(status: number, rows: unknown = []) {
  return { status, ok: status === 200, json: async () => rows };
}

describe("DealTimelineComments", () => {
  it("keeps API chronology and renders imported body as escaped text with whitespace", async () => {
    const body = '<img src=x onerror="alert(1)">\n  Следующая строка';
    const fetch = vi.fn().mockResolvedValue(response(200, [
      { id: 9, body, author_display: "Клиент", created_at: "2026-09-20T10:00:00Z" },
      { id: 3, body: "Ранее", author_display: null, created_at: "2026-09-19T10:00:00Z" },
    ]));
    vi.stubGlobal("fetch", fetch);
    const { container } = render(<DealTimelineComments dealId="42" />);
    const rows = await screen.findAllByRole("listitem");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("Клиент");
    expect(rows[0].querySelector("p")?.textContent).toBe(body);
    expect(rows[1]).toHaveTextContent("Автор не указан");
    expect(container.querySelector("img, a")).toBeNull();
    expect(rows[0].querySelector("p")).toHaveClass("whitespace-pre-wrap");
    expect(rows[0].querySelector("time")).toHaveAttribute("dateTime", "2026-09-20T10:00:00Z");
    expect(fetch).toHaveBeenCalledWith("/api/sales/deals/42/timeline/comments",
      expect.objectContaining({ cache: "no-store", signal: expect.any(AbortSignal) }));
  });

  it("treats naive timestamps as UTC and displays Minsk time without changing explicit offsets", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(200, [
      { id: 1, body: "Naive UTC", author_display: "Автор", created_at: "2024-11-02T07:00:00" },
      { id: 2, body: "Explicit UTC", author_display: "Автор", created_at: "2024-11-02T07:00:00Z" },
      { id: 3, body: "Explicit Minsk", author_display: "Автор", created_at: "2024-11-02T07:00:00+03:00" },
      { id: 4, body: "Malformed", author_display: "Автор", created_at: "invalid-timestamp" },
    ])));
    render(<DealTimelineComments dealId="42" />);
    const rows = await screen.findAllByRole("listitem");
    expect(rows[0].querySelector("time")).toHaveTextContent("10:00");
    expect(rows[1].querySelector("time")).toHaveTextContent("10:00");
    expect(rows[2].querySelector("time")).toHaveTextContent("07:00");
    expect(rows[3].querySelector("time")).toHaveTextContent("invalid-timestamp");
  });

  it("distinguishes loading from a confirmed empty timeline", async () => {
    let finish!: (value: unknown) => void;
    vi.stubGlobal("fetch", vi.fn().mockReturnValue(new Promise((resolve) => { finish = resolve; })));
    render(<DealTimelineComments dealId="42" />);
    expect(screen.getByRole("status")).toHaveTextContent("Загрузка комментариев");
    expect(screen.queryByText("Комментариев в истории сделки нет.")).not.toBeInTheDocument();
    await act(async () => finish(response(200)));
    expect(screen.getByText("Комментариев в истории сделки нет.")).toBeInTheDocument();
  });

  it.each([
    [401, "Сессия истекла"], [403, "недоступны"], [404, "недоступны"],
  ])("shows access state for HTTP %i without an empty-state claim", async (status, message) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(status)));
    render(<DealTimelineComments dealId="42" />);
    expect(await screen.findByRole("alert")).toHaveTextContent(message);
    expect(screen.queryByText("Комментариев в истории сделки нет.")).not.toBeInTheDocument();
  });

  it("shows a retryable error for service failure or invalid JSON", async () => {
    const fetch = vi.fn().mockResolvedValueOnce(response(500))
      .mockResolvedValueOnce(response(200, [{ id: 1, body: "missing author" }]))
      .mockResolvedValueOnce(response(200));
    vi.stubGlobal("fetch", fetch);
    render(<DealTimelineComments dealId="42" />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Не удалось загрузить комментарии");
    fireEvent.click(screen.getByRole("button", { name: "Повторить" }));
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
    expect(await screen.findByRole("alert")).toHaveTextContent("Не удалось загрузить комментарии");
    fireEvent.click(screen.getByRole("button", { name: "Повторить" }));
    expect(await screen.findByText("Комментариев в истории сделки нет.")).toBeInTheDocument();
  });

  it("does not show a late result from another deal", async () => {
    let finish!: (value: unknown) => void;
    const fetch = vi.fn().mockReturnValueOnce(new Promise((resolve) => { finish = resolve; }))
      .mockResolvedValueOnce(response(200));
    vi.stubGlobal("fetch", fetch);
    const view = render(<DealTimelineComments dealId="1" />);
    view.rerender(<DealTimelineComments dealId="2" />);
    expect(await screen.findByText("Комментариев в истории сделки нет.")).toBeInTheDocument();
    await act(async () => finish(response(200, [
      { id: 1, body: "Старое", author_display: "Автор", created_at: "2026-09-20T10:00:00Z" },
    ])));
    expect(screen.queryByText("Старое")).not.toBeInTheDocument();
  });

  it("loads attachments only for an expanded comment, without an N+1 request", async () => {
    const fetch = vi.fn().mockResolvedValueOnce(response(200, [
      { id: 7, body: "Первый", author_display: "Автор", created_at: "2026-09-20T10:00:00Z" },
      { id: 8, body: "Второй", author_display: "Автор", created_at: "2026-09-20T10:00:00Z" },
    ])).mockResolvedValueOnce(response(200, []));
    vi.stubGlobal("fetch", fetch);
    render(<DealTimelineComments dealId="42" />);
    const rows = await screen.findAllByRole("listitem");
    expect(fetch).toHaveBeenCalledTimes(1);
    fireEvent.click(within(rows[0]).getByRole("button", { name: "Вложения" }));
    expect(await within(rows[0]).findByText("Вложений нет.")).toBeInTheDocument();
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(fetch).toHaveBeenLastCalledWith("/api/sales/deals/42/timeline/comments/7/attachments",
      expect.objectContaining({ cache: "no-store", signal: expect.any(AbortSignal) }));
    expect(within(rows[1]).queryByText("Вложений нет.")).not.toBeInTheDocument();
  });

  it("uses numeric same-origin download URLs and ignores untrusted metadata URLs", async () => {
    const fetch = vi.fn().mockResolvedValueOnce(response(200, [
      { id: 7, body: "Документ", author_display: "Автор", created_at: "2026-09-20T10:00:00Z" },
    ])).mockResolvedValueOnce(response(200, [
      { id: 19, filename: "Акт.pdf", content_type: "application/pdf", size_bytes: 2048,
        source_url: "https://evil.example/file", storage_path: "private/secret" },
      { id: 20, filename: "<img src=x onerror=alert(1)>", content_type: "text/html", size_bytes: 0 },
    ]));
    vi.stubGlobal("fetch", fetch);
    const { container } = render(<DealTimelineComments dealId="42" />);
    fireEvent.click(await screen.findByRole("button", { name: "Вложения" }));
    const link = await screen.findByRole("link", { name: "Акт.pdf" });
    expect(link).toHaveAttribute("href", "/api/sales/deals/42/timeline/comments/7/attachments/19/download");
    expect(link).toHaveAttribute("download");
    expect(screen.getByText(/2\s*048 байт/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "<img src=x onerror=alert(1)>" })).toHaveAttribute(
      "href", "/api/sales/deals/42/timeline/comments/7/attachments/20/download");
    expect(container.querySelector("img")).toBeNull();
    expect(container).not.toHaveTextContent("private/secret");
    expect(container.innerHTML).not.toContain("evil.example");
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it("shows attachment access errors and retries service errors", async () => {
    const fetch = vi.fn().mockResolvedValueOnce(response(200, [
      { id: 7, body: "Документ", author_display: "Автор", created_at: "2026-09-20T10:00:00Z" },
    ])).mockResolvedValueOnce(response(500)).mockResolvedValueOnce(response(200, []));
    vi.stubGlobal("fetch", fetch);
    render(<DealTimelineComments dealId="42" />);
    fireEvent.click(await screen.findByRole("button", { name: "Вложения" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Не удалось загрузить вложения");
    fireEvent.click(screen.getByRole("button", { name: "Повторить загрузку вложений" }));
    expect(await screen.findByText("Вложений нет.")).toBeInTheDocument();
    expect(fetch).toHaveBeenCalledTimes(3);
  });

  it.each([[401, "Сессия истекла"], [403, "недоступны"], [404, "недоступны"]])(
    "reports attachment list HTTP %i without a false empty state", async (status, message) => {
      vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(response(200, [
        { id: 7, body: "Документ", author_display: "Автор", created_at: "2026-09-20T10:00:00Z" },
      ])).mockResolvedValueOnce(response(status)));
      render(<DealTimelineComments dealId="42" />);
      fireEvent.click(await screen.findByRole("button", { name: "Вложения" }));
      expect(await screen.findByRole("alert")).toHaveTextContent(message);
      expect(screen.queryByText("Вложений нет.")).not.toBeInTheDocument();
    },
  );

  it("rejects malformed attachment IDs instead of constructing an untrusted download link", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(response(200, [
      { id: 7, body: "Документ", author_display: "Автор", created_at: "2026-09-20T10:00:00Z" },
    ])).mockResolvedValueOnce(response(200, [
      { id: "../19", filename: "Акт.pdf", content_type: "application/pdf", size_bytes: 1 },
    ])));
    render(<DealTimelineComments dealId="42" />);
    fireEvent.click(await screen.findByRole("button", { name: "Вложения" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Не удалось загрузить вложения");
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });
});
