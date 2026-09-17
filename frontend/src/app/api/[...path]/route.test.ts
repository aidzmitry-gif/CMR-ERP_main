import { beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

const jar = vi.hoisted(() => ({
  get: vi.fn(() => ({ value: "sales" })),
}));
const auth = vi.hoisted(() => ({ ensureFreshAccessToken: vi.fn(async () => "access-token") }));
const headersMock = vi.hoisted(() => ({
  buildBackendProxyHeaders: vi.fn(() => new Headers({ "x-test": "1" })),
}));

vi.mock("next/headers", () => ({ cookies: vi.fn(async () => jar) }));
vi.mock("@/lib/auth-session-server", () => auth);
vi.mock("@/lib/api-proxy-headers", () => headersMock);

import { GET, POST } from "@/app/api/[...path]/route";

beforeEach(() => {
  vi.clearAllMocks();
});

describe("API proxy route", () => {
  it("проксирует обычный ответ, query, роли и bearer", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), {
        status: 201,
        statusText: "Created",
        headers: { "content-type": "application/json", "x-hidden": "no" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const res = await GET(
      new NextRequest("http://frontend/api/sales/board?funnel=new"),
      { params: Promise.resolve({ path: ["sales", "board"] }) },
    );
    expect(res.status).toBe(201);
    expect(res.headers.get("content-type")).toContain("application/json");
    expect(await res.json()).toEqual({ ok: true });
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/sales/board?funnel=new"),
      expect.objectContaining({ method: "GET", cache: "no-store" }),
    );
    expect(headersMock.buildBackendProxyHeaders).toHaveBeenCalledWith(
      expect.any(Headers),
      { devRole: "sales", accessToken: "access-token" },
    );
  });

  it("передаёт body у POST и сохраняет SSE stream без буферизации", async () => {
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(new TextEncoder().encode("data: ping\n\n"));
        controller.close();
      },
    });
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response("accepted", { status: 202 }))
      .mockResolvedValueOnce(
        new Response(stream, {
          status: 200,
          headers: { "content-type": "text/event-stream" },
        }),
      );
    vi.stubGlobal("fetch", fetchMock);

    const post = await POST(
      new NextRequest("http://frontend/api/sales/deals", { method: "POST", body: JSON.stringify({ title: "x" }) }),
      { params: Promise.resolve({ path: ["sales", "deals"] }) },
    );
    expect(post.status).toBe(202);
    expect(fetchMock.mock.calls[0][1]).toEqual(
      expect.objectContaining({ method: "POST", body: expect.any(ArrayBuffer) }),
    );

    const sse = await GET(
      new NextRequest("http://frontend/api/sales/calls/stream"),
      { params: Promise.resolve({ path: ["sales", "calls", "stream"] }) },
    );
    expect(sse.headers.get("cache-control")).toBe("no-cache, no-transform");
    expect(sse.headers.get("connection")).toBe("keep-alive");
    expect(await sse.text()).toContain("data: ping");
  });
});
