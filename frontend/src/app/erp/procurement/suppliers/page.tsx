import { AppShell } from "@/components/app-shell";
import { ProcurementSuppliersTable } from "@/components/erp/procurement-suppliers-table";
import { fetchSuppliersServer } from "@/lib/procurement-suppliers";
import { currentRole } from "@/lib/role-server";

export default async function ProcurementSuppliersPage() {
  const role = await currentRole();
  const suppliers = await fetchSuppliersServer(role);

  return (
    <AppShell crumbs={["ERP", "Закупки", "Поставщики"]}>
      <ProcurementSuppliersTable initial={suppliers} />
    </AppShell>
  );
}
