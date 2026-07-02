import { AppShell } from "@/components/app-shell";
import { MarketingSeoProjectView } from "@/components/erp/marketing-seo-project-view";

export default async function MarketingSeoProjectPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;

  return (
    <AppShell crumbs={["ERP", "Маркетинг", "SEO / GEO", "Проект"]}>
      <MarketingSeoProjectView projectId={id} />
    </AppShell>
  );
}
