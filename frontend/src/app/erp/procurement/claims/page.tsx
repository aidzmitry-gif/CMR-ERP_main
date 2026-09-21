import { AppShell } from "@/components/app-shell";
import { ClaimsPanel } from "@/components/erp/claims-panel";
import { ProcurementNav } from "@/components/erp/procurement-nav";
import { fetchClaimsServer } from "@/lib/procurement-claims";
import { currentRole } from "@/lib/role-server";

export default async function ProcurementClaimsPage() {
  const role = await currentRole();
  const claims = await fetchClaimsServer(role);

  return (
    <AppShell crumbs={["ERP", "Закупки", "Претензии поставщикам"]}>
      <div className="flex min-w-0 flex-1 flex-col">
        <ProcurementNav />
        <ClaimsPanel initial={claims} />
      </div>
    </AppShell>
  );
}
