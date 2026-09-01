import { useRef, useState } from "react";
import type { DragEvent } from "react";
import { FileText, ImagePlus, UploadCloud } from "lucide-react";

/** 拖拽上传面板；仅做前端预览，分析由父组件通过 onFile 触发 */
export default function UploadPanel({ onFile }: { onFile: (file: File) => void }) {
  const [dragging, setDragging] = useState(false);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [isPdf, setIsPdf] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleFile = (file: File) => {
    setIsPdf(file.type === "application/pdf");
    setPreviewUrl(file.type.startsWith("image/") ? URL.createObjectURL(file) : null);
    onFile(file);
  };

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const file = e.dataTransfer.files[0];
    if (file) handleFile(file);
  };

  return (
    <div>
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        onClick={() => inputRef.current?.click()}
        className={`home-plan-grid relative flex min-h-[360px] cursor-pointer flex-col items-center justify-center gap-4 overflow-hidden rounded-[1.6rem] border px-6 py-14 text-center transition-all ${
          dragging
            ? "border-[#5f7350] bg-[#dfe8d7]"
            : "border-[#1d241f]/20 bg-[#deddd3] hover:border-[#5f7350] hover:bg-[#e6e5dc]"
        }`}
      >
        <span className="absolute top-4 left-5 font-mono text-[9px] tracking-[0.18em] text-[#6e796f] uppercase">Input / Spatial source</span>
        <span className="absolute top-4 right-5 flex items-center gap-2 font-mono text-[9px] tracking-[0.16em] text-[#5f7350] uppercase"><span className="h-1.5 w-1.5 animate-pulse rounded-full bg-[#5f7350]" />Scanner ready</span>
        {previewUrl ? (
          <img
            src={previewUrl}
            alt="上传预览"
            className="max-h-64 rounded-2xl object-contain shadow-card"
          />
        ) : isPdf ? (
          <div className="flex h-24 w-24 items-center justify-center rounded-2xl bg-terra-100 text-terra-600">
            <FileText className="h-10 w-10" strokeWidth={1.4} />
          </div>
        ) : (
          <div className="flex h-16 w-16 items-center justify-center rounded-full bg-[#182019] text-[#d5ff67] shadow-[0_0_0_10px_rgb(24_32_25/.07)]">
            <UploadCloud className="h-8 w-8" strokeWidth={1.5} />
          </div>
        )}
        <div>
          <p className="text-sm font-semibold text-stone-700">
            {previewUrl || isPdf ? "重新上传其他文件" : "拖拽文件到这里，或点击上传"}
          </p>
          <p className="mt-1.5 flex items-center justify-center gap-1 text-xs text-stone-400">
            <ImagePlus className="h-3.5 w-3.5" />
            支持 JPG / PNG / PDF，单个文件不超过 20MB
          </p>
        </div>
        <input
          ref={inputRef}
          type="file"
          accept="image/jpeg,image/png,application/pdf"
          className="hidden"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) handleFile(file);
            e.target.value = "";
          }}
        />
      </div>
    </div>
  );
}
