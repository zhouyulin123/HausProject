import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { Home, Lamp, ShieldCheck, Smartphone, Sofa } from "lucide-react";
import Button from "@/components/common/Button";
import { useAuthStore } from "@/store/useAuthStore";
import { sendSmsCode } from "@/api/authApi";

const inputClass =
  "w-full rounded-xl border border-cream-300 bg-white/80 px-4 py-2.5 text-sm text-stone-700 placeholder:text-stone-300 outline-none transition-colors focus:border-sage-500 focus:ring-2 focus:ring-sage-100";

export default function LoginPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const login = useAuthStore((s) => s.login);
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [countdown, setCountdown] = useState(0);
  const [sending, setSending] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [devCode, setDevCode] = useState("");

  useEffect(() => {
    if (countdown <= 0) return;
    const timer = setTimeout(() => setCountdown((c) => c - 1), 1000);
    return () => clearTimeout(timer);
  }, [countdown]);

  const handleSend = async () => {
    if (!/^1\d{10}$/.test(phone)) {
      setError("请输入正确的 11 位手机号");
      return;
    }
    setError("");
    setSending(true);
    try {
      const res = await sendSmsCode(phone);
      setDevCode(res.dev_code ?? "");
      setCountdown(60);
    } catch (e) {
      setError(e instanceof Error ? e.message : "验证码发送失败，请稍后重试");
    } finally {
      setSending(false);
    }
  };

  const handleSubmit = async () => {
    if (!/^1\d{10}$/.test(phone)) {
      setError("请输入正确的 11 位手机号");
      return;
    }
    if (!code) {
      setError("请输入验证码");
      return;
    }
    setError("");
    setSubmitting(true);
    try {
      const user = await login(phone, code);
      const from = (
        location.state as { from?: { pathname?: string } } | null
      )?.from?.pathname;
      if (from) {
        navigate(from, { replace: true });
      } else {
        navigate(
          user.role === "factory" || user.role === "admin" ? "/workspace" : "/",
        );
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "登录失败，请稍后重试");
    } finally {
      setSubmitting(false);
    }
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
            手机号验证码即可登录，方案自动保存，还能发布装修意向给厂家报价。
          </p>
        </div>
      </div>

      {/* 右侧表单 */}
      <div className="mx-auto w-full max-w-md">
        <h1 className="text-2xl font-semibold">登录 / 注册</h1>
        <p className="mt-2 text-sm text-stone-500">
          未注册的手机号验证后将自动创建账号。
        </p>

        <form
          className="mt-6 space-y-4"
          onSubmit={(e) => {
            e.preventDefault();
            void handleSubmit();
          }}
        >
          <div>
            <label className="mb-1.5 block text-xs font-medium text-stone-500">
              手机号
            </label>
            <div className="relative">
              <Smartphone className="absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2 text-stone-300" />
              <input
                type="tel"
                inputMode="numeric"
                maxLength={11}
                placeholder="请输入 11 位手机号"
                className={`${inputClass} pl-9`}
                value={phone}
                onChange={(e) => setPhone(e.target.value.replace(/\D/g, ""))}
              />
            </div>
          </div>

          <div>
            <label className="mb-1.5 block text-xs font-medium text-stone-500">
              验证码
            </label>
            <div className="flex gap-2">
              <input
                type="text"
                inputMode="numeric"
                maxLength={6}
                placeholder="6 位验证码"
                className={inputClass}
                value={code}
                onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
              />
              <Button
                type="button"
                variant="outline"
                className="shrink-0"
                onClick={() => void handleSend()}
                disabled={sending || countdown > 0}
              >
                {countdown > 0 ? `${countdown}s` : sending ? "发送中" : "获取验证码"}
              </Button>
            </div>
          </div>

          {devCode && (
            <p className="flex items-center gap-1.5 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-700">
              <ShieldCheck className="h-4 w-4" />
              开发环境验证码：{devCode}
            </p>
          )}

          {error && <p className="text-xs text-red-600">{error}</p>}

          <Button type="submit" className="w-full" size="lg" disabled={submitting}>
            {submitting ? "正在进入..." : "登录 / 注册"}
          </Button>
        </form>

        <p className="mt-6 text-center text-xs text-stone-400">
          登录即代表同意《用户协议》与《隐私政策》。厂家账号由管理员开通。
        </p>
      </div>
    </div>
  );
}
