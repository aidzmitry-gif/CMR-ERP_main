import { AppShell } from "@/components/app-shell";
import { OfficeDocumentBoard } from "@/components/erp/office-document-board";

export default function OfficePage() {
  return (
    <AppShell crumbs={["ERP", "Офис-менеджер"]}>
      <OfficeDocumentBoard />
    </AppShell>
  );
}
