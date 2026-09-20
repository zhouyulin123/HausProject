import { Suspense, useEffect } from "react";
import { Outlet, ScrollRestoration, useLocation } from "react-router-dom";
import Header from "./Header";
import Footer from "./Footer";
import { useShopStore } from "@/store/useShopStore";
import { useAuthStore } from "@/store/useAuthStore";
import { isFullScreenDesignPath } from "@/lib/designWorkspaceRouting";

export default function Layout() {
  const { pathname } = useLocation();
  const spatialWorkspace = isFullScreenDesignPath(pathname);
  const loadShop = useShopStore((s) => s.load);
  const initAuth = useAuthStore((s) => s.init);

  useEffect(() => {
    void loadShop();
    void initAuth();
  }, [loadShop, initAuth]);

  return (
    <div className="flex min-h-screen flex-col">
      <Header />
      <main className="flex-1">
        <Suspense
          fallback={
            <div className="flex min-h-[55vh] items-center justify-center bg-[#0b0f0c] text-sm text-[#aab4aa]">
              正在加载设计工作区…
            </div>
          }
        >
          <Outlet />
        </Suspense>
      </main>
      {!spatialWorkspace && <Footer />}
      <ScrollRestoration />
    </div>
  );
}
