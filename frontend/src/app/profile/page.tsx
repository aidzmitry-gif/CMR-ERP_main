import { AppShell } from "@/components/app-shell";
import { EmployeeProfileForm } from "@/components/employee-profile-form";

export default function ProfilePage() {
  return <AppShell crumbs={["ERP", "Моя HR-карточка"]}>
    <main className="mx-auto w-full max-w-3xl p-4 sm:p-8"><EmployeeProfileForm /></main>
  </AppShell>;
}
