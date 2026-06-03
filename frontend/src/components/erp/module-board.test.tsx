import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ModuleBoard } from "@/components/erp/module-board";

let calls: { url: string; method: string }[];

beforeEach(() => {
  calls = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, opts?: { method?: string }) => {
      const method = opts?.method ?? "GET";
      calls.push({ url, method });
      if (method === "GET") {
        return { ok: true, json: async () => [{ id: 1, name: "Кампания", channel: "email", status: "new" }] };
      }
      return { ok: true, json: async () => ({}) };
    }),
  );
});
afterEach(() => vi.restoreAllMocks());

describe("ModuleBoard", () => {
  it("грузит строки и создаёт запись (POST)", async () => {
    render(
      <ModuleBoard
        title="Маркетинг"
        endpoint="/marketing/campaigns"
        columns={[{ key: "name", label: "Кампания" }, { key: "channel", label: "Канал" }]}
        fields={[{ key: "name", label: "Кампания" }, { key: "channel", label: "Канал" }]}
      />,
    );
    expect(await screen.findByText("Кампания")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Добавить/ }));
    fireEvent.click(screen.getByText("Сохранить"));
    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
  });

  it("смена статуса по клику (PATCH)", async () => {
    render(
      <ModuleBoard
        title="Закупки"
        endpoint="/procurement/requests"
        columns={[{ key: "name", label: "Имя" }, { key: "status", label: "Статус" }]}
        fields={[{ key: "name", label: "Имя" }]}
        statusKey="status"
        statusFlow={["new", "done"]}
        patchPath="/procurement/requests"
      />,
    );
    const statusBtn = await screen.findByRole("button", { name: "new" });
    fireEvent.click(statusBtn);
    await waitFor(() => expect(calls.some((c) => c.method === "PATCH")).toBe(true));
  });
});
