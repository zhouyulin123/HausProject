import { useEffect } from "react";
import { Outlet, ScrollRestoration } from "react-router-dom";
import Header from "./Header";
import Footer from "./Footer";
import { useShopStore } from "@/store/useShopStore";

export default function Layout() {
  const loadShop = useShopStore((s) => s.load);

  useEffect(() => {
    void loadShop();
  }, [loadShop]);

  return (
    <div className="flex min-h-screen flex-col">
      <Header />
      <main className="flex-1">
        <Outlet />
      </main>
      <Footer />
      <ScrollRestoration />
    </div>
  );
}
