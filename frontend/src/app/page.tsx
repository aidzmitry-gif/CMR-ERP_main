import { redirect } from "next/navigation";

import { defaultPathForRole } from "@/lib/app-role";
import { currentRole, currentUserName } from "@/lib/role-server";

export default async function Home() {
  if (!(await currentUserName())) redirect("/login");
  redirect(defaultPathForRole(await currentRole()));
}
