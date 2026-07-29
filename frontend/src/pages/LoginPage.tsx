import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Home, Lamp, MessageSquare, Smartphone, Sofa } from "lucide-react";
import Button from "@/components/common/Button";

type Mode = "login" | "register";
type Channel = "email" | "phone";

const inputClass =
  "w-full rounded-xl border border-cream-300 bg-white/80 px-4 py-2.5 text-sm text-stone-700 placeholder:text-stone-300 outline-none transition-colors focus:border-sage-500 focus:ring-2 focus:ring-sage-100";

export default function LoginPage() {
  const navigate = useNavigate();
  const [mode, setMode] = useState<Mode>("login");
  const [channel, setChannel] = useState<Channel>("email");
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = () => {
    // mock 登录：无真实鉴权，模拟成功后回首页
    setSubmitting(true);
    setTimeout(() => navigate("/"), 800);
  };

  return (
    <div className="mx-auto grid max-w-5xl gap-10 px-4 py-12 sm:px-6 lg:grid-cols-2 lg:items-center lg:py-20">
      {/* 左侧插画卡片 */}
      <div className="relative hidden overflow-hidden rounded-3xl bg-gradient-to-br from-[#f7efe2] via-[#ecd9bd] to-[#cfae83] p-10 shadow-soft lg:block lg:min-h-[480px]">
        <div className="absolute top-10 right-12 opacity-60">
          <Lamp className="h-16 w-16 text-wood-700" strokeWidth={1.1} />
        </div>
        <div className="absolute bottom-16 left-10 opacity-70">
          <Sofa className="h-28 w-28 text-wood-700" strokeWidth={1} />
        </div>
        <div className="absolute right-0 bottom-0 left-0 h-10 bg-wood-500/20" />
        <div className="relative">
          <span className="flex h-11 w-11 items-center justify-center rounded-2xl bg-white/80 text-sage-700">
            <Home className="h-6 w-6" strokeWidth={1.6} />
          </span>
          <h2 className="mt-6 max-w-xs font-display text-2xl leading-relaxed font-semibold text-stone-800">
            你的家不只是好看，
            <br />
            还要适合每天的生活。
          </h2>
          <p className="mt-4 max-w-xs text-sm leading-relaxed text-stone-600/80">
            登录后可以保存方案、收藏家具，并在任何设备继续你的家装定制。
          </p>
        </div>
      </div>

      {/* 右侧表单 */}
      <div className="mx-auto w-full max-w-md">
        <h1 className="text-2xl font-semibold">
          {mode === "login" ? "欢迎回来" : "创建账号"}
        </h1>
        <p className="mt-2 text-sm text-stone-500">
          {mode === "login"
            ? "继续你的家装定制之旅。"
            : "注册后，AI 生成的方案会自动保存到你的账号。"}
        </p>

        {/* 登录方式切换 */}
        <div className="mt-6 flex rounded-xl bg-cream-100 p-1">
          {(
            [
              { key: "email", label: "邮箱登录", icon: MessageSquare },
              { key: "phone", label: "手机号登录", icon: Smartphone },
            ] as const
          ).map((item) => (
            <button
              key={item.key}
              type="button"
              onClick={() => setChannel(item.key)}
              className={`flex flex-1 items-center justify-center gap-1.5 rounded-lg py-2 text-sm font-medium transition-all ${
                channel === item.key
                  ? "bg-white text-stone-800 shadow-card"
                  : "text-stone-400 hover:text-stone-600"
              }`}
            >
              <item.icon className="h-4 w-4" />
              {item.label}
            </button>
          ))}
        </div>

        <form
          className="mt-5 space-y-4"
          onSubmit={(e) => {
            e.preventDefault();
            handleSubmit();
          }}
        >
          {channel === "email" ? (
            <input type="email" required placeholder="邮箱地址" className={inputClass} />
          ) : (
            <input type="tel" required placeholder="手机号" className={inputClass} />
          )}
          <input
            type="password"
            required
            placeholder={mode === "login" ? "密码" : "设置密码（至少 8 位）"}
            className={inputClass}
          />
          {mode === "login" && (
            <div className="text-right">
              <button
                type="button"
                className="text-xs text-stone-400 hover:text-sage-700"
                onClick={() => setMode("register")}
              >
                忘记密码？
              </button>
            </div>
          )}
          <Button type="submit" className="w-full" size="lg" disabled={submitting}>
            {submitting ? "正在进入..." : mode === "login" ? "登录" : "注册"}
          </Button>
        </form>

        {/* 第三方登录占位 */}
        <div className="mt-6">
          <div className="flex items-center gap-3 text-xs text-stone-300">
            <span className="h-px flex-1 bg-cream-200" />
            或使用以下方式
            <span className="h-px flex-1 bg-cream-200" />
          </div>
          <div className="mt-4 grid grid-cols-2 gap-3">
            <Button variant="outline" onClick={handleSubmit}>
              微信登录
            </Button>
            <Button variant="outline" onClick={handleSubmit}>
              手机验证码
            </Button>
          </div>
        </div>

        <p className="mt-8 text-center text-sm text-stone-500">
          {mode === "login" ? "还没有账号？" : "已有账号？"}
          <button
            type="button"
            className="ml-1 font-medium text-sage-700 hover:text-sage-600"
            onClick={() => setMode(mode === "login" ? "register" : "login")}
          >
            {mode === "login" ? "立即注册" : "去登录"}
          </button>
        </p>
      </div>
    </div>
  );
}
