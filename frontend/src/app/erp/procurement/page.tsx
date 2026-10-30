import Link from "next/link";
import { Plus } from "lucide-react";
import { AppShell } from "@/components/app-shell";
import { ProcurementKanban } from "@/components/erp/procurement-kanban";

export default async function ProcurementPage({ searchParams }: { searchParams?: Promise<{ org?: string | string[] }> }) {
  const params = searchParams ? await searchParams : {};
  const suggestedOrg = typeof params.org === "string" ? params.org : undefined;
  return <AppShell crumbs={["Закупки", "Воронка закупок"]} headerActions={<Link href="/erp/procurement/planning" className="ml-2 inline-flex items-center gap-2 rounded-[11px] bg-accent px-4 py-2.5 text-[13px] font-bold text-white shadow-sm hover:bg-accent-ink"><Plus size={16} aria-hidden />Создать закупку</Link>}><div className="flex min-w-0 flex-1 flex-col"><ProcurementKanban suggestedOrg={suggestedOrg} /></div></AppShell>;
}
