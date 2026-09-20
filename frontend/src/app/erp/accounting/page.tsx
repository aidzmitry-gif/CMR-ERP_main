import { AppShell } from "@/components/app-shell";
import { AccountingView } from "@/components/erp/accounting-view";

export default async function AccountingPage({ searchParams }: { searchParams?: Promise<{ org?: string | string[] }> }) {
  const params = searchParams ? await searchParams : {};
  const suggestedOrg = typeof params.org === "string" ? params.org : undefined;
  return <AppShell crumbs={["ERP", "Бухгалтерия"]}><AccountingView suggestedOrg={suggestedOrg} /></AppShell>;
}
