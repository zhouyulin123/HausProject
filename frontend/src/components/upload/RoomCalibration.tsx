import { useState } from "react";
import { Ruler } from "lucide-react";
import Button from "@/components/common/Button";
import type { ImageAnalysis } from "@/types/requirement";
import type { RoomModel } from "@/types/roomModel";
import { calibrateRoomModel } from "@/api/designApi";

const inputClass =
  "w-full rounded-xl border border-cream-200 bg-white px-3 py-2 text-sm text-stone-700 outline-none focus:border-terra-300";

export default function RoomCalibration({
  analysis,
  onCalibrated,
}: {
  analysis: ImageAnalysis;
  onCalibrated: (roomModel: RoomModel) => void;
}) {
  const room = analysis.roomModel?.rooms[0];
  const [width, setWidth] = useState(room?.widthM ? String(room.widthM) : "");
  const [depth, setDepth] = useState(room?.depthM ? String(room.depthM) : "");
  const [ceiling, setCeiling] = useState(
    room?.ceilingHeight ? String(room.ceilingHeight) : "",
  );
  const [status, setStatus] = useState<"idle" | "saving" | "saved" | "error">(
    "idle",
  );

  if (!analysis.imageId || !room) return null;

  const canSubmit =
    Number.parseFloat(width) > 0 && Number.parseFloat(depth) > 0;

  const submit = async () => {
    if (!canSubmit || !analysis.imageId) return;
    setStatus("saving");
    try {
      const calibrated = await calibrateRoomModel(analysis.imageId, {
        roomId: room.id,
        widthM: Number.parseFloat(width),
        depthM: Number.parseFloat(depth),
        ceilingHeightM: ceiling
          ? Number.parseFloat(ceiling)
          : undefined,
      });
      setStatus("saved");
      onCalibrated(calibrated);
    } catch {
      setStatus("error");
    }
  };

  return (
    <div className="mt-3 rounded-2xl border border-cream-200 bg-white/70 p-4">
      <div className="flex items-center gap-1.5 text-sm font-semibold text-stone-700">
        <Ruler className="h-4 w-4 text-wood-600" />
        确认「{room.name}」真实尺寸
      </div>
      <p className="mt-1 text-xs text-stone-400">
        AI 无法精确测量，请填写实际尺寸（米），用于生成更准确的 3D 布局。
      </p>

      <div className="mt-3 grid grid-cols-3 gap-3">
        <label className="block">
          <span className="mb-1 block text-xs text-stone-500">宽（米）</span>
          <input
            type="number"
            inputMode="decimal"
            min={0.5}
            max={50}
            step={0.1}
            value={width}
            onChange={(e) => setWidth(e.target.value)}
            placeholder="如 4.6"
            className={inputClass}
          />
        </label>
        <label className="block">
          <span className="mb-1 block text-xs text-stone-500">深（米）</span>
          <input
            type="number"
            inputMode="decimal"
            min={0.5}
            max={50}
            step={0.1}
            value={depth}
            onChange={(e) => setDepth(e.target.value)}
            placeholder="如 5.6"
            className={inputClass}
          />
        </label>
        <label className="block">
          <span className="mb-1 block text-xs text-stone-500">层高（米，可选）</span>
          <input
            type="number"
            inputMode="decimal"
            min={1.8}
            max={8}
            step={0.1}
            value={ceiling}
            onChange={(e) => setCeiling(e.target.value)}
            placeholder="2.8"
            className={inputClass}
          />
        </label>
      </div>

      <div className="mt-3 flex items-center justify-end gap-2">
        {status === "saved" && (
          <span className="text-xs text-sage-600">已保存，将用于 3D 布局</span>
        )}
        {status === "error" && (
          <span className="text-xs text-terra-600">保存失败，请重试</span>
        )}
        <Button
          onClick={submit}
          disabled={!canSubmit || status === "saving"}
          size="sm"
        >
          {status === "saving" ? "保存中…" : "确认尺寸"}
        </Button>
      </div>
    </div>
  );
}
