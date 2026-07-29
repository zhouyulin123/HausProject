import type { LucideIcon } from "lucide-react";

export default function FeatureCard({
  icon: Icon,
  title,
  description,
}: {
  icon: LucideIcon;
  title: string;
  description: string;
}) {
  return (
    <div className="group rounded-3xl border border-cream-200 bg-white/70 p-6 transition-all duration-300 hover:-translate-y-1 hover:shadow-soft">
      <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-sage-100 text-sage-600 transition-colors group-hover:bg-sage-600 group-hover:text-white">
        <Icon className="h-6 w-6" strokeWidth={1.6} />
      </div>
      <h3 className="mt-4 text-base font-semibold text-stone-800">{title}</h3>
      <p className="mt-2 text-sm leading-relaxed text-stone-500">{description}</p>
    </div>
  );
}
