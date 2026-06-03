import { AppShell } from "@/components/app-shell";
import { SettingsView } from "@/components/erp/settings-view";

export default function SettingsPage() {
  return (
    <AppShell crumbs={["ERP", "IT и настройки"]}>
      <SettingsView />
    </AppShell>
  );
}
