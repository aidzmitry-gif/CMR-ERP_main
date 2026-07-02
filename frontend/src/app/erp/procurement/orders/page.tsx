import { AppShell } from "@/components/app-shell";
import { ProcurementOpenOrdersTable } from "@/components/erp/procurement-open-orders-table";
import { fetchOpenOrdersServer } from "@/lib/procurement-orders";
import { currentRole } from "@/lib/role-server";

export default async function ProcurementOpenOrdersPage() {
  const role = await currentRole();
  const orders = await fetchOpenOrdersServer(role);

  return (
    <AppShell crumbs={["ERP", "Закупки", "Заказы в пути"]}>
      <ProcurementOpenOrdersTable initial={orders} />
    </AppShell>
  );
}
