import { afterEach, expect, it, vi } from "vitest";
import { loadRegistry, loadSourcePreview } from "./global-document-register";
const filters = { q: "", kind: "", date_from: "", date_to: "", limit: 50 };
const signal = () => new AbortController().signal;
const serve = (value: unknown) => vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(value))));
afterEach(() => vi.unstubAllGlobals());
it("rejects a response from a different organization", async () => {
  serve({ organization_id: 2, source: "1c", page: 1, limit: 50, total: 0, pages: 1, items: [], kinds: [] });
  await expect(loadRegistry("1", "1c", 1, filters, signal())).rejects.toThrow("некорректные");
});
it("rejects an out-of-scope item even when its envelope matches", async () => {
  serve({ organization_id: 1, source: "1c", page: 1, limit: 50, total: 1, pages: 1, items: [{ id: 1, organization_id: 2 }], kinds: [] });
  await expect(loadRegistry("1", "1c", 1, filters, signal())).rejects.toThrow("некорректные");
});
it("does not accept a source preview claiming posting or an original", async () => {
  serve({ id: 1, organization_id: 1, source: "1c", status: "SOURCE_ONLY", native_posted: true, original_available: true });
  await expect(loadSourcePreview("1", 1, 1, signal())).rejects.toThrow("некорректные");
});
it("rejects invalid organization IDs before making a request", async () => {
  const request = vi.fn(); vi.stubGlobal("fetch", request);
  await expect(loadRegistry("1/../../2", "1c", 1, filters, signal())).rejects.toThrow();
  expect(request).not.toHaveBeenCalled();
});
