import { AppShell } from "@/components/app-shell";
import { WmsTasks } from "@/components/erp/wms-tasks";
import { currentRole } from "@/lib/role-server";
import { fetchTasksServer } from "@/lib/wms-warehouse";

export default async function WmsTasksPage() {
  const role = await currentRole();
  const tasks = await fetchTasksServer(role);
  return (
    <AppShell crumbs={["ERP", "Склад", "Задачи (подбор/размещение)"]}>
      <WmsTasks initial={tasks} />
    </AppShell>
  );
}
