import { Link } from "react-router-dom";
import { Home } from "lucide-react";
import { useShopStore } from "@/store/useShopStore";

const columns = [
  {
    title: "产品",
    links: [
      { label: "AI 定制", to: "/customize" },
      { label: "风格案例", to: "/styles" },
      { label: "家具推荐", to: "/furniture" },
    ],
  },
  {
    title: "我的",
    links: [
      { label: "我的方案", to: "/my-designs" },
      { label: "登录 / 注册", to: "/login" },
    ],
  },
];

export default function Footer() {
  const shop = useShopStore((s) => s.shop);
  const shopName = shop?.shop_name || "AI 家装定制助手";
  const slogan = shop?.slogan || "让每个家都有自己的样子";

  return (
    <footer className="mt-auto border-t border-cream-200 bg-cream-100/60">
      <div className="mx-auto grid max-w-7xl gap-10 px-4 py-12 sm:px-6 md:grid-cols-[1.5fr_1fr_1fr]">
        <div>
          <div className="flex items-center gap-2">
            {shop?.logo_url ? (
              <img
                src={shop.logo_url}
                alt={shopName}
                className="h-8 w-8 rounded-lg object-cover"
              />
            ) : (
              <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-sage-600 text-white">
                <Home className="h-4 w-4" />
              </span>
            )}
            <span className="font-display text-base font-semibold text-stone-800">
              {shopName}
            </span>
          </div>
          <p className="mt-4 max-w-sm text-sm leading-relaxed text-stone-500">
            不用懂设计，也能得到一套清晰的装修方案。从户型、预算到生活习惯，AI
            会综合生成更适合你的家装建议。
          </p>
        </div>
        {columns.map((col) => (
          <div key={col.title}>
            <h4 className="text-sm font-semibold text-stone-700">{col.title}</h4>
            <ul className="mt-4 space-y-2.5">
              {col.links.map((link) => (
                <li key={link.to + link.label}>
                  <Link
                    to={link.to}
                    className="text-sm text-stone-500 transition-colors hover:text-sage-700"
                  >
                    {link.label}
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
      <div className="border-t border-cream-200 py-5 text-center text-xs text-stone-400">
        © 2026 {shopName} · {slogan}
      </div>
    </footer>
  );
}
