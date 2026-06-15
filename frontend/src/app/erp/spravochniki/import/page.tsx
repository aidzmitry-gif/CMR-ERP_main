import { AppShell } from "@/components/app-shell";
import { SpravImport } from "@/components/erp/spravochniki/sprav-import";

export default function SpravImportPage() {
  return (
    <AppShell crumbs={["ERP", "Справочники", "Импорт из 1С"]}>
      <SpravImport />
    </AppShell>
  );
}
