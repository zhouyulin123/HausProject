import { useEffect, useState } from "react";
import PageTitle from "@/components/common/PageTitle";
import EmptyState from "@/components/common/EmptyState";
import { listUsers, updateUserRole, type AdminUser } from "@/api/adminApi";
import { roleLabel } from "@/store/useAuthStore";

export default function AdminUsersPage() {
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const reload = async () => {
    setLoading(true);
    try {
      setUsers(await listUsers());
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载用户失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void reload();
  }, []);

  const changeRole = async (
    userId: number,
    role: "customer" | "factory" | "admin",
  ) => {
    setError("");
    try {
      await updateUserRole(userId, role);
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : "更新角色失败");
    }
  };

  return (
    <div className="mx-auto max-w-6xl px-4 py-10 sm:px-6">
      <PageTitle
        title="用户管理"
        description="管理注册用户的角色：普通用户、厂家、管理员。（仅管理员可访问）"
      />

      {error && (
        <p className="mt-4 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-600">
          {error}
        </p>
      )}

      {loading ? (
        <p className="mt-6 text-center text-sm text-stone-400">加载中...</p>
      ) : users.length === 0 ? (
        <div className="mt-6">
          <EmptyState title="暂无用户" description="用户注册后会出现在这里。" />
        </div>
      ) : (
        <div className="mt-6 overflow-hidden rounded-2xl border border-cream-200">
          <table className="w-full text-sm">
            <thead className="bg-cream-100 text-left text-xs text-stone-500">
              <tr>
                <th className="px-4 py-2.5 font-medium">手机号</th>
                <th className="px-4 py-2.5 font-medium">昵称</th>
                <th className="px-4 py-2.5 font-medium">当前角色</th>
                <th className="px-4 py-2.5 font-medium">注册时间</th>
                <th className="px-4 py-2.5 font-medium">切换角色</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id} className="border-t border-cream-100">
                  <td className="px-4 py-2.5 font-medium text-stone-700">
                    {u.phone ?? "-"}
                  </td>
                  <td className="px-4 py-2.5 text-stone-500">
                    {u.nickname ?? "-"}
                  </td>
                  <td className="px-4 py-2.5">
                    <span className="rounded bg-sage-100 px-1.5 py-0.5 text-xs text-sage-700">
                      {roleLabel(u.role)}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 text-stone-500">
                    {u.created_at ?? "-"}
                  </td>
                  <td className="px-4 py-2.5">
                    <select
                      value={u.role}
                      onChange={(e) =>
                        void changeRole(
                          u.id,
                          e.target.value as "customer" | "factory" | "admin",
                        )
                      }
                      className="rounded-lg border border-cream-300 bg-white px-2 py-1 text-sm text-stone-700 outline-none focus:border-sage-500"
                    >
                      <option value="customer">用户</option>
                      <option value="factory">厂家</option>
                      <option value="admin">管理员</option>
                    </select>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
