import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DocumentVersions } from "./document-versions";

const base = { id: 1, kind: "invoice", number: "СЧ-1", amount: 240, status: "posted", onec_ref: null,
  valid_until: null, reserve_status: "none", version: 1, original_state: "issued" };
afterEach(() => vi.unstubAllGlobals());

describe("DocumentVersions", () => {
  it("создаёт отдельный черновик по явной причине и сохраняет ключ при повторе", async () => {
    const fetch = vi.fn().mockResolvedValueOnce({ ok: false, json: async () => ({ detail: "Повторите запрос" }) })
      .mockResolvedValue({ ok: true });
    vi.stubGlobal("fetch", fetch);
    const refresh = vi.fn().mockResolvedValue(undefined);
    render(<DocumentVersions docs={[base]} refresh={refresh} />);
    fireEvent.click(screen.getByText("Новая версия #1"));
    fireEvent.change(screen.getByLabelText("Причина новой версии"), { target: { value: "Новая цена" } });
    fireEvent.click(screen.getByText("Создать черновик"));
    expect(await screen.findByRole("alert")).toHaveTextContent("Повторите запрос");
    fireEvent.click(screen.getByText("Создать черновик"));
    await waitFor(() => expect(refresh).toHaveBeenCalledOnce());
    const first = JSON.parse(fetch.mock.calls[0][1].body);
    const retry = JSON.parse(fetch.mock.calls[1][1].body);
    expect(first).toEqual(retry);
    expect(first.reason).toBe("Новая цена");
    expect(fetch.mock.calls[0][0]).toBe("/api/sales/documents/1/revision");
  });

  it("показывает старую оплату и постоянную ссылку на её оригинал", () => {
    render(<DocumentVersions docs={[{ ...base, status: "paid", superseded_by_id: 2 }]} refresh={vi.fn()} />);
    expect(screen.getByText(/Заменён документом #2; оплата: оплачен/)).toBeInTheDocument();
    expect(screen.getByText("Оригинал #1")).toHaveAttribute("href", "/api/sales/documents/1/render");
    expect(screen.queryByText("Новая версия #1")).toBeNull();
  });

  it("помечает неизвестный legacy оригинал", () => {
    render(<DocumentVersions docs={[{ ...base, original_state: "legacy_unavailable" }]} refresh={vi.fn()} />);
    expect(screen.getByText(/Историческое содержание неизвестно/)).toBeInTheDocument();
    expect(screen.queryByText("Оригинал #1")).toBeNull();
  });

  it("черновик выпускается отдельным действием", async () => {
    const fetch = vi.fn().mockResolvedValue({ ok: true });
    vi.stubGlobal("fetch", fetch);
    render(<DocumentVersions docs={[{ ...base, id: 2, status: "draft", original_state: "draft", supersedes_id: 1 }]} refresh={vi.fn()} />);
    fireEvent.click(screen.getByText("Выпустить версию"));
    await waitFor(() => expect(fetch).toHaveBeenCalledWith("/api/sales/documents/2/issue", expect.objectContaining({ method: "POST" })));
  });
});
