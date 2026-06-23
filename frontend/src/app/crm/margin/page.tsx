import { AppShell } from "@/components/app-shell";
import { MarginByMonth } from "@/components/margin/margin-by-month";

export default function Page() {
  return (
    <AppShell crumbs={["CRM", "Валовая прибыль"]}>
      <MarginByMonth />
    </AppShell>
  );
}
