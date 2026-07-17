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

const BASE = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";

async function proxy(req: NextRequest, segments: string[]): Promise<Response> {
  const jar = await cookies();
  const role = jar.get(ROLE_COOKIE)?.value;
  const accessToken = await ensureFreshAccessToken();
  const target = `${BASE}/${segments.join("/")}${req.nextUrl.search}`;

  const headers = buildBackendProxyHeaders(req.headers, { devRole: role, accessToken: accessToken ?? undefined });

  const init: RequestInit = { method: req.method, headers, cache: "no-store" };
  if (req.method !== "GET" && req.method !== "HEAD") {
    init.body = await req.arrayBuffer();
  }

  const res = await fetch(target, init);
  const out = new Headers();
  const contentType = res.headers.get("content-type");
  if (contentType) out.set("content-type", contentType);
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
