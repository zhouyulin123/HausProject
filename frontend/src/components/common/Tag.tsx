import type { ReactNode } from "react";

type Tone = "sage" | "terra" | "wood" | "cream" | "neutral";

const tones: Record<Tone, string> = {
  sage: "bg-sage-100 text-sage-700",
  terra: "bg-terra-100 text-terra-700",
  wood: "bg-wood-200/60 text-wood-700",
  cream: "bg-cream-200 text-stone-600",
  neutral: "bg-stone-100 text-stone-500",
};

export default function Tag({
  tone = "cream",
  children,
  className = "",
}: {
  tone?: Tone;
  children: ReactNode;
  className?: string;
}) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium ${tones[tone]} ${className}`}
    >
      {children}
    </span>
  );
}
