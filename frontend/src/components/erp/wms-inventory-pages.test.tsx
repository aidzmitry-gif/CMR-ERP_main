import type { ReactNode } from "react";
import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import InventoryPage from "@/app/erp/wms/inventory/page";
import DetailPage from "@/app/erp/wms/inventory/[id]/page";
import CyclePage from "@/app/erp/wms/cycle-counts/page";
import { detail, inventory, jsonResponse, organizations, plan } from "@/test/inventory-fixtures";

const { auth, notFound } = vi.hoisted(() => ({
  auth: { Authorization: "Bearer synthetic-token", "X-User": "operator", "X-User-Roles": "warehouse" },
  notFound: vi.fn(() => { throw new Error("NEXT_NOT_FOUND"); }),
}));
vi.mock("@/lib/role-server", () => ({ currentRole: async () => "warehouse" }));
vi.mock("@/lib/auth-headers-server", () => ({ backendAuthHeaders: async () => auth }));
vi.mock("@/components/app-shell", () => ({ AppShell: ({ children }: { children: ReactNode }) => <>{children}</> }));
vi.mock("next/navigation", () => ({ notFound, useRouter: () => ({ push: vi.fn() }) }));
beforeEach(() => { notFound.mockClear(); });
afterEach(() => vi.unstubAllGlobals());

const company = { id: 1, name: "Юрлицо установки", unp: "987654321" };
const installation = { configuration: "platform_settings", revision: 3, organization: company };
const isInstallation = (url: string) => url.endsWith("system/instance-organization");

it.each(["inventory", "cycle"])("SSR %s uses the configured company with authenticated headers, not a company picker", async (kind) => {
  const fetcher = vi.fn((url: string) => Promise.resolve(jsonResponse(isInstallation(url) ? installation : kind === "inventory" ? [inventory()] : [plan()])));
  vi.stubGlobal("fetch", fetcher);
  const Page = kind === "inventory" ? InventoryPage : CyclePage;
  render(await Page({ searchParams: Promise.resolve({ organization_id: "1" }) }));
  await screen.findByText("Юрлицо установки · УНП 987654321");
  const serverCalls = fetcher.mock.calls.filter(([url]) => url.startsWith("http"));
  expect(serverCalls).toHaveLength(2);
  for (const [, options] of serverCalls) expect(options).toEqual({ cache: "no-store", headers: auth });
  expect(serverCalls[0][0]).toBe("http://127.0.0.1:8000/system/instance-organization");
  expect(serverCalls[1][0]).toContain("organization_id=1");
  expect(fetcher.mock.calls.some(([url]) => url.includes("receipt-organizations"))).toBe(false);
  expect(screen.queryByLabelText("Юрлицо")).not.toBeInTheDocument();
});

it("SSR without a hint uses the saved company and never chooses the first accessible book", async () => {
  const savedSecond = { ...installation, organization: { ...company, id: 2 } };
  const fetcher = vi.fn((url: string) => Promise.resolve(jsonResponse(isInstallation(url) ? savedSecond : [inventory({ organization_id: 2 })])));
  vi.stubGlobal("fetch", fetcher);
  render(await InventoryPage({ searchParams: Promise.resolve({}) }));
  await screen.findByText("ИНВ-7");
  expect(fetcher.mock.calls[1][0]).toContain("organization_id=2");
  expect(fetcher.mock.calls.some(([url]) => url.includes("receipt-organizations"))).toBe(false);
  expect(screen.queryByLabelText("Юрлицо")).not.toBeInTheDocument();
});

it.each(["inventory", "cycle"])("SSR %s rejects a foreign URL hint before fetching any documents", async (kind) => {
  const fetcher = vi.fn().mockResolvedValue(jsonResponse(installation));vi.stubGlobal("fetch", fetcher);
  const Page = kind === "inventory" ? InventoryPage : CyclePage;
  render(await Page({ searchParams: Promise.resolve({ organization_id: "2" }) }));
  expect(screen.getByRole("alert")).toHaveTextContent("Юрлицо ссылки не совпадает");
  expect(fetcher).toHaveBeenCalledTimes(1);
  expect(fetcher.mock.calls[0][0]).toContain("/system/instance-organization");
});

it("SSR cannot load documents when installation identity is unconfigured or malformed", async () => {
  const fetcher = vi.fn().mockResolvedValue(jsonResponse({ configuration: "platform_settings", revision: 1, organization: organizations[0] }));
  vi.stubGlobal("fetch", fetcher);
  render(await InventoryPage({ searchParams: Promise.resolve({}) }));
  expect(screen.getByRole("alert")).toHaveTextContent("некорректное юрлицо");
  expect(fetcher).toHaveBeenCalledTimes(1);
  expect(screen.queryByText("Инвентаризаций пока нет")).not.toBeInTheDocument();
});

it.each([403, 409, 503])("SSR HTTP %s stays a document error, not an empty list or404", async (status) => {
  vi.stubGlobal("fetch", vi.fn((url: string) => Promise.resolve(isInstallation(url) ? jsonResponse(installation) : jsonResponse({ detail: "SSR failure" }, status))));
  render(await InventoryPage({ searchParams: Promise.resolve({ organization_id: "1" }) }));
  expect(screen.getByRole("alert")).toHaveTextContent("SSR failure");
  expect(screen.queryByText("Инвентаризаций пока нет")).not.toBeInTheDocument();
  expect(notFound).not.toHaveBeenCalled();
});

it("SSR detail сохраняет headers и provenance", async () => {
  const fetcher = vi.fn().mockResolvedValue(jsonResponse(detail())); vi.stubGlobal("fetch", fetcher);
  render(await DetailPage({ params: Promise.resolve({ id: "7" }) }));
  expect(fetcher).toHaveBeenCalledWith("http://127.0.0.1:8000/wms/inventory/7", { cache: "no-store", headers: auth });
  expect(screen.getByText("a".repeat(64))).toBeInTheDocument();
});

it.each([403, 409, 503])("SSR detail %s не маскирует отказ под отсутствие документа", async (status) => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ detail: "Detail denied" }, status)));
  render(await DetailPage({ params: Promise.resolve({ id: "7" }) }));
  expect(screen.getByRole("alert")).toHaveTextContent("Detail denied");
  expect(notFound).not.toHaveBeenCalled();
});

it("только реальный 404 вызывает notFound", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({}, 404)));
  await expect(DetailPage({ params: Promise.resolve({ id: "7" }) })).rejects.toThrow("NEXT_NOT_FOUND");
  expect(notFound).toHaveBeenCalledTimes(1);
});

it("SSR сеть отображается ошибкой", async () => {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
  render(await CyclePage({ searchParams: Promise.resolve({ organization_id: "1" }) }));
  expect(screen.getByRole("alert")).toHaveTextContent("Ошибка сети");
  expect(screen.queryByText("Планов пока нет")).not.toBeInTheDocument();
});
