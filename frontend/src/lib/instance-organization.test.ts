import { afterEach, expect, it, vi } from "vitest";
import { fetchInstanceOrganization } from "./instance-organization";

afterEach(() => vi.unstubAllGlobals());
const organization = { id: 7, name: "Synthetic organization", unp: "987654321" };
const context = { configuration: "AIOS_SELLER_UNP", organization };
function serve(value: unknown, status = 200) {
  const fetcher = vi.fn().mockResolvedValue({ ok: status === 200, status, json: async () => value });
  vi.stubGlobal("fetch", fetcher);
  return fetcher;
}

it("reads the shared server context without a caller-selected organization", async () => {
  const fetcher = serve(context);
  expect(await fetchInstanceOrganization()).toEqual(organization);
  expect(fetcher).toHaveBeenCalledWith("/api/system/instance-organization", { cache: "no-store" });
});
it("rejects an unbound configuration source", async () => {
  serve({ ...context, configuration: "browser-choice" });
  await expect(fetchInstanceOrganization()).rejects.toThrow(/некорректное/);
});
it("rejects a malformed organization identifier", async () => {
  serve({ ...context, organization: { ...organization, id: true } });
  await expect(fetchInstanceOrganization()).rejects.toThrow(/некорректное/);
});
it("keeps denied access distinct from an empty document list", async () => {
  serve({ organization }, 403);
  await expect(fetchInstanceOrganization()).rejects.toThrow(/права сотрудника/);
});
it("shows configuration failure without trusting server response text", async () => {
  serve({ detail: "synthetic-private-message" }, 503);
  await expect(fetchInstanceOrganization()).rejects.toThrow(/настройки сервера/);
});
it("reports a network failure without selecting a fallback", async () => {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("synthetic-private-message")));
  await expect(fetchInstanceOrganization()).rejects.toThrow("Не удалось загрузить юрлицо установки. Повторите загрузку.");
});
