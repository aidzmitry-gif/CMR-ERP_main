import { AppShell } from "@/components/app-shell";
import { ClaimsPanel } from "@/components/erp/claims-panel";
import { fetchClaimsServer } from "@/lib/procurement-claims";
import { currentRole } from "@/lib/role-server";

export default async function ProcurementClaimsPage() {
  const role = await currentRole();
  const claims = await fetchClaimsServer(role);

  return (
    <AppShell crumbs={["ERP", "Закупки", "Претензии поставщикам"]}>
      <ClaimsPanel initial={claims} />
    </AppShell>
  );
}
