import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { AppShell } from "@/components/app-shell";
import { BrandingEditor } from "@/components/branding-editor";

/** Лого продавца для печатных форм (счёт-протокол/договор). */
export default function DealsBrandingPage() {
  return (
    <AppShell crumbs={["CRM", "Сделки", "Лого"]}>
      <main className="flex-1 overflow-y-auto bg-canvas text-ink">
        <div className="mx-auto max-w-[700px] px-[22px] pb-10 pt-[18px]">
          <Link
            href="/crm/deals"
            className="mb-3 inline-flex items-center gap-1 text-[12.5px] font-semibold text-muted hover:text-ink"
          >
            <ArrowLeft size={14} /> К доске
          </Link>
          <h1 className="mb-1 text-[19px] font-extrabold text-ink">Лого компании</h1>
          <p className="mb-4 text-[12.5px] text-muted">
            Логотип продавца, который печатается на счетах и договорах.
          </p>
          <BrandingEditor />
        </div>
      </main>
    </AppShell>
  );
}
