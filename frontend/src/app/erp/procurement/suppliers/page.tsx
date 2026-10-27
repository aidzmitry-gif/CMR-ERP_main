import { AppShell } from "@/components/app-shell";
import { ProcurementSuppliersTable } from "@/components/erp/procurement-suppliers-table";
import { ProcurementNav } from "@/components/erp/procurement-nav";
import { fetchSuppliersServer } from "@/lib/procurement-suppliers";
import { currentRole } from "@/lib/role-server";

export default async function ProcurementSuppliersPage() {
  const role = await currentRole();
  const suppliers = await fetchSuppliersServer(role);

  return (
    <AppShell crumbs={["ERP", "Закупки", "Поставщики"]}>
      <div className="flex min-w-0 flex-1 flex-col">
        <ProcurementNav />
        <ProcurementSuppliersTable initial={suppliers} />
      </div>
    </AppShell>
  );
}
