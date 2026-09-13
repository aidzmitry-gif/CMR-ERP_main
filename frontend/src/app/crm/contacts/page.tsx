import { AppShell } from "@/components/app-shell";
import { CrmDirectory } from "@/components/crm-directory";

export default function ContactsPage() {
  return <AppShell crumbs={["CRM", "Контакты"]}><CrmDirectory kind="contacts" /></AppShell>;
}
