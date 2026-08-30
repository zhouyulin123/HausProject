import { Home, RefreshCw } from "lucide-react";
import { Link, isRouteErrorResponse, useRouteError } from "react-router-dom";
import { isTransientLazyImportError } from "@/lib/lazyImport";

export default function RouteErrorPage() {
  const error = useRouteError();
  const isMissing = isRouteErrorResponse(error) && error.status === 404;
  const isModuleFailure = isTransientLazyImportError(error);

  const title = isMissing
    ? "这个页面不存在"
    : isModuleFailure
      ? "页面资源暂时没有加载成功"
      : "页面暂时无法显示";
  const description = isMissing
    ? "你访问的地址可能已经调整，可以返回首页继续浏览。"
    : "服务可能正在更新或网络发生了短暂波动，请重新加载页面。";

  return (
    <main className="flex min-h-screen flex-col bg-[#0b0f0c] px-6 text-[#f1efe7]">
      <div className="mx-auto flex w-full max-w-6xl flex-1 flex-col justify-center py-16">
        <p className="font-mono text-[11px] tracking-[0.18em] text-[#d5ff67]">
          HAUS / 页面恢复
        </p>
        <h1 className="mt-5 max-w-3xl font-display text-4xl leading-tight tracking-normal text-[#f1efe7] sm:text-6xl">
          {title}
        </h1>
        <p className="mt-6 max-w-xl text-sm leading-7 text-[#aab4aa] sm:text-base">
          {description}
        </p>
        <div className="mt-9 flex flex-wrap gap-3">
          {!isMissing && (
            <button
              type="button"
              onClick={() => window.location.reload()}
              className="inline-flex items-center gap-2 rounded-md bg-[#d5ff67] px-5 py-3 text-sm font-semibold text-[#11150f] transition-colors hover:bg-[#e2ff91]"
            >
              <RefreshCw className="h-4 w-4" />
              重新加载
            </button>
          )}
          <Link
            to="/"
            className="inline-flex items-center gap-2 rounded-md border border-white/18 px-5 py-3 text-sm text-[#d8ddd7] transition-colors hover:border-white/35 hover:text-white"
          >
            <Home className="h-4 w-4" />
            返回首页
          </Link>
        </div>
      </div>
    </main>
  );
}
