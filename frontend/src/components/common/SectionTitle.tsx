interface SectionTitleProps {
  eyebrow?: string;
  title: string;
  description?: string;
  align?: "center" | "left";
}

export default function SectionTitle({
  eyebrow,
  title,
  description,
  align = "center",
}: SectionTitleProps) {
  const alignClass = align === "center" ? "text-center items-center" : "text-left items-start";
  return (
    <div className={`flex flex-col gap-3 ${alignClass}`}>
      {eyebrow && (
        <span className="inline-flex w-fit items-center gap-1.5 rounded-full bg-sage-100 px-3 py-1 text-xs font-medium tracking-wide text-sage-700">
          {eyebrow}
        </span>
      )}
      <h2 className="text-2xl font-semibold sm:text-3xl">{title}</h2>
      {description && (
        <p className="max-w-2xl text-sm leading-relaxed text-stone-500 sm:text-base">
          {description}
        </p>
      )}
    </div>
  );
}
