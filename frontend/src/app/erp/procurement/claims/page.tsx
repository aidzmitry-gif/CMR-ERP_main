import { AppShell } from "@/components/app-shell";
import { ProcurementScopedClaims } from "@/components/erp/procurement-scoped-claims";
import { ProcurementNav } from "@/components/erp/procurement-nav";

export default function ProcurementClaimsPage() {
  return (
    <AppShell crumbs={["ERP", "Закупки", "Претензии поставщикам"]}>
      <div className="flex min-w-0 flex-1 flex-col">
        <ProcurementNav />
        <ProcurementScopedClaims />
      </div>
    </AppShell>
  );
}
