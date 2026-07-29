import { useEffect, useState } from "react";
import { Link, NavLink, useLocation } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { Home, Menu, Sparkles, X } from "lucide-react";
import Button from "@/components/common/Button";
import { useShopStore } from "@/store/useShopStore";

const navItems = [
  { label: "首页", to: "/" },
  { label: "AI 定制", to: "/customize" },
  { label: "风格案例", to: "/styles" },
  { label: "家具推荐", to: "/furniture" },
  { label: "我的方案", to: "/my-designs" },
  { label: "客户跟单", to: "/customers" },
  { label: "商品库", to: "/admin" },
];

export default function Header() {
  const [scrolled, setScrolled] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const location = useLocation();
  const shop = useShopStore((s) => s.shop);
  const shopName = shop?.shop_name || "AI 家装定制助手";

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8);
    window.addEventListener("scroll", onScroll);
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  // 路由变化时收起移动端菜单
  useEffect(() => setMenuOpen(false), [location.pathname]);

  return (
    <header
      className={`sticky top-0 z-40 border-b transition-all duration-300 ${
        scrolled
          ? "border-cream-200 bg-cream-50/90 shadow-card backdrop-blur-md"
          : "border-transparent bg-cream-50/70 backdrop-blur-sm"
      }`}
    >
      <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-4 sm:px-6">
        <Link to="/" className="flex items-center gap-2">
          {shop?.logo_url ? (
            <img
              src={shop.logo_url}
              alt={shopName}
              className="h-9 w-9 rounded-xl object-cover"
            />
          ) : (
            <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-sage-600 text-white">
              <Home className="h-5 w-5" strokeWidth={1.8} />
            </span>
          )}
          <span className="font-display text-lg font-semibold text-stone-800">
            {shopName}
          </span>
        </Link>

        <nav className="hidden items-center gap-1 lg:flex">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                `rounded-lg px-3.5 py-2 text-sm font-medium transition-colors ${
                  isActive
                    ? "bg-sage-100 text-sage-700"
                    : "text-stone-600 hover:bg-cream-100 hover:text-stone-800"
                }`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>

        <div className="hidden items-center gap-2 lg:flex">
          <Link to="/login">
            <Button variant="ghost" size="sm">
              登录 / 注册
            </Button>
          </Link>
          <Link to="/customize">
            <Button size="sm">
              <Sparkles className="h-4 w-4" />
              开始定制
            </Button>
          </Link>
        </div>

        <button
          className="flex h-10 w-10 items-center justify-center rounded-xl text-stone-600 hover:bg-cream-100 lg:hidden"
          onClick={() => setMenuOpen((v) => !v)}
          aria-label="打开菜单"
        >
          {menuOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
        </button>
      </div>

      <AnimatePresence>
        {menuOpen && (
          <motion.nav
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.25 }}
            className="overflow-hidden border-t border-cream-200 bg-cream-50 lg:hidden"
          >
            <div className="flex flex-col gap-1 px-4 py-3">
              {navItems.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  className={({ isActive }) =>
                    `rounded-lg px-3 py-2.5 text-sm font-medium ${
                      isActive
                        ? "bg-sage-100 text-sage-700"
                        : "text-stone-600 hover:bg-cream-100"
                    }`
                  }
                >
                  {item.label}
                </NavLink>
              ))}
              <div className="mt-2 flex gap-2 border-t border-cream-200 pt-3">
                <Link to="/login" className="flex-1">
                  <Button variant="outline" className="w-full">
                    登录 / 注册
                  </Button>
                </Link>
                <Link to="/customize" className="flex-1">
                  <Button className="w-full">开始定制</Button>
                </Link>
              </div>
            </div>
          </motion.nav>
        )}
      </AnimatePresence>
    </header>
  );
}
