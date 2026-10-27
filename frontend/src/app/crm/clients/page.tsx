import { AppShell } from "@/components/app-shell";
import { CrmDirectory } from "@/components/crm-directory";

export default function ClientsPage() {
  return <AppShell crumbs={["CRM", "Клиенты"]}><CrmDirectory kind="clients" /></AppShell>;
}
