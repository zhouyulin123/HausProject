import { useEffect, useRef, useState } from "react";
import { Send, RefreshCw, Check } from "lucide-react";
import {
  getHomeAgentHistory,
  getHomeAsset,
  requestHomeAgent,
} from "@/api/homeDesignApi";
import type {
  HomeAgentBudgetPreview,
  HomeAgentHistory,
  HomeAgentRequest,
  HomeAgentResponse,
  HomeAsset,
  HomeDesignDocument,
} from "@/types/homeDesign";
import type { HomeAssetLibrary } from "@/lib/homeAssetLibrary";
import HomeAgentAssetPicker from "./HomeAgentAssetPicker";

export const budgetStatusLabel = (
  status: HomeAgentBudgetPreview["budget_status"],
) =>
  ({
    within: "在本轮预算内",
    over: "超出本轮预算",
    incomplete: "仍有待报价，无法判断是否超预算",
    unknown: "未形成完整预算判断",
  })[status];
export function parsePendingAgentRequest(value: string): HomeAgentRequest | null {
  try {
    const request = JSON.parse(value) as Partial<HomeAgentRequest>;
    if (
      typeof request.client_turn_id !== "string" ||
      !request.client_turn_id.trim() ||
      typeof request.message !== "string" ||
      !request.message.trim() ||
      !Number.isSafeInteger(request.base_version) ||
      request.base_version! < 1 ||
      !Number.isSafeInteger(request.space_version) ||
      request.space_version! < 1 ||
      (request.region !== null &&
        (typeof request.region !== "string" ||
          !/^[A-Z0-9-]{2,32}$/.test(request.region))) ||
      (request.budget_max !== null &&
        (!Number.isSafeInteger(request.budget_max) || request.budget_max! <= 0)) ||
      !Array.isArray(request.allowed_asset_ids) ||
      request.allowed_asset_ids.length > 20 ||
      request.allowed_asset_ids.some(
        (id) => !Number.isSafeInteger(id) || id <= 0,
      ) ||
      new Set(request.allowed_asset_ids).size !== request.allowed_asset_ids.length
    )
      return null;
    return request as HomeAgentRequest;
  } catch {
    return null;
  }
}
export function proposalBlock(
  response: HomeAgentResponse,
  version: number,
  document: HomeDesignDocument,
  dirty: boolean,
  editable: boolean,
) {
  if (!editable) return "当前设计不可编辑";
  if (dirty) return "请先保存或撤销当前修改";
  if (
    response.outcome !== "proposal" ||
    !response.candidate_document ||
    response.validation?.valid !== true
  )
    return "该回复没有可应用的有效建议";
  if (
    response.base_version !== version ||
    response.space_version !== document.space_version ||
    response.candidate_document.space_version !== document.space_version
  )
    return "建议基准版本已过期，请重新提出需求";
  if (response.budget_preview.budget_status === "over")
    return "候选已超出本轮预算，请调整预算或设计要求";
  return "";
}
export function proposalDiff(
  current: HomeDesignDocument,
  candidate: HomeDesignDocument,
) {
  return (["objects", "surfaces"] as const).flatMap((kind) => {
    const old = new Map(current[kind].map((o) => [o.id, o])),
      next = new Map(candidate[kind].map((o) => [o.id, o]));
    return [...new Set([...old.keys(), ...next.keys()])].flatMap((id) => {
      const item = next.get(id) ?? old.get(id)!;
      return JSON.stringify(old.get(id)) === JSON.stringify(next.get(id))
        ? []
        : [
            `${!old.has(id) ? "新增" : !next.has(id) ? "移除" : "修改"}${kind === "objects" ? "物件" : "饰面"}：${"name" in item ? item.name : item.material.name}`,
          ];
    });
  });
}
export default function HomeAgentPanel({
  taskId,
  version,
  document,
  dirty,
  editable,
  assetLibrary,
  onApply,
  onApplied,
}: {
  taskId: number;
  version: number;
  document: HomeDesignDocument;
  dirty: boolean;
  editable: boolean;
  assetLibrary: HomeAssetLibrary;
  onApply: (d: HomeDesignDocument) => void;
  onApplied: () => void;
}) {
  const [text, setText] = useState(""),
    [region, setRegion] = useState(""),
    [budget, setBudget] = useState(""),
    [allowedAssets, setAllowedAssets] = useState<HomeAsset[]>([]),
    [evidenceAssets, setEvidenceAssets] = useState<Record<number, HomeAsset>>({}),
    [history, setHistory] = useState<HomeAgentHistory | null>(null),
    [response, setResponse] = useState<HomeAgentResponse | null>(null),
    [pending, setPending] = useState<HomeAgentRequest | null>(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const generation = useRef(0);
  const storageKey = `haus-home-agent-pending-${taskId}`;
  const load = async (more = false) => {
    const key = ++generation.current;
    setBusy(true);
    setError("");
    try {
      const r = await getHomeAgentHistory(
        taskId,
        more ? (history?.next_before_id ?? undefined) : undefined,
      );
      if (key === generation.current)
        setHistory(
          more && history ? { ...r, turns: [...history.turns, ...r.turns] } : r,
        );
    } catch {
      if (key === generation.current) setError("对话记录读取失败，请重试。");
    } finally {
      if (key === generation.current) setBusy(false);
    }
  };
  useEffect(() => {
    try {
      const raw = localStorage.getItem(storageKey);
      const cached = raw ? parsePendingAgentRequest(raw) : null;
      if (cached) setPending(cached);
      else if (raw) setError("本机待重试对话配置无效，未恢复该请求");
    } catch {
      setError("未能读取本机待重试对话");
    }
    void load();
    return () => {
      generation.current++;
    };
  }, [taskId]);
  useEffect(() => {
    const ids = response?.evidence.asset_refs.map((item) => item.asset_id) ?? [];
    let active = true;
    if (!ids.length) {
      setEvidenceAssets({});
      return () => {
        active = false;
      };
    }
    void Promise.allSettled(ids.map((id) => getHomeAsset(taskId, id))).then(
      (results) => {
        if (!active) return;
        const loaded: Record<number, HomeAsset> = {};
        results.forEach((result) => {
          if (result.status === "fulfilled") loaded[result.value.id] = result.value;
        });
        setEvidenceAssets(loaded);
      },
    );
    return () => {
      active = false;
    };
  }, [response, taskId]);
  const send = async () => {
    if (!version || !editable || dirty) return;
    const normalizedRegion = region.trim().toUpperCase();
    const parsedBudget = budget.trim() ? Number(budget) : null;
    if (normalizedRegion && !/^[A-Z0-9-]{2,32}$/.test(normalizedRegion)) {
      setError("地区代码需为 2–32 位大写字母、数字或连字符");
      return;
    }
    if (
      parsedBudget !== null &&
      (!Number.isSafeInteger(parsedBudget) || parsedBudget <= 0)
    ) {
      setError("预算上限必须是大于 0 的整数");
      return;
    }
    const payload = pending ?? {
      client_turn_id: crypto.randomUUID(),
      base_version: version,
      space_version: document.space_version,
      message: text.trim(),
      region: normalizedRegion || null,
      budget_max: parsedBudget,
      allowed_asset_ids: allowedAssets.map((asset) => asset.id),
    };
    if (!payload.message) return;
    const key = ++generation.current;
    setPending(payload);
    setBusy(true);
    setResponse(null);
    setError("");
    try {
      localStorage.setItem(storageKey, JSON.stringify(payload));
    } catch {
      setError("本机未能保存重试标识，请勿关闭当前面板");
    }
    try {
      const r = await requestHomeAgent(taskId, payload);
      if (key !== generation.current) return;
      setResponse(r);
      setPending(null);
      setText("");
      try {
        localStorage.removeItem(storageKey);
      } catch {
        /* 保留在内存的结果仍可检查。 */
      }
    } catch (e) {
      if (key === generation.current) {
        const detail = (e as { detail?: { message?: string } })?.detail;
        setError(detail?.message ?? "建议请求失败，请使用原请求重试。");
      }
    } finally {
      if (key === generation.current) setBusy(false);
    }
  };
  const block = response
    ? proposalBlock(response, version, document, dirty, editable)
    : "";
  const money = (value: number | null) =>
    value === null
      ? "待报价"
      : `${value.toLocaleString("zh-CN", { maximumFractionDigits: 2 })} CNY`;
  const configuredIds = pending?.allowed_asset_ids ?? allowedAssets.map((asset) => asset.id);
  return (
    <section className="hd-agent">
      <p>AI 建议 · 确认后进入草稿</p>
      {!version && <p>请先保存家装版本，再提出设计需求。</p>}
      {dirty && <p>有未保存修改，请先保存或撤销。</p>}
      <div className="hd-agent-config">
        <label>
          交付地区
          <input
            aria-label="AI 交付地区"
            value={pending?.region ?? region}
            placeholder="例如 CN-SH（可留空）"
            maxLength={32}
            disabled={busy || !!pending || !version}
            onChange={(event) => setRegion(event.target.value.toUpperCase())}
          />
        </label>
        <label>
          本轮预算上限（CNY）
          <input
            aria-label="AI 本轮预算上限"
            type="number"
            min={1}
            step={1}
            value={pending?.budget_max ?? budget}
            placeholder="可留空"
            disabled={busy || !!pending || !version}
            onChange={(event) => setBudget(event.target.value)}
          />
        </label>
      </div>
      <HomeAgentAssetPicker
        library={assetLibrary}
        selected={allowedAssets}
        disabled={busy || !!pending || !version || dirty || !editable}
        onChange={setAllowedAssets}
      />
      {!!pending && (
        <p role="status">
          待重试配置：{pending.region ?? "未指定地区"} · {pending.budget_max ? `预算 ${pending.budget_max.toLocaleString()} CNY` : "未指定预算"} · 授权家具 {configuredIds.length} 件
        </p>
      )}
      <label>
        设计需求
        <textarea
          rows={5}
          maxLength={4000}
          value={pending?.message ?? text}
          disabled={busy || !!pending || !version}
          onChange={(e) => setText(e.target.value)}
          placeholder="描述想调整的房间、物件或材料"
        />
      </label>
      <button
        disabled={
          busy || !editable || dirty || !version || (!pending && !text.trim())
        }
        onClick={() => void send()}
      >
        <Send size={16} />
        {pending ? "重试本轮" : "获取建议"}
      </button>
      {pending && !busy && (
        <button
          onClick={() => {
            setPending(null);
            try {
              localStorage.removeItem(storageKey);
            } catch {}
            setError("");
          }}
        >
          结束本轮，重新提问
        </button>
      )}
      {busy && <p role="status">正在处理…</p>}
      {error && <p role="alert">{error}</p>}
      {response && (
        <article>
          <p>{response.message}</p>
          {response.candidate_document && (
            <section className="hd-agent-review" aria-label="AI 候选审阅">
              <div>
                <h3>方案变化</h3>
                <ul>
                  {proposalDiff(document, response.candidate_document).map(
                    (line, i) => <li key={i}>{line}</li>,
                  )}
                </ul>
              </div>
              <div>
                <h3>采用家具及来源</h3>
                {!response.evidence.asset_refs.length && <p>本轮候选未引用冻结家具。</p>}
                {response.evidence.asset_refs.map((ref) => {
                  const asset = evidenceAssets[ref.asset_id];
                  return (
                    <article key={ref.asset_id}>
                      <strong>{asset?.name ?? `冻结家具 #${ref.asset_id}`}</strong>
                      <small>
                        {asset?.source_summary?.sku ? `SKU ${asset.source_summary.sku} · ` : ""}
                        来源 #{ref.source_id} / V{ref.source_version} · {asset?.source_summary?.verification_status ? `核验：${asset.source_summary.verification_status}` : "核验状态读取中或不可用"}
                      </small>
                    </article>
                  );
                })}
              </div>
              <div className={`hd-agent-budget is-${response.budget_preview.budget_status}`}>
                <h3>预算影响</h3>
                <strong>{budgetStatusLabel(response.budget_preview.budget_status)}</strong>
                <p>已知小计：{money(response.budget_preview.known_subtotal)}</p>
                <p>待报价：{response.budget_preview.pending_count} 项</p>
                <p>完整合计：{money(response.budget_preview.total_price)}</p>
                {response.budget_preview.budget_max !== null && <p>本轮上限：{money(response.budget_preview.budget_max)}</p>}
              </div>
              <div>
                <h3>约束与限制</h3>
                {!response.validation?.issues.length && !response.budget_preview.limitations.length && <p>未发现需要单独说明的问题。</p>}
                {response.validation?.issues.map((issue, index) => <p key={`issue-${index}`}>{issue.message}</p>)}
                {response.budget_preview.limitations.map((limitation) => <p key={limitation}>{limitation}</p>)}
              </div>
            </section>
          )}
          {block && <p role="status">{block}</p>}
          <button
            disabled={!!block || busy}
            onClick={() => {
              if (
                !proposalBlock(response, version, document, dirty, editable) &&
                response.candidate_document &&
                window.confirm(
                  "将这份建议应用到本机草稿？保存前不会修改服务端版本。",
                )
              )
                {
                  onApply(response.candidate_document);
                  onApplied();
                }
            }}
          >
            <Check size={16} />
            确认应用到草稿
          </button>
        </article>
      )}
      <h3>对话记录</h3>
      <button disabled={busy} onClick={() => void load()}>
        <RefreshCw size={16} />
        刷新记录
      </button>
      {history?.turns.map((turn) => (
        <article key={turn.turn_id}>
          <p>{turn.message}</p>
          <small>
            家装 V{turn.base_version} · 空间 V{turn.space_version} ·{" "}
            {turn.status === "running"
              ? "处理中"
              : turn.status === "failed"
                ? "失败"
                : "已回复"}
          </small>
          <p>{turn.response?.message ?? turn.error_code}</p>
          {turn.status === "completed" && turn.response && (
            <button disabled={busy} onClick={() => setResponse(turn.response)}>
              查看此轮建议
            </button>
          )}
        </article>
      ))}
      {history?.next_before_id && (
        <button disabled={busy} onClick={() => void load(true)}>
          更早对话
        </button>
      )}
    </section>
  );
}
