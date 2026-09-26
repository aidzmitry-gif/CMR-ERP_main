import Link from "next/link";
import { AppShell } from "@/components/app-shell";
import { TasksWorkspace } from "./tasks-workspace";

export default function TasksPage() {
  return <AppShell crumbs={["CRM", "Задачи"]}>
    <main className="flex-1 overflow-y-auto bg-canvas px-[22px] py-[18px] text-ink">
      <div className="mx-auto max-w-[1000px]">
        <Link href="/crm/deals" className="text-sm text-accent-ink underline">К сделкам</Link>
        <h1 className="mt-3 text-xl font-bold">Задачи CRM</h1>
        <TasksWorkspace />
      </div>
    </main>
  </AppShell>;
}
