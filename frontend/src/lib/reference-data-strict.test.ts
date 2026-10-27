import { afterEach, expect, it, vi } from "vitest";
import { fetchAllSkus } from "./reference-data";
afterEach(() => vi.unstubAllGlobals());
it("strict SKU reads reject unavailable and malformed data, but accept an empty array", async () => {
  const fetcher = vi.fn().mockResolvedValueOnce({ ok: false, status: 503 })
    .mockResolvedValueOnce({ ok: true, json: async () => ({ result: null }) })
    .mockResolvedValueOnce({ ok: true, json: async () => ({ result: [] }) });
  vi.stubGlobal("fetch", fetcher);
  await expect(fetchAllSkus("director", 250, true)).rejects.toThrow();
  await expect(fetchAllSkus("director", 250, true)).rejects.toThrow("Некорректный");
  await expect(fetchAllSkus("director", 250, true)).resolves.toEqual([]);
});
