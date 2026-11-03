import { AppShell } from "@/components/app-shell";
import { SalesMailInbox } from "@/components/kanban/sales-mail-inbox";
import { currentRole } from "@/lib/role-server";

export default async function SalesMailPage() {
  const role = await currentRole();
  const canAssignOwner = ["admin", "director", "commercial"].includes(role);

  return (
    <AppShell crumbs={["CRM", "Почта отдела продаж"]}>
      <SalesMailInbox canAssignOwner={canAssignOwner} />
    </AppShell>
  );
}
