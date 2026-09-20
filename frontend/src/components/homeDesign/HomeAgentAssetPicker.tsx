import { useEffect, useSyncExternalStore } from "react";
import { Plus, RefreshCw, X } from "lucide-react";
import type { HomeAsset } from "@/types/homeDesign";
import type { HomeAssetLibrary } from "@/lib/homeAssetLibrary";

export function updateAllowedAssets(
  current: number[],
  assetId: number,
  allowed: boolean,
) {
  if (!allowed) return current.filter((id) => id !== assetId);
  if (current.includes(assetId)) return current;
  if (current.length >= 20) throw Error("最多允许 AI 使用 20 件家具");
  return [...current, assetId];
}

const sourceText = (asset: HomeAsset) => {
  const summary = asset.source_summary ?? {};
  return [
    summary.sku ? `SKU ${summary.sku}` : asset.kind === "product" ? `商品 #${asset.source_id}` : `作品 #${asset.source_id}`,
    `来源 V${asset.source_version}`,
    summary.verification_status ? `核验：${summary.verification_status}` : "核验状态未知",
  ].join(" · ");
};

export default function HomeAgentAssetPicker({
  library,
  selected,
  disabled,
  onChange,
}: {
  library: HomeAssetLibrary;
  selected: HomeAsset[];
  disabled: boolean;
  onChange: (assets: HomeAsset[]) => void;
}) {
  const state = useSyncExternalStore(library.subscribe, library.getSnapshot);
  useEffect(() => {
    void library.load();
  }, [library]);
  const selectedIds = selected.map((asset) => asset.id);
  const add = (asset: HomeAsset) => {
    const nextIds = updateAllowedAssets(selectedIds, asset.id, true);
    if (nextIds === selectedIds) return;
    onChange([...selected, asset]);
  };
  return (
    <section className="hd-agent-assets" aria-labelledby="agent-assets-title">
      <div className="hd-agent-section-title">
        <div>
          <h3 id="agent-assets-title">允许 AI 使用的家具</h3>
          <small>只有你明确加入的冻结版本才会交给 AI，最多 20 件。</small>
        </div>
        <button
          aria-label="刷新 AI 家具来源"
          title="刷新 AI 家具来源"
          disabled={disabled || state.loading}
          onClick={() => void library.load()}
        >
          <RefreshCw size={15} />
        </button>
      </div>
      {!!selected.length && (
        <div className="hd-agent-allowed-list">
          {selected.map((asset) => (
            <article key={asset.id}>
              <div>
                <strong>{asset.name}</strong>
                <small>{sourceText(asset)}</small>
              </div>
              <button
                aria-label={`不再允许 AI 使用${asset.name}`}
                title="移出 AI 白名单"
                disabled={disabled}
                onClick={() => onChange(selected.filter((item) => item.id !== asset.id))}
              >
                <X size={15} />
              </button>
            </article>
          ))}
        </div>
      )}
      {!selected.length && <p>尚未授权家具；AI 仍可调整已有物件与饰面。</p>}
      <div className="hd-segment">
        <button disabled={disabled} aria-pressed={state.kind === "product"} onClick={() => void library.switchKind("product")}>商品家具</button>
        <button disabled={disabled} aria-pressed={state.kind === "open_geometry"} onClick={() => void library.switchKind("open_geometry")}>本任务作品</button>
      </div>
      <div className="hd-agent-source-list">
        {state.options.map((option) => (
          <button
            key={`${option.kind}-${option.source_id}-${option.source_version}`}
            disabled={disabled || state.freezing || !option.available}
            onClick={() => void library.freeze(option)}
          >
            <strong>{option.name}</strong>
            <small>
              {option.source_summary?.sku ? `SKU ${option.source_summary.sku} · ` : ""}
              {option.source_version ? `来源 V${option.source_version}` : "无可用版本"}
              {option.source_summary?.verification_status ? ` · 核验：${option.source_summary.verification_status}` : " · 核验状态未知"}
            </small>
            {!option.available && <small>{option.reason ?? "当前不可用"}</small>}
          </button>
        ))}
      </div>
      {state.loading && <p role="status">正在读取家具来源…</p>}
      {state.error && <p role="alert">{state.error}</p>}
      {state.pending && !state.freezing && <button disabled={disabled} onClick={() => void library.retry()}>重试冻结原版本</button>}
      {state.next !== null && <button disabled={disabled || state.loading} onClick={() => void library.load(true)}>加载更多来源</button>}
      {state.asset && !selectedIds.includes(state.asset.id) && (
        <button className="hd-agent-allow" disabled={disabled || selected.length >= 20} onClick={() => add(state.asset!)}>
          <Plus size={15} />允许 AI 使用“{state.asset.name}”
        </button>
      )}
      {selected.length >= 20 && <p role="status">已达到 20 件授权上限。</p>}
    </section>
  );
}
