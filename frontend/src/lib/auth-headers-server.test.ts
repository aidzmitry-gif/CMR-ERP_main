import { afterEach, expect, it, vi } from "vitest";
import { ACTOR_COOKIE, TOKEN_COOKIE } from "@/lib/access";
import { backendAuthHeaders } from "./auth-headers-server";
const state = vi.hoisted(() => ({ mode: "dev", values: {} as Record<string, string> }));
vi.mock("next/headers", () => ({ cookies: async () => ({ get: (key: string) => state.values[key] ? { value: state.values[key] } : undefined }) }));
vi.mock("@/lib/auth-mode", () => ({ frontendAuthMode: () => state.mode }));
afterEach(() => { state.mode = "dev"; state.values = {}; });
it("uses the same authenticated development actor as browser API requests", async () => {
 state.values[ACTOR_COOKIE] = "warehouse-user";
 expect(await backendAuthHeaders("warehouse")).toEqual({ "X-User-Roles": "warehouse", "X-User": "warehouse-user" });
});
it("does not invent an actor when the development session lacks one", async () => {
 expect(await backendAuthHeaders("warehouse")).not.toHaveProperty("X-User");
});
it("OIDC uses bearer identity and never forwards the development actor", async () => {
 state.mode = "oidc"; state.values[ACTOR_COOKIE] = "untrusted-actor"; state.values[TOKEN_COOKIE] = "synthetic-token";
 const headers = await backendAuthHeaders("warehouse");
 expect(headers.Authorization).toBe("Bearer synthetic-token"); expect(headers).not.toHaveProperty("X-User");
});
