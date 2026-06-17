import { type ReactNode } from "react";
import { cn } from "@/lib/cn";

/** Состояние «пусто» — нет данных. */
export function EmptyState({ icon, title, hint, action }: { icon?: ReactNode; title: string; hint?: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-12 text-center">
      {icon && <div className="text-faint [&_svg]:size-8">{icon}</div>}
      <div className="text-sm font-semibold text-ink">{title}</div>
      {hint && <div className="max-w-sm text-[13px] text-muted">{hint}</div>}
      {action && <div className="mt-1">{action}</div>}
    </div>
  );
}

/** Состояние «загрузка» — скелетоны строк. */
export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("animate-pulse rounded-md bg-[#ECECF0]", className)} />;
}
export function LoadingRows({ rows = 4 }: { rows?: number }) {
  return (
    <div className="space-y-2 p-4">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="flex items-center gap-3">
          <Skeleton className="size-9 rounded-full" />
          <Skeleton className="h-3 flex-1" />
          <Skeleton className="h-3 w-16" />
        </div>
      ))}
    </div>
  );
}

/** Состояние «ошибка». */
export function ErrorState({ title = "Не удалось загрузить", hint, action }: { title?: string; hint?: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-12 text-center">
      <div className="text-2xl">⚠️</div>
      <div className="text-sm font-semibold text-red-600">{title}</div>
      {hint && <div className="max-w-sm text-[13px] text-muted">{hint}</div>}
      {action && <div className="mt-1">{action}</div>}
    </div>
  );
}
