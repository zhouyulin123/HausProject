import { useEffect, useRef, useState } from "react";
import { fetchUploadedImageContent } from "@/api/designApi";

/** 会话只进入请求头；临时 Blob 不写入项目缓存。 */
export function usePrivateImage(imageId: number | null | undefined) {
  const activeUrl = useRef<string|null>(null);
  const [state, setState] = useState<{id: number; url: string | null; failed: boolean} | null>(null);
  useEffect(() => {
    if (!imageId || !Number.isSafeInteger(imageId) || imageId < 1) return;
    const controller = new AbortController();
    let temporaryUrl: string | null = null;
    void fetchUploadedImageContent(imageId, controller.signal).then(blob => {
      if (controller.signal.aborted) return;
      temporaryUrl = URL.createObjectURL(blob);
      activeUrl.current = temporaryUrl;
      setState({id: imageId, url: temporaryUrl, failed: false});
    }).catch(() => {
      if (!controller.signal.aborted) setState({id: imageId, url: null, failed: true});
    });
    return () => {
      controller.abort();
      activeUrl.current = null;
      if (temporaryUrl) URL.revokeObjectURL(temporaryUrl);
    };
  }, [imageId]);
  return state && state.id === imageId && (state.failed || state.url === activeUrl.current) ? state : {url: null, failed: false};
}
