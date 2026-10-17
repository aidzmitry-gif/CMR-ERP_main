import { beforeEach, describe, expect, it, vi } from "vitest";

const pageMocks = vi.hoisted(() => ({
  backendAuthHeaders: vi.fn(),
  currentRole: vi.fn(),
  fetchSkuCard: vi.fn(),
  fetchQualitySummary: vi.fn(),
  fetchDuplicateClusters: vi.fn(),
  fetchSyncJournal: vi.fn(),
  fetchNomenclatureGroups: vi.fn(),
  fetchSurvivorshipRules: vi.fn(),
  fetchPendingReferenceApprovals: vi.fn(),
  fetchCurrencyRates: vi.fn(),
  fetchVatRates: vi.fn(),
  fetchAiCatalog: vi.fn(),
}));

vi.mock("@/components/app-shell", () => ({ AppShell: () => null }));
vi.mock("@/components/erp/spravochniki/sprav-sku-card", () => ({ SpravSkuCard: () => null }));
vi.mock("@/components/erp/spravochniki/sprav-quality", () => ({ SpravQuality: () => null }));
vi.mock("@/components/erp/spravochniki/sprav-merge", () => ({ SpravMerge: () => null }));
vi.mock("@/components/erp/spravochniki/sprav-sync-journal", () => ({ SpravSyncJournal: () => null }));
vi.mock("@/components/erp/spravochniki/sprav-categories", () => ({ SpravCategories: () => null }));
vi.mock("@/components/erp/spravochniki/sprav-merge-rules", () => ({ SpravMergeRules: () => null }));
vi.mock("@/components/erp/spravochniki/sprav-admin", () => ({ SpravAdmin: () => null }));
vi.mock("@/components/erp/spravochniki/sprav-rates", () => ({ SpravRates: () => null }));
vi.mock("@/components/erp/spravochniki/sprav-ai", () => ({ SpravAi: () => null }));
vi.mock("@/lib/auth-headers-server", () => ({
  backendAuthHeaders: pageMocks.backendAuthHeaders,
}));
vi.mock("@/lib/role-server", () => ({ currentRole: pageMocks.currentRole }));
vi.mock("@/lib/reference-data", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/reference-data")>();
  return {
    ...actual,
    fetchSkuCard: pageMocks.fetchSkuCard,
    fetchQualitySummary: pageMocks.fetchQualitySummary,
    fetchDuplicateClusters: pageMocks.fetchDuplicateClusters,
    fetchSyncJournal: pageMocks.fetchSyncJournal,
    fetchNomenclatureGroups: pageMocks.fetchNomenclatureGroups,
    fetchSurvivorshipRules: pageMocks.fetchSurvivorshipRules,
    fetchPendingReferenceApprovals: pageMocks.fetchPendingReferenceApprovals,
    fetchCurrencyRates: pageMocks.fetchCurrencyRates,
    fetchVatRates: pageMocks.fetchVatRates,
    fetchAiCatalog: pageMocks.fetchAiCatalog,
  };
});

import SkuCardPage from "./sku/[code]/page";
import QualityPage from "./quality/page";
import MergePage from "./merge/page";
import SyncPage from "./sync/page";
import CategoriesPage from "./categories/page";
import RulesPage from "./rules/page";
import AdminPage from "./admin/page";
import RatesPage from "./rates/page";
import AiPage from "./ai/page";

const authHeaders = {
  Authorization: "Bearer synthetic-g09c-page-token",
  "X-User-Roles": "director",
};

function expectAuthenticatedPage(element: unknown) {
  expect(pageMocks.currentRole).toHaveBeenCalledTimes(1);
  expect(pageMocks.backendAuthHeaders).toHaveBeenCalledTimes(1);
  expect(pageMocks.backendAuthHeaders).toHaveBeenCalledWith("director");
  expect(JSON.stringify(element)).not.toContain("synthetic-g09c-page-token");
}

beforeEach(() => {
  vi.clearAllMocks();
  pageMocks.currentRole.mockResolvedValue("director");
  pageMocks.backendAuthHeaders.mockResolvedValue(authHeaders);
  pageMocks.fetchSkuCard.mockResolvedValue({ code: "SKU-1", title: "Товар" });
  pageMocks.fetchQualitySummary.mockResolvedValue([]);
  pageMocks.fetchDuplicateClusters.mockResolvedValue([]);
  pageMocks.fetchSyncJournal.mockResolvedValue([]);
  pageMocks.fetchNomenclatureGroups.mockResolvedValue([]);
  pageMocks.fetchSurvivorshipRules.mockResolvedValue([]);
  pageMocks.fetchPendingReferenceApprovals.mockResolvedValue([]);
  pageMocks.fetchCurrencyRates.mockResolvedValue([]);
  pageMocks.fetchVatRates.mockResolvedValue([]);
  pageMocks.fetchAiCatalog.mockResolvedValue(null);
});

describe("Reference SSR pages forward server auth headers", () => {
  it("[PAGE-CARD] forwards auth headers to the encoded-code loader", async () => {
    const page = await SkuCardPage({ params: Promise.resolve({ code: "SKU%2F1" }) });
    expectAuthenticatedPage(page);
    expect(pageMocks.fetchSkuCard).toHaveBeenCalledWith("SKU/1", "director", authHeaders);
  });

  it("[PAGE-QUALITY] forwards auth headers to the quality loader", async () => {
    const page = await QualityPage();
    expectAuthenticatedPage(page);
    expect(pageMocks.fetchQualitySummary).toHaveBeenCalledWith("director", authHeaders);
  });

  it("[PAGE-MERGE] forwards auth headers to the duplicate loader", async () => {
    const page = await MergePage();
    expectAuthenticatedPage(page);
    expect(pageMocks.fetchDuplicateClusters).toHaveBeenCalledWith("director", authHeaders);
  });

  it("[PAGE-SYNC] forwards auth headers to the synchronization loader", async () => {
    const page = await SyncPage();
    expectAuthenticatedPage(page);
    expect(pageMocks.fetchSyncJournal).toHaveBeenCalledWith("director", authHeaders);
  });

  it("[PAGE-CATEGORIES] forwards auth headers to the nomenclature loader", async () => {
    const page = await CategoriesPage();
    expectAuthenticatedPage(page);
    expect(pageMocks.fetchNomenclatureGroups).toHaveBeenCalledWith({ roles: "director" }, authHeaders);
  });

  it("[PAGE-RULES] forwards auth headers to the survivorship loader", async () => {
    const page = await RulesPage();
    expectAuthenticatedPage(page);
    expect(pageMocks.fetchSurvivorshipRules).toHaveBeenCalledWith(undefined, "director", authHeaders);
  });

  it("[PAGE-ADMIN] forwards auth headers to the approvals loader", async () => {
    const page = await AdminPage();
    expectAuthenticatedPage(page);
    expect(pageMocks.fetchPendingReferenceApprovals).toHaveBeenCalledWith("director", authHeaders);
  });

  it("[PAGE-RATES] forwards one auth header set to currency and VAT loaders", async () => {
    const page = await RatesPage();
    expectAuthenticatedPage(page);
    expect(pageMocks.fetchCurrencyRates).toHaveBeenCalledWith(undefined, "director", authHeaders);
    expect(pageMocks.fetchVatRates).toHaveBeenCalledWith(undefined, "director", authHeaders);
  });

  it("[PAGE-AI] forwards auth headers to the AI catalog loader", async () => {
    const page = await AiPage();
    expectAuthenticatedPage(page);
    expect(pageMocks.fetchAiCatalog).toHaveBeenCalledWith("director", authHeaders);
  });
});
