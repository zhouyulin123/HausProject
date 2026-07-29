import { useEffect, useState } from "react";
import { Check, ImagePlus, Loader2, Store } from "lucide-react";
import type { ShopSettings } from "@/api/designApi";
import {
  fetchShopSettings,
  saveShopSettings,
  uploadShopLogo,
} from "@/api/designApi";
import { useShopStore } from "@/store/useShopStore";
import Button from "@/components/common/Button";

const inputClass =
  "w-full rounded-xl border border-cream-300 bg-white/80 px-3.5 py-2 text-sm text-stone-700 placeholder:text-stone-300 outline-none transition-colors focus:border-sage-500 focus:ring-2 focus:ring-sage-100";

const empty: ShopSettings = {
  shop_name: "",
  phone: null,
  wechat: null,
  address: null,
  slogan: null,
  logo_url: null,
};

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label className="mb-1 block text-xs font-semibold text-stone-500">
        {label}
        {hint && <span className="ml-1.5 font-normal text-stone-400">{hint}</span>}
      </label>
      {children}
    </div>
  );
}

export default function ShopSettingsPanel() {
  const [shop, setShop] = useState<ShopSettings>(empty);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    void fetchShopSettings().then((s) => {
      setShop(s);
      setLoading(false);
    });
  }, []);

  const set = (patch: Partial<ShopSettings>) => setShop((s) => ({ ...s, ...patch }));

  const handleLogo = async (file: File) => {
    setUploading(true);
    try {
      set({ logo_url: await uploadShopLogo(file) });
    } finally {
      setUploading(false);
    }
  };

  const refreshGlobalShop = useShopStore((s) => s.load);

  const submit = async () => {
    if (!shop.shop_name.trim()) return;
    setSaving(true);
    try {
      await saveShopSettings(shop);
      await refreshGlobalShop(); // 立即刷新页头/页脚
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return <div className="mt-6 h-64 animate-pulse rounded-3xl bg-cream-100/70" />;
  }

  return (
    <div className="mt-6 max-w-2xl">
      <div className="rounded-3xl border border-cream-200 bg-white/80 p-6">
        <div className="flex items-center gap-2">
          <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-sage-100 text-sage-600">
            <Store className="h-4 w-4" />
          </span>
          <h3 className="text-base font-semibold text-stone-800">店铺信息</h3>
        </div>
        <p className="mt-1.5 text-xs text-stone-400">
          这里填写的信息会出现在提案 PDF 的页头与页脚，客户看到的就是你的品牌。
        </p>

        <div className="mt-5 space-y-4">
          <Field label="店铺名称 *">
            <input
              className={inputClass}
              value={shop.shop_name}
              onChange={(e) => set({ shop_name: e.target.value })}
              placeholder="例如 木言家居 · 全屋定制"
            />
          </Field>
          <Field label="品牌标语" hint="出现在页脚">
            <input
              className={inputClass}
              value={shop.slogan ?? ""}
              onChange={(e) => set({ slogan: e.target.value })}
              placeholder="例如 让每个家都有自己的样子"
            />
          </Field>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="联系电话">
              <input
                className={inputClass}
                value={shop.phone ?? ""}
                onChange={(e) => set({ phone: e.target.value })}
                placeholder="13800000000"
              />
            </Field>
            <Field label="微信号">
              <input
                className={inputClass}
                value={shop.wechat ?? ""}
                onChange={(e) => set({ wechat: e.target.value })}
                placeholder="myshop_vip"
              />
            </Field>
          </div>
          <Field label="门店地址">
            <input
              className={inputClass}
              value={shop.address ?? ""}
              onChange={(e) => set({ address: e.target.value })}
              placeholder="杭州市西湖区 xx 家居广场 3 楼"
            />
          </Field>
          <Field label="店铺 Logo" hint="建议方形，出现在提案页头">
            <div className="flex items-center gap-4">
              <div className="relative flex h-20 w-20 shrink-0 items-center justify-center overflow-hidden rounded-xl border border-cream-300 bg-cream-100">
                {shop.logo_url ? (
                  <img
                    src={shop.logo_url}
                    alt="logo"
                    className="h-full w-full object-contain"
                  />
                ) : (
                  <ImagePlus className="h-6 w-6 text-stone-300" />
                )}
                {uploading && (
                  <div className="absolute inset-0 flex items-center justify-center bg-white/70">
                    <Loader2 className="h-5 w-5 animate-spin text-sage-600" />
                  </div>
                )}
              </div>
              <label className="cursor-pointer rounded-xl border border-cream-300 bg-white/70 px-4 py-2 text-sm text-stone-600 hover:border-sage-400 hover:text-sage-700">
                上传 Logo
                <input
                  type="file"
                  accept="image/*"
                  className="hidden"
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    if (f) void handleLogo(f);
                  }}
                />
              </label>
            </div>
          </Field>
        </div>

        <div className="mt-6 flex items-center justify-end gap-3">
          {saved && (
            <span className="inline-flex items-center gap-1 text-sm text-sage-600">
              <Check className="h-4 w-4" />
              已保存，下次导出即生效
            </span>
          )}
          <Button onClick={() => void submit()} disabled={saving || !shop.shop_name.trim()}>
            {saving ? "保存中..." : "保存店铺信息"}
          </Button>
        </div>
      </div>
    </div>
  );
}
