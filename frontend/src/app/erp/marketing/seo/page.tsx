import { AppShell } from "@/components/app-shell";
import { MarketingSeoView } from "@/components/erp/marketing-seo-view";

export default function MarketingSeoPage() {
  return (
    <AppShell crumbs={["ERP", "Маркетинг", "SEO / GEO"]}>
      <MarketingSeoView />
    </AppShell>
  );
}
