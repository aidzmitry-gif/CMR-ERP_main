"use client";

import { useRouter } from "next/navigation";

export function OnboardingExit() {
  const router = useRouter();

  async function logout() {
    await fetch("/api/auth/logout", { method: "POST" });
    router.replace("/login");
    router.refresh();
  }

  return (
    <button
      type="button"
      onClick={() => void logout()}
      className="mt-6 rounded-lg border border-line px-4 py-2 text-sm font-medium text-ink hover:border-accent"
    >
      Выйти
    </button>
  );
}
