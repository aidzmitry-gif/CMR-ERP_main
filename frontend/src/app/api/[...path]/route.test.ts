import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

vi.mock("next/headers", () => ({ cookies: vi.fn(async () => ({ get: () => undefined })) }));
vi.mock("@/lib/auth-session-server", () => ({ ensureFreshAccessToken: vi.fn(async () => "synthetic-token") }));
vi.mock("@/lib/role-server", () => ({ currentDevUsername: vi.fn(async () => "synthetic-user") }));

import { GET } from "./route";

const downloadPath = ["sales", "deals", "42", "timeline", "comments", "7", "attachments", "19", "download"];

function request(headers = new Headers()) {
  return {
    method: "GET",
    headers,
    nextUrl: { search: "" },
  } as Parameters<typeof GET>[0];
}

async function get(path = downloadPath, headers = new Headers()) {
  return GET(request(headers), { params: Promise.resolve({ path }) });
}

afterEach(() => vi.unstubAllGlobals());

describe("timeline attachment download proxy", () => {
  it("streams the same body and forwards only safe download headers", async () => {
    const stream = new ReadableStream<Uint8Array>();
    const arrayBuffer = vi.fn(() => { throw new Error("download must not buffer"); });
    const fetch = vi.fn().mockResolvedValue({
      status: 200, statusText: "OK", body: stream, arrayBuffer,
      headers: new Headers({
        "content-type": "application/pdf",
        "content-disposition": 'attachment; filename="Act.pdf"',
        location: "https://storage.example/secret",
        "set-cookie": "secret=1",
      }),
    });
    vi.stubGlobal("fetch", fetch);
    const res = await get();
    expect(res.status).toBe(200);
    expect(res.body).toBe(stream);
    expect(arrayBuffer).not.toHaveBeenCalled();
    expect(res.headers.get("content-type")).toBe("application/pdf");
    expect(res.headers.get("content-disposition")).toBe('attachment; filename="Act.pdf"');
    expect(res.headers.get("cache-control")).toBe("private, no-store");
    expect(res.headers.get("x-content-type-options")).toBe("nosniff");
    expect(res.headers.get("accept-ranges")).toBe("none");
    expect(res.headers.has("location")).toBe(false);
    expect(res.headers.has("set-cookie")).toBe(false);
    expect(fetch).toHaveBeenCalledWith(expect.stringContaining("/sales/deals/42/timeline/comments/7/attachments/19/download"),
      expect.objectContaining({ redirect: "manual", cache: "no-store" }));
    const upstreamHeaders = fetch.mock.calls[0][1].headers as Headers;
    expect(upstreamHeaders.get("authorization")).toBe("Bearer synthetic-token");
  });

  it("strips browser Range and If-Range before requesting the full attachment", async () => {
    const fetch = vi.fn().mockResolvedValue({
      status: 200, statusText: "OK", body: null,
      headers: new Headers({ "content-type": "application/octet-stream" }),
    });
    vi.stubGlobal("fetch", fetch);
    const res = await get(downloadPath, new Headers({
      range: "bytes=100-", "if-range": '"synthetic-etag"',
    }));
    const upstreamHeaders = fetch.mock.calls[0][1].headers as Headers;
    expect(upstreamHeaders.has("range")).toBe(false);
    expect(upstreamHeaders.has("if-range")).toBe(false);
    expect(res.status).toBe(200);
    expect(res.headers.get("accept-ranges")).toBe("none");
  });

  it.each([206, 416])("rejects unexpected upstream HTTP %i without a malformed range response", async (status) => {
    const arrayBuffer = vi.fn(() => { throw new Error("download must not buffer"); });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      status, statusText: "Unexpected range", body: null, arrayBuffer,
      headers: new Headers({ "content-range": "bytes 0-99/1000" }),
    }));
    const res = await get();
    expect(res.status).toBe(502);
    expect(res.headers.has("content-range")).toBe(false);
    expect(res.headers.get("accept-ranges")).toBe("none");
    expect(arrayBuffer).not.toHaveBeenCalled();
  });

  it.each([401, 403, 404])("preserves upstream HTTP %i without redirecting or buffering", async (status) => {
    const arrayBuffer = vi.fn(() => { throw new Error("download must not buffer"); });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      status, statusText: "Denied", body: null, arrayBuffer,
      headers: new Headers({ "content-type": "application/json" }),
    }));
    const res = await get();
    expect(res.status).toBe(status);
    expect(res.headers.get("cache-control")).toBe("private, no-store");
    expect(arrayBuffer).not.toHaveBeenCalled();
  });

  it("rejects upstream redirects without exposing their Location", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      status: 302, statusText: "Found", body: null,
      headers: new Headers({ location: "https://storage.example/private" }),
    }));
    const res = await get();
    expect(res.status).toBe(502);
    expect(res.headers.has("location")).toBe(false);
    expect(res.headers.get("cache-control")).toBe("private, no-store");
  });

  it("keeps ordinary API response buffering and never enables manual redirect for nonnumeric paths", async () => {
    const arrayBuffer = vi.fn(async () => new TextEncoder().encode("ordinary").buffer);
    const fetch = vi.fn().mockResolvedValue({
      status: 200, statusText: "OK", body: null, arrayBuffer,
      headers: new Headers({ "content-type": "text/plain", "content-disposition": "attachment" }),
    });
    vi.stubGlobal("fetch", fetch);
    const res = await get(["sales", "deals", "42", "timeline", "comments", "../7", "attachments", "19", "download"],
      new Headers({ range: "bytes=100-" }));
    expect(await res.text()).toBe("ordinary");
    expect(arrayBuffer).toHaveBeenCalledOnce();
    expect(res.headers.has("content-disposition")).toBe(false);
    expect(fetch.mock.calls[0][1].redirect).toBeUndefined();
    expect((fetch.mock.calls[0][1].headers as Headers).get("range")).toBe("bytes=100-");
  });
});

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
