import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

vi.mock("next/headers", () => ({ cookies: async () => ({ get: () => undefined }) }));
vi.mock("@/lib/auth-session-server", () => ({ ensureFreshAccessToken: async () => null }));

import { GET } from "./route";

afterEach(() => vi.unstubAllGlobals());

describe("backend download proxy", () => {
  it("preserves attachment filename, MIME protection and cache policy with exact bytes", async () => {
    const bytes = new Uint8Array([0, 1, 127, 128, 255]);
    const disposition = "attachment; filename*=UTF-8''invoice.pdf";
    vi.stubGlobal("fetch", vi.fn(async () => new Response(bytes, { headers: {
      "content-type": "application/pdf", "content-disposition": disposition,
      "x-content-type-options": "nosniff", "cache-control": "no-store",
      "set-cookie": "upstream-secret=not-forwarded", "x-internal-debug": "not-forwarded",
    } })));
    const response = await GET(new NextRequest("http://localhost/api/sales/deals/1/incoming-emails/r/attachments/0"), {
      params: Promise.resolve({ path: ["sales", "deals", "1", "incoming-emails", "r", "attachments", "0"] }),
    });
    expect(response.headers.get("content-disposition")).toBe(disposition);
    expect(response.headers.get("content-type")).toBe("application/pdf");
    expect(response.headers.get("x-content-type-options")).toBe("nosniff");
    expect(response.headers.get("cache-control")).toBe("no-store");
    expect(response.headers.has("set-cookie")).toBe(false);
    expect(response.headers.has("x-internal-debug")).toBe(false);
    expect(new Uint8Array(await response.arrayBuffer())).toEqual(bytes);
  });

  it("keeps the existing event stream path and no-cache policy", async () => {
    const upstream = new Response("data: hello\n\n", { headers: { "content-type": "text/event-stream" } });
    const buffered = vi.spyOn(upstream, "arrayBuffer");
    vi.stubGlobal("fetch", vi.fn(async () => upstream));
    const response = await GET(new NextRequest("http://localhost/api/sales/calls/stream"), {
      params: Promise.resolve({ path: ["sales", "calls", "stream"] }),
    });
    expect(response.headers.get("cache-control")).toBe("no-cache, no-transform");
    expect(await response.text()).toBe("data: hello\n\n");
    expect(buffered).not.toHaveBeenCalled();
  });
});
