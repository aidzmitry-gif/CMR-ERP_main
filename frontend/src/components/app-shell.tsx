import { Sidebar } from "@/components/sidebar";
import { Topbar } from "@/components/topbar";

export function AppShell({
  crumbs,
  children,
}: {
  crumbs: string[];
  children: React.ReactNode;
}) {
  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar />
      <div className="flex flex-1 flex-col overflow-hidden">
        <Topbar crumbs={crumbs} />
        <div className="flex flex-1 overflow-hidden">{children}</div>
      </div>
    </div>
  );
}
