import { forwardRef, type InputHTMLAttributes, type SelectHTMLAttributes, type TextareaHTMLAttributes, type ReactNode } from "react";
import { cn } from "@/lib/cn";

const field =
  "w-full rounded-[10px] border bg-surface px-3 py-2 text-sm text-ink outline-none transition-colors " +
  "placeholder:text-faint focus:border-accent focus:ring-[3px] focus:ring-accent/15 " +
  "disabled:bg-sunken disabled:text-faint disabled:cursor-not-allowed";
const normalCls = "border-line-strong";
const invalidCls = "border-[#F2C4C4] focus:border-red-400 focus:ring-red-400/15";

/** Текстовое поле. icon — иконка слева; invalid — ошибочное состояние. */
export interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  icon?: ReactNode;
  invalid?: boolean;
}
export const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ className, icon, invalid, ...props }, ref) =>
    icon ? (
      <div className="relative">
        <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-faint [&_svg]:size-4">{icon}</span>
        <input ref={ref} className={cn(field, invalid ? invalidCls : normalCls, "pl-9", className)} {...props} />
      </div>
    ) : (
      <input ref={ref} className={cn(field, invalid ? invalidCls : normalCls, className)} {...props} />
    ),
);
Input.displayName = "Input";

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement> & { invalid?: boolean }>(
  ({ className, invalid, ...props }, ref) => (
    <textarea ref={ref} className={cn(field, invalid ? invalidCls : normalCls, "min-h-[76px] resize-y", className)} {...props} />
  ),
);
Textarea.displayName = "Textarea";

export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement> & { invalid?: boolean }>(
  ({ className, invalid, children, ...props }, ref) => (
    <select ref={ref} className={cn(field, invalid ? invalidCls : normalCls, "cursor-pointer pr-8", className)} {...props}>
      {children}
    </select>
  ),
);
Select.displayName = "Select";

/** Обёртка поля: подпись + поле + подсказка/ошибка. */
export function Field({ label, hint, error, required, children }: {
  label?: string; hint?: string; error?: string; required?: boolean; children: ReactNode;
}) {
  return (
    <label className="block">
      {label && (
        <span className="mb-1 block text-[13px] font-medium text-ink">
          {label} {required && <span className="text-red-500">*</span>}
        </span>
      )}
      {children}
      {error ? (
        <span className="mt-1 block text-[12px] text-red-600">{error}</span>
      ) : hint ? (
        <span className="mt-1 block text-[12px] text-muted">{hint}</span>
      ) : null}
    </label>
  );
}
