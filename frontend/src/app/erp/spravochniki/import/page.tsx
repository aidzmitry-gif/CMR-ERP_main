import { AppShell } from "@/components/app-shell";
import { SpravImportShell } from "@/components/erp/spravochniki/sprav-import-shell";

export default function SpravImportPage() {
  return (
    <AppShell crumbs={["ERP", "Справочники", "Импорт"]}>
      <SpravImportShell />
    </AppShell>
  );
}
