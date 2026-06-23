import { AppShell } from "@/components/app-shell";
import { CallsWorkspace } from "@/components/calls/calls-workspace";

export default function CallsPage() {
  return (
    <AppShell crumbs={["CRM", "Звонки"]}>
      <CallsWorkspace />
    </AppShell>
  );
}
