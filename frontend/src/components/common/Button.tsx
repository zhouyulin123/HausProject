import type { ButtonHTMLAttributes, ReactNode } from "react";

type Variant = "primary" | "terra" | "secondary" | "outline" | "ghost";
type Size = "sm" | "md" | "lg";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  children: ReactNode;
}

const variantClasses: Record<Variant, string> = {
  primary:
    "bg-sage-600 text-white shadow-card hover:bg-sage-700 active:scale-[0.98]",
  terra: "bg-terra-500 text-white shadow-card hover:bg-terra-600 active:scale-[0.98]",
  secondary: "bg-cream-200 text-stone-700 hover:bg-cream-300 active:scale-[0.98]",
  outline:
    "border border-stone-300 bg-white/70 text-stone-700 hover:border-sage-500 hover:text-sage-700",
  ghost: "text-stone-600 hover:bg-cream-100 hover:text-stone-800",
};

const sizeClasses: Record<Size, string> = {
  sm: "rounded-lg px-3 py-1.5 text-sm gap-1",
  md: "rounded-xl px-5 py-2.5 text-sm gap-1.5",
  lg: "rounded-xl px-7 py-3 text-base gap-2",
};

export default function Button({
  variant = "primary",
  size = "md",
  className = "",
  children,
  ...rest
}: ButtonProps) {
  return (
    <button
      className={`inline-flex cursor-pointer items-center justify-center font-medium transition-all duration-200 disabled:pointer-events-none disabled:opacity-50 ${variantClasses[variant]} ${sizeClasses[size]} ${className}`}
      {...rest}
    >
      {children}
    </button>
  );
}
