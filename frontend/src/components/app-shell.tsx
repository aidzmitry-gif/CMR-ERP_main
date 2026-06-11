import { cookies } from "next/headers";

import { Sidebar } from "@/components/sidebar";
import { Topbar } from "@/components/topbar";
import { DEFAULT_ROLE, fetchAccess, ROLE_COOKIE } from "@/lib/access";

export async function AppShell({
  crumbs,
  children,
}: {
  crumbs: string[];
  children: React.ReactNode;
}) {
  // текущая dev-роль из cookie (по умолчанию — полный доступ); матрицу берём с backend
  const role = (await cookies()).get(ROLE_COOKIE)?.value ?? DEFAULT_ROLE;
  const access = await fetchAccess(role);
  // backend недоступен → не прячем ничего (allowedSlugs=null), чтобы UI не «ослеп»
  const allowedSlugs = access ? access.matrix[role] ?? [] : null;
  const roles = access?.roles ?? [];
  const roleTitle = roles.find((r) => r.slug === role)?.title ?? role;

  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar allowedSlugs={allowedSlugs} role={role} roleTitle={roleTitle} roles={roles} />
      <div className="flex flex-1 flex-col overflow-hidden">
        <Topbar crumbs={crumbs} />
        <div className="flex flex-1 overflow-hidden">{children}</div>
      </div>
    </div>
  );
}
