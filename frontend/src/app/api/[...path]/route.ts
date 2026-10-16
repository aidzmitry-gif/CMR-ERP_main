// Прокси клиентских вызовов на backend FastAPI с проброской dev-роли и OIDC-заделом.
// Заменяет прежний rewrite `/api/:path*` (next.config.mjs): помимо переадресации
// добавляет заголовок `X-User-Roles` из cookie `aios_role`, чтобы backend применял
// матрицу доступа (config/access.py) и к мутациям из браузера, а не только к SSR.
// Authorization пробрасывается явно (см. `lib/api-proxy-headers.ts`) — готовность к auth_mode=oidc.

import { cookies } from "next/headers";
import type { NextRequest } from "next/server";

import { ROLE_COOKIE } from "@/lib/access";
import { buildBackendProxyHeaders } from "@/lib/api-proxy-headers";
import { ensureFreshAccessToken } from "@/lib/auth-session-server";
import { currentDevUsername } from "@/lib/role-server";

const BASE = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";

function isTimelineAttachmentDownload(segments: string[]): boolean {
  return segments.length === 9
    && segments[0] === "sales" && segments[1] === "deals"
    && /^\d+$/.test(segments[2]) && segments[3] === "timeline"
    && segments[4] === "comments" && /^\d+$/.test(segments[5])
    && segments[6] === "attachments" && /^\d+$/.test(segments[7])
    && segments[8] === "download";
}

async function proxy(req: NextRequest, segments: string[]): Promise<Response> {
  const jar = await cookies();
  const role = jar.get(ROLE_COOKIE)?.value;
  const accessToken = await ensureFreshAccessToken();
  const target = `${BASE}/${segments.join("/")}${req.nextUrl.search}`;

  const headers = buildBackendProxyHeaders(req.headers, { devRole: role, devUsername: await currentDevUsername(), accessToken: accessToken ?? undefined });

  const attachmentDownload = req.method === "GET" && isTimelineAttachmentDownload(segments);
  const init: RequestInit = { method: req.method, headers, cache: "no-store" };
  if (attachmentDownload) {
    // This route serves full downloads only; do not request a partial body that
    // would need Content-Range/If-Range semantics in the browser response.
    headers.delete("range");
    headers.delete("if-range");
    init.redirect = "manual";
  }
  if (req.method !== "GET" && req.method !== "HEAD") {
    init.body = await req.arrayBuffer();
  }

  const res = await fetch(target, init);
  if (attachmentDownload) {
    const out = new Headers({
      "cache-control": "private, no-store",
      "x-content-type-options": "nosniff",
      "accept-ranges": "none",
    });
    if (res.status === 206 || res.status === 416 || (res.status >= 300 && res.status < 400)) {
      return new Response("Download unavailable", { status: 502, headers: out });
    }
    const contentType = res.headers.get("content-type");
    if (contentType) out.set("content-type", contentType);
    const disposition = res.headers.get("content-disposition");
    if (disposition?.toLowerCase().startsWith("attachment;")) {
      out.set("content-disposition", disposition);
    } else if (res.ok) {
      out.set("content-disposition", "attachment");
    }
    return new Response(res.body, { status: res.status, statusText: res.statusText, headers: out });
  }
  const out = new Headers();
  const contentType = res.headers.get("content-type");
  if (contentType) out.set("content-type", contentType);
  const malformedTimelineDownload = segments[0] === "sales" && segments[1] === "deals"
    && segments[3] === "timeline" && segments[4] === "comments"
    && segments[6] === "attachments" && segments[8] === "download";
  for (const name of ["content-disposition", "x-content-type-options", "cache-control"]) {
    const value = res.headers.get(name);
    if (value && !(name === "content-disposition" && malformedTimelineDownload)) out.set(name, value);
  }
  // SSE/поток: пробрасываем тело стримом, НЕ буферизуем. Иначе text/event-stream
  // (окно входящего звонка, /sales/calls/stream) «висит» до закрытия апстрима и
  // карточки звонка не доходят до клиента.
  if (contentType?.includes("text/event-stream")) {
    out.set("cache-control", "no-cache, no-transform");
    out.set("connection", "keep-alive");
    return new Response(res.body, { status: res.status, statusText: res.statusText, headers: out });
  }
  const body = await res.arrayBuffer();
  return new Response(body, { status: res.status, statusText: res.statusText, headers: out });
}

type Ctx = { params: Promise<{ path: string[] }> };
const handler = async (req: NextRequest, ctx: Ctx) => proxy(req, (await ctx.params).path);

export {
  handler as GET,
  handler as POST,
  handler as PUT,
  handler as PATCH,
  handler as DELETE,
};
