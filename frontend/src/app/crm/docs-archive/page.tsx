import { AppShell } from "@/components/app-shell";
import { DocsArchive } from "@/components/docs/docs-archive";

export default function Page() {
  return (
    <AppShell crumbs={["CRM", "Архив документов"]}>
      <DocsArchive />
    </AppShell>
  );
}
