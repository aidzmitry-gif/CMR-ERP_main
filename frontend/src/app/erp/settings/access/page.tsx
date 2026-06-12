import { AppShell } from "@/components/app-shell";
import { AccessAdmin } from "@/components/erp/access-admin";

export default function AccessAdminPage() {
  return (
    <AppShell crumbs={["ERP", "IT и настройки", "Управление доступом"]}>
      <AccessAdmin />
    </AppShell>
  );
}
