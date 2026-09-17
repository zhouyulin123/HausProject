import { useState } from "react";
import { Maximize2 } from "lucide-react";
import type { RoomSource } from "@/types/roomModel";

export default function RoomSourcePreview({ source }: { source: RoomSource | null }) {
  const [failedUrl, setFailedUrl] = useState<string | null>(null);
  if (!source) return null;
  const rawUrl = source.image_url;
  let imageUrl: string | null = null;
  if (rawUrl?.startsWith("/uploads/") && !rawUrl.includes("\\")) {
    const parsed = new URL(rawUrl, "https://local.invalid");
    if (parsed.pathname.startsWith("/uploads/")) imageUrl = parsed.pathname + parsed.search;
  }
  const title = source.file_name || "空间原图";
  return (
    <section className="mt-4" aria-label="空间原图">
      <div className="mb-2 flex min-w-0 items-center gap-2 text-xs">
        <span className="shrink-0 text-[#8d978e]">原图</span>
        <span className="truncate text-[#dce2da]" title={title}>{title}</span>
      </div>
      {imageUrl && failedUrl !== imageUrl ? (
        <a
          href={imageUrl}
          target="_blank"
          rel="noopener noreferrer"
          aria-label={`查看原图：${title}`}
          title="查看原图"
          className="group relative block aspect-[4/3] overflow-hidden rounded border border-white/15 bg-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#d5ff67]"
        >
          <img
            src={imageUrl}
            alt={title}
            className="h-full w-full object-contain"
            onError={() => setFailedUrl(imageUrl)}
          />
          <span className="absolute right-2 bottom-2 flex h-8 w-8 items-center justify-center rounded bg-black/70 text-white group-hover:bg-black/90">
            <Maximize2 className="h-4 w-4" aria-hidden="true" />
          </span>
        </a>
      ) : <p role="status" className="border border-white/10 p-3 text-xs text-[#b8c0b9]">原图暂不可用</p>}
    </section>
  );
}
