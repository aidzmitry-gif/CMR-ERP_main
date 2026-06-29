import { AppShell } from "@/components/app-shell";
import { type StockThreshold, WmsStockView } from "@/components/erp/wms-stock-view";
import { currentRole } from "@/lib/role-server";
import { fetchStockMirrorServer } from "@/lib/wms-stock";

async function fetchThresholds(role?: string): Promise<StockThreshold[]> {
  try {
    const BASE = process.env.BACKEND_URL ?? "http://localhost:8000";
    const headers: Record<string, string> = role ? { "X-User-Roles": role } : {};
    const res = await fetch(`${BASE}/wms/thresholds`, { cache: "no-store", headers });
    if (!res.ok) return [];
    return (await res.json()) as StockThreshold[];
  } catch {
    return [];
  }
}

export default async function WmsStockPage() {
  const role = await currentRole();
  const [data, thresholds] = await Promise.all([
    fetchStockMirrorServer(role),
    fetchThresholds(role),
  ]);

  return (
    <AppShell crumbs={["ERP", "Склад", "Остатки"]}>
      <WmsStockView initial={data} thresholds={thresholds} />
    </AppShell>
  );
}
