import clsx from "clsx";
import { BarChart3 } from "lucide-react";
import type { Priority } from "@/lib/types";

const STYLES: Record<Priority, string> = {
  Высокий: "bg-red-50 text-red-600",
  Средний: "bg-amber-50 text-amber-600",
  Низкий: "bg-slate-100 text-slate-500",
};

export function PriorityBadge({
  priority,
  withIcon = false,
}: {
  priority: Priority;
  withIcon?: boolean;
}) {
  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs font-medium",
        STYLES[priority],
      )}
    >
      {withIcon && <BarChart3 size={12} />}
      {priority}
    </span>
  );
}
