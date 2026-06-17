import clsx, { type ClassValue } from "clsx";

/**
 * Склейка className-ов для компонентов ui.
 * На clsx без tailwind-merge — варианты задаём статическими map-ами классов
 * (см. components/ui/button.tsx), поэтому конфликтов Tailwind-утилит не возникает.
 * Если позже понадобится переопределять произвольные утилиты через проп `className`,
 * добавить tailwind-merge и обернуть тут — вызывающий код не изменится.
 */
export function cn(...inputs: ClassValue[]): string {
  return clsx(inputs);
}
