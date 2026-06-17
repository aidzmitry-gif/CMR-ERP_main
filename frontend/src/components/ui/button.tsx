import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";
import { cn } from "@/lib/cn";

export type ButtonVariant =
  | "primary" // главное действие зоны (индиго)
  | "secondary" // равнозначная альтернатива (обводка)
  | "ghost" // третьестепенное
  | "money" // денежное действие — приоритет №1 (зелёный): доплата, закрытие
  | "violet" // AI-действия
  | "danger" // необратимое/опасное
  | "call" // телефония: позвонить (зелёная трубка)
  | "hangup"; // телефония: завершить/отменить (красная)

export type ButtonSize = "sm" | "md" | "lg";

const base =
  "inline-flex items-center justify-center gap-1.5 font-semibold leading-none whitespace-nowrap " +
  "border border-transparent transition-all duration-150 cursor-pointer " +
  "focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-accent/35 " +
  "disabled:opacity-45 disabled:cursor-not-allowed disabled:shadow-none active:translate-y-px";

const variants: Record<ButtonVariant, string> = {
  primary:
    "bg-accent text-white shadow-[0_1px_2px_rgba(75,69,214,.4),0_2px_8px_rgba(99,91,255,.28),inset_0_1px_0_rgba(255,255,255,.22)] hover:bg-accent-ink",
  secondary:
    "bg-surface text-ink border-line-strong shadow-[0_1px_1px_rgba(20,20,40,.04)] hover:bg-sunken hover:border-[#CFCFD8]",
  ghost: "text-muted hover:bg-[#EFEFF3] hover:text-ink",
  money:
    "bg-money text-white shadow-[0_1px_2px_rgba(15,157,88,.3),0_2px_8px_rgba(15,157,88,.22)] hover:brightness-105",
  violet:
    "bg-[#7C3AED] text-white shadow-[0_1px_2px_rgba(109,40,217,.35),0_2px_8px_rgba(124,58,237,.24)] hover:brightness-105",
  danger: "bg-surface text-[#DC2626] border-[#F2C4C4] hover:bg-[#FCEAEA]",
  call: "bg-money text-white shadow-[0_1px_2px_rgba(15,157,88,.3)] hover:brightness-105",
  hangup: "bg-[#DC2626] text-white hover:brightness-105",
};

const sizes: Record<ButtonSize, string> = {
  sm: "text-xs px-3 py-[7px] rounded-lg [&_svg]:size-[13px]",
  md: "text-[13px] px-4 py-[10px] rounded-[10px] [&_svg]:size-[15px]",
  lg: "text-[14.5px] font-bold px-[22px] py-[13px] rounded-[11px] [&_svg]:size-4",
};

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** Иконка слева (lucide). Размер задаётся по size автоматически. */
  icon?: ReactNode;
  /** На всю ширину контейнера (для мобильной раскладки/CTA). */
  block?: boolean;
}

/**
 * Единый компонент кнопки дизайн-системы. Заменяет инлайн-классы по проекту.
 * Вид/иерархия — см. frontend/DESIGN.md. Варианты служат приоритетам платформы:
 * money/call — деньги (№1), danger/hangup отделяют необратимое (№2).
 */
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ variant = "primary", size = "md", icon, block, className, children, type = "button", ...props }, ref) => (
    <button
      ref={ref}
      type={type}
      className={cn(base, variants[variant], sizes[size], block && "w-full", className)}
      {...props}
    >
      {icon}
      {children}
    </button>
  ),
);
Button.displayName = "Button";
