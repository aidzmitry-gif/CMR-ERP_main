import { forwardRef, type HTMLAttributes } from "react";
import { cn } from "@/lib/cn";

/**
 * Карточка/секция — базовая поверхность экрана (Stripe/Notion вид).
 * Тёплый фон, тонкая граница, мягкая многослойная тень. См. frontend/DESIGN.md.
 */
export const Card = forwardRef<HTMLDivElement, HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div ref={ref} className={cn("rounded-2xl border border-line bg-surface shadow-card", className)} {...props} />
  ),
);
Card.displayName = "Card";

/** Шапка карточки: заголовок слева, действие/мета справа. */
export const CardHeader = forwardRef<HTMLDivElement, HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div
      ref={ref}
      className={cn("flex items-center gap-2 border-b border-line px-[18px] py-3 text-[13.5px] font-bold", className)}
      {...props}
    />
  ),
);
CardHeader.displayName = "CardHeader";

/** Тело карточки. */
export const CardBody = forwardRef<HTMLDivElement, HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div ref={ref} className={cn("px-[18px] py-[14px]", className)} {...props} />
  ),
);
CardBody.displayName = "CardBody";
