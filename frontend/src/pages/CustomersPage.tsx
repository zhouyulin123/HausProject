import { useEffect, useState } from "react";
import { Link2, Phone, Plus, Search, UserRound } from "lucide-react";
import {
  attachCurrentTaskToCustomer,
  createCustomer,
  getCurrentTaskId,
  listCustomers,
} from "@/api/designApi";
import type { CustomerRecord } from "@/api/designApi";
import PageTitle from "@/components/common/PageTitle";
import EmptyState from "@/components/common/EmptyState";
import Button from "@/components/common/Button";
import Tag from "@/components/common/Tag";

const inputClass =
  "rounded-xl border border-cream-300 bg-white/80 px-4 py-2.5 text-sm text-stone-700 placeholder:text-stone-300 outline-none transition-colors focus:border-sage-500 focus:ring-2 focus:ring-sage-100";

export default function CustomersPage() {
  const [customers, setCustomers] = useState<CustomerRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [keyword, setKeyword] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ name: "", phone: "", note: "" });
  const [attachedId, setAttachedId] = useState<number | null>(null);

  const hasCurrentTask = getCurrentTaskId() !== null;

  const load = async (q?: string) => {
    try {
      setCustomers(await listCustomers(q));
      setFailed(false);
    } catch {
      setFailed(true);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const submit = async () => {
    if (!form.name.trim()) return;
    await createCustomer({
      name: form.name.trim(),
      phone: form.phone.trim() || undefined,
      note: form.note.trim() || undefined,
    });
    setForm({ name: "", phone: "", note: "" });
    setShowForm(false);
    void load(keyword || undefined);
  };

  const attach = async (customerId: number) => {
    const ok = await attachCurrentTaskToCustomer(customerId).catch(() => false);
    if (ok) {
      setAttachedId(customerId);
      setTimeout(() => setAttachedId(null), 2500);
      void load(keyword || undefined);
    }
  };

  return (
    <div className="mx-auto max-w-5xl px-4 py-10 sm:px-6">
      <PageTitle
        title="客户跟单"
        description="记录到店客户与他们的方案，随时继续跟进。（内部使用）"
        extra={
          <Button onClick={() => setShowForm((v) => !v)}>
            <Plus className="h-4 w-4" />
            新增客户
          </Button>
        }
      />

      {showForm && (
        <div className="mt-6 flex flex-col gap-3 rounded-3xl border border-cream-200 bg-white/80 p-5 sm:flex-row sm:items-end">
          <div className="flex-1">
            <label className="mb-1.5 block text-xs font-semibold text-stone-500">
              客户姓名 *
            </label>
            <input
              className={`${inputClass} w-full`}
              value={form.name}
              placeholder="例如 王女士"
              onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
            />
          </div>
          <div className="flex-1">
            <label className="mb-1.5 block text-xs font-semibold text-stone-500">
              联系电话
            </label>
            <input
              className={`${inputClass} w-full`}
              value={form.phone}
              placeholder="选填"
              onChange={(e) => setForm((f) => ({ ...f, phone: e.target.value }))}
            />
          </div>
          <div className="flex-[2]">
            <label className="mb-1.5 block text-xs font-semibold text-stone-500">
              备注
            </label>
            <input
              className={`${inputClass} w-full`}
              value={form.note}
              placeholder="例如 三室两厅旧改，预算 15 万，周末再来"
              onChange={(e) => setForm((f) => ({ ...f, note: e.target.value }))}
            />
          </div>
          <Button onClick={() => void submit()} disabled={!form.name.trim()}>
            保存
          </Button>
        </div>
      )}

      <div className="relative mt-6 sm:w-80">
        <Search className="absolute top-1/2 left-3.5 h-4 w-4 -translate-y-1/2 text-stone-300" />
        <input
          type="text"
          value={keyword}
          onChange={(e) => {
            setKeyword(e.target.value);
            void load(e.target.value || undefined);
          }}
          placeholder="搜索姓名或电话"
          className={`${inputClass} w-full pl-10`}
        />
      </div>

      {loading ? (
        <div className="mt-6 space-y-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="h-20 animate-pulse rounded-3xl bg-cream-100/70" />
          ))}
        </div>
      ) : failed ? (
        <div className="mt-8">
          <EmptyState
            title="客户数据加载失败"
            description="请确认后端服务已启动（端口 8081）。"
            action={<Button onClick={() => void load()}>重试</Button>}
          />
        </div>
      ) : customers.length === 0 ? (
        <div className="mt-8">
          <EmptyState
            icon={UserRound}
            title="还没有客户记录"
            description="接待第一位客户时，点右上角「新增客户」记一笔。"
          />
        </div>
      ) : (
        <div className="mt-6 space-y-3">
          {customers.map((c) => (
            <div
              key={c.id}
              className="flex flex-col gap-3 rounded-3xl border border-cream-200 bg-white/80 p-5 sm:flex-row sm:items-center sm:justify-between"
            >
              <div className="flex items-center gap-4">
                <span className="flex h-11 w-11 items-center justify-center rounded-2xl bg-sage-100 text-sage-600">
                  <UserRound className="h-5 w-5" />
                </span>
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-semibold text-stone-800">{c.name}</span>
                    {c.phone && (
                      <span className="inline-flex items-center gap-1 text-xs text-stone-400">
                        <Phone className="h-3 w-3" />
                        {c.phone}
                      </span>
                    )}
                    <Tag tone={c.task_count > 0 ? "sage" : "cream"}>
                      {c.task_count > 0 ? `${c.task_count} 个方案` : "暂无方案"}
                    </Tag>
                  </div>
                  <p className="mt-1 text-xs text-stone-400">
                    {c.created_at} 建档{c.note ? ` · ${c.note}` : ""}
                  </p>
                </div>
              </div>
              {hasCurrentTask && (
                <Button
                  variant={attachedId === c.id ? "secondary" : "outline"}
                  size="sm"
                  onClick={() => void attach(c.id)}
                >
                  <Link2 className="h-4 w-4" />
                  {attachedId === c.id ? "已关联" : "关联当前方案"}
                </Button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
