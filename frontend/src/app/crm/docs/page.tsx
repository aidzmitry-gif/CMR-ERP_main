import { AppShell } from "@/components/app-shell";
import { DocsRegistry } from "@/components/docs/docs-registry";

export default function Page() {
  return (
    <AppShell crumbs={["CRM", "Реестр документов"]}>
      <DocsRegistry />
    </AppShell>
  );
}
