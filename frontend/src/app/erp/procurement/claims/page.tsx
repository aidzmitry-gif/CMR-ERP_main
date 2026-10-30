import { AppShell } from "@/components/app-shell";
import { ProcurementScopedClaims } from "@/components/erp/procurement-scoped-claims";

export default function ProcurementClaimsPage() {
  return (
    <AppShell crumbs={["ERP", "Закупки", "Претензии поставщикам"]}>
      <div className="flex min-w-0 flex-1 flex-col">

        <ProcurementScopedClaims />
      </div>
    </AppShell>
  );
}
