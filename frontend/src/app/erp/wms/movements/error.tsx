"use client";

import { useRouter } from "next/navigation";
import { startTransition } from "react";

export default function MovementLoadError({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  const router = useRouter();
  return <div role="alert" className="m-6 rounded-xl border border-line bg-surface p-6">
    <h1 className="text-lg font-semibold">Не удалось загрузить журнал движений</h1>
    <p className="mt-2 text-sm text-muted">Проверьте вход в систему и доступ к юрлицу, затем повторите загрузку.</p>
    <button type="button" className="mt-4 rounded-lg border border-line px-4 py-2 text-sm" onClick={() => startTransition(() => { router.refresh(); reset(); })}>Повторить загрузку</button>
  </div>;
}
