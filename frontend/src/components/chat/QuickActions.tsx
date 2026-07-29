import { Wand2 } from "lucide-react";

/** 快捷指令条：点击直接作为消息发送 */
export default function QuickActions({
  commands,
  onSelect,
  disabled,
}: {
  commands: string[];
  onSelect: (command: string) => void;
  disabled?: boolean;
}) {
  return (
    <div className="flex flex-wrap gap-2">
      {commands.map((command) => (
        <button
          key={command}
          type="button"
          disabled={disabled}
          onClick={() => onSelect(command)}
          className="inline-flex items-center gap-1 rounded-full border border-cream-300 bg-white/80 px-3 py-1.5 text-xs font-medium text-stone-600 transition-all hover:border-terra-400 hover:text-terra-600 disabled:pointer-events-none disabled:opacity-50"
        >
          <Wand2 className="h-3 w-3" />
          {command}
        </button>
      ))}
    </div>
  );
}
