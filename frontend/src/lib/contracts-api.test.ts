import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchContractTemplates, prepareContract, sendPackage } from "@/lib/contracts-api";

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

  it("sendPackage при успехе — ok + фиксированный текст пакета", async () => {
    mockFetch(async () => ({
      ok: true,
      json: async () => ({
        deal_id: 1,
        invoice_number: "СЧ-1",
        contract_number: "ДГ-1",
        channel: "email",
        sent: true,
      }),
    }));
    expect(await sendPackage("1")).toEqual({
      ok: true,
      message: "✅ Пакет отправлен: счёт + договор",
    });
  });

  it("sendPackage шлёт POST на /deals/{id}/send-package", async () => {
    const f = vi.fn(async () => ({ ok: true, json: async () => ({}) }));
    mockFetch(f);
    await sendPackage("7");
    expect(f).toHaveBeenCalledWith(
      "/api/sales/deals/7/send-package",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("sendPackage при 409 — ok:false + detail с бэка как message", async () => {
    mockFetch(async () => ({
      ok: false,
      json: async () => ({ detail: "Нужны проведённый счёт и согласованный договор" }),
    }));
    expect(await sendPackage("1")).toEqual({
      ok: false,
      message: "Нужны проведённый счёт и согласованный договор",
    });
  });

  it("sendPackage при ошибке без JSON-тела → общее сообщение", async () => {
    mockFetch(async () => ({
      ok: false,
      json: async () => {
        throw new Error("not json");
      },
    }));
    expect(await sendPackage("1")).toEqual({
      ok: false,
      message: "⚠️ Не удалось отправить пакет",
    });
  });

  it("sendPackage при исключении сети → ok:false с общим сообщением", async () => {
    mockFetch(async () => {
      throw new Error("net");
    });
    expect(await sendPackage("1")).toEqual({
      ok: false,
      message: "⚠️ Не удалось отправить пакет",
    });
  });
});
