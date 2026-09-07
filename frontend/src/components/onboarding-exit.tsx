"use client";

export function OnboardingExit() {
  return (
    <form action="/api/auth/logout" method="post">
      <button
        type="submit"
        className="mt-6 rounded-lg border border-line px-4 py-2 text-sm font-medium text-ink hover:border-accent"
      >
        Выйти
      </button>
    </form>
  );
}
