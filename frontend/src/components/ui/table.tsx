import { type HTMLAttributes, type ThHTMLAttributes, type TdHTMLAttributes } from "react";
import { cn } from "@/lib/cn";

/**
 * Стилевые обёртки таблицы (Stripe/Notion). Логику сортировки/фильтров/пагинации
 * даёт TanStack Table при реальной интеграции — здесь только единый вид.
 */
export function Table({ className, ...props }: HTMLAttributes<HTMLTableElement>) {
  return <table className={cn("w-full border-collapse text-[13px]", className)} {...props} />;
}
export function Th({ className, ...props }: ThHTMLAttributes<HTMLTableCellElement>) {
  return (
    <th
      className={cn(
        "border-b border-line px-3 py-2.5 text-left text-[10px] font-semibold uppercase tracking-wide text-faint",
        className,
      )}
      {...props}
    />
  );
}
export function Td({ className, ...props }: TdHTMLAttributes<HTMLTableCellElement>) {
  return <td className={cn("border-b border-line px-3 py-2.5 text-ink", className)} {...props} />;
}
export function Tr({ className, ...props }: HTMLAttributes<HTMLTableRowElement>) {
  return <tr className={cn("transition-colors hover:bg-sunken", className)} {...props} />;
}
