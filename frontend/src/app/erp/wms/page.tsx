import Link from "next/link";
import { AppShell } from "@/components/app-shell";
import { ScopedWmsDashboard } from "@/components/erp/wms-dashboard";

export default function WmsPage() {
  return <AppShell crumbs={["ERP", "Склад"]}>
    <Link className="mb-4 inline-block text-accent underline" href="/erp/wms/settings">Настроить режим WMS по складам</Link>
    <ScopedWmsDashboard />
  </AppShell>;
}
