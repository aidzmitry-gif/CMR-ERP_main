import { AppShell } from "@/components/app-shell";
import { WmsBalances } from "@/components/erp/wms-balances";
import { fetchBalancesServer } from "@/lib/wms-ops";
import { currentRole } from "@/lib/role-server";

export default async function WmsBalancesPage() {
  const role = await currentRole();
  const data = await fetchBalancesServer(role);

  return (
    <AppShell crumbs={["ERP", "Склад", "Остаток из движений"]}>
      <WmsBalances initial={data} />
    </AppShell>
  );
}
