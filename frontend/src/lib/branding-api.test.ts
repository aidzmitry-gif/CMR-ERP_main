import { afterEach, describe, expect, it, vi } from "vitest";

import { fetchBranding, updateBranding } from "@/lib/branding-api";

afterEach(() => vi.unstubAllGlobals());

describe("branding-api", () => {
  it("возвращает branding при успешном GET", async () => {
    const branding = { logo_data_url: "logo", stamp_data_url: null, signature_data_url: "sign" };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => branding }));
    await expect(fetchBranding()).resolves.toEqual(branding);
  });

  it("безопасно деградирует на HTTP-ошибку и сетевое исключение", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false }));
    await expect(fetchBranding()).resolves.toEqual({ logo_data_url: null, stamp_data_url: null, signature_data_url: null });
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
    await expect(fetchBranding()).resolves.toEqual({ logo_data_url: null, stamp_data_url: null, signature_data_url: null });
  });

  it("отправляет только переданный patch и возвращает статус PUT", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true });
    vi.stubGlobal("fetch", fetchMock);
    await expect(updateBranding({ logo_data_url: "new-logo" })).resolves.toBe(true);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/sales/branding",
      expect.objectContaining({ method: "PUT", body: JSON.stringify({ logo_data_url: "new-logo" }) }),
    );
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false }));
    await expect(updateBranding({ stamp_data_url: null })).resolves.toBe(false);
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
    await expect(updateBranding({ signature_data_url: "x" })).resolves.toBe(false);
  });
});
