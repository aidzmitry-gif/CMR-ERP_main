import { AppShell } from "@/components/app-shell";
import { RegularClients } from "@/components/regular/regular-clients";

export default function Page() {
  return (
    <AppShell crumbs={["CRM", "Постоянные клиенты"]}>
      <RegularClients />
    </AppShell>
  );
}
