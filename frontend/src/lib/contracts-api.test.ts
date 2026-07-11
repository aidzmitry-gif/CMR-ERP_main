import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchContractTemplates, prepareContract } from "@/lib/contracts-api";

afterEach(() => vi.restoreAllMocks());

function mockFetch(impl: (...args: unknown[]) => Promise<unknown>) {
  global.fetch = vi.fn(impl) as unknown as typeof fetch;
}

const apiDoc = {
  id: 9,
  kind: "contract",
  number: "ДГ-1",
  status: "pending_approval",
  onec_ref: null,
  amount: 100,
  valid_until: null,
  reserve_status: "none",
};

describe("contracts-api", () => {
  it("fetchContractTemplates возвращает список при 200", async () => {
    mockFetch(async () => ({
      ok: true,
      json: async () => [{ id: 1, code: "supply-basic", name: "Поставка (базовый)" }],
    }));
    expect(await fetchContractTemplates()).toEqual([
      { id: 1, code: "supply-basic", name: "Поставка (базовый)" },
    ]);
  });

  it("fetchContractTemplates при HTTP-ошибке → []", async () => {
    mockFetch(async () => ({ ok: false }));
    expect(await fetchContractTemplates()).toEqual([]);
  });

  it("fetchContractTemplates при исключении → []", async () => {
    mockFetch(async () => {
      throw new Error("net");
    });
    expect(await fetchContractTemplates()).toEqual([]);
  });

  it("prepareContract при 201 — ok + сообщение с номером + doc", async () => {
    mockFetch(async () => ({ ok: true, json: async () => apiDoc }));
    const result = await prepareContract("1", "supply-basic");
    expect(result.ok).toBe(true);
    expect(result.message).toBe("✅ Договор ДГ-1 отправлен на согласование");
    expect(result.doc?.status).toBe("pending_approval");
  });

  it("prepareContract шлёт POST на /deals/{id}/contract с template_code", async () => {
    const f = vi.fn(async () => ({ ok: true, json: async () => apiDoc }));
    mockFetch(f);
    await prepareContract("7", "supply-basic");
    expect(f).toHaveBeenCalledWith(
      "/api/sales/deals/7/contract",
      expect.objectContaining({
        method: "POST",
        body: expect.stringContaining("supply-basic"),
      }),
    );
  });

  it("prepareContract при 409 — ok:false + detail с бэка как message", async () => {
    mockFetch(async () => ({
      ok: false,
      json: async () => ({ detail: "Договор по сделке уже подготовлен" }),
    }));
    expect(await prepareContract("1", "supply-basic")).toEqual({
      ok: false,
      message: "Договор по сделке уже подготовлен",
    });
  });

  it("prepareContract при ошибке без JSON-тела → общее сообщение", async () => {
    mockFetch(async () => ({
      ok: false,
      json: async () => {
        throw new Error("not json");
      },
    }));
    expect(await prepareContract("1", "supply-basic")).toEqual({
      ok: false,
      message: "⚠️ Не удалось подготовить договор",
    });
  });

  it("prepareContract при исключении сети → ok:false с общим сообщением", async () => {
    mockFetch(async () => {
      throw new Error("net");
    });
    expect(await prepareContract("1", "supply-basic")).toEqual({
      ok: false,
      message: "⚠️ Не удалось подготовить договор",
    });
  });
});
