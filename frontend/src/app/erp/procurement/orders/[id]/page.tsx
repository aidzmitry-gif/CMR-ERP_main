import { notFound } from "next/navigation";

import { AppShell } from "@/components/app-shell";
import { ProcurementMachineEditor } from "@/components/erp/procurement-machine-editor";
import { fetchOrderServer } from "@/lib/procurement-machine";
import { currentRole } from "@/lib/role-server";

export default async function ProcurementOrderEditorPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const role = await currentRole();
  const order = await fetchOrderServer(Number(id), role);
  if (!order) notFound();

  return (
    <AppShell crumbs={["ERP", "Закупки", "Заказы в пути", order.number]}>
      <ProcurementMachineEditor initial={order} />
    </AppShell>
  );
}
