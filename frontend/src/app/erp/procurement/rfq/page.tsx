import { AppShell } from "@/components/app-shell";
import { ProcurementRfqView } from "@/components/erp/procurement-rfq-view";
import { fetchRfqsServer } from "@/lib/procurement-rfq";
import { currentRole } from "@/lib/role-server";

export default async function ProcurementRfqPage() {
  const role = await currentRole();
  const rfqs = await fetchRfqsServer(role);

  return (
    <AppShell crumbs={["ERP", "Закупки", "Тендер / RFQ"]}>
      <ProcurementRfqView initial={rfqs} />
    </AppShell>
  );
}
