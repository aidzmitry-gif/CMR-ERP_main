// Explicit silent refresh (also covered by middleware + API proxy).

import { NextResponse } from "next/server";

import { ensureFreshAccessToken } from "@/lib/auth-session-server";

export async function POST(): Promise<Response> {
  const token = await ensureFreshAccessToken();
  if (!token) {
    return NextResponse.json({ ok: false, error: "no_session" }, { status: 401 });
  }
  return NextResponse.json({ ok: true });
}
