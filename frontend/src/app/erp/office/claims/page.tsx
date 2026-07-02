import { AppShell } from "@/components/app-shell";
import { OfficeClaimsView } from "@/components/erp/office-claims-view";

export default function OfficeClaimsPage() {
  return (
    <AppShell crumbs={["ERP", "Офис-менеджер", "Претензии"]}>
      <OfficeClaimsView />
    </AppShell>
  );
}
