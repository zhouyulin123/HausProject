import type { LucideIcon } from "lucide-react";
import { Sprout } from "lucide-react";
import type { ReactNode } from "react";

export default function EmptyState({
  icon: Icon = Sprout,
  title,
  description,
  action,
}: {
  icon?: LucideIcon;
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center gap-4 rounded-3xl border border-dashed border-cream-300 bg-cream-100/50 px-6 py-16 text-center">
      <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-sage-100 text-sage-600">
        <Icon className="h-8 w-8" strokeWidth={1.5} />
      </div>
      <h3 className="text-lg font-semibold text-stone-700">{title}</h3>
      {description && (
        <p className="max-w-sm text-sm leading-relaxed text-stone-500">{description}</p>
      )}
      {action}
    </div>
  );
}
