import { AppShell } from "@/components/app-shell";
import { OfficeLegalView } from "@/components/erp/office-legal-view";

export default function OfficeContractsPage() {
  return (
    <AppShell crumbs={["ERP", "Офис-менеджер", "Договоры"]}>
      <OfficeLegalView />
    </AppShell>
  );
}
