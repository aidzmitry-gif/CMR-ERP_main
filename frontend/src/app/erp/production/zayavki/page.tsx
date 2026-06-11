import { AppShell } from "@/components/app-shell";
import { ZayavkiTable } from "@/components/erp/zayavki-table";
import { fetchBomsServer, fetchNormsServer, fetchOrdersServer } from "@/lib/production-zayavki";
import { currentRole } from "@/lib/role-server";

export default async function ProductionZayavkiPage() {
  const role = await currentRole();
  const [orders, norms, boms] = await Promise.all([
    fetchOrdersServer(role),
    fetchNormsServer(role),
    fetchBomsServer(role),
  ]);

  return (
    <AppShell crumbs={["ERP", "Производство", "Заявки на сборку"]}>
      <ZayavkiTable initialOrders={orders} initialNorms={norms} initialBoms={boms} />
    </AppShell>
  );
}
