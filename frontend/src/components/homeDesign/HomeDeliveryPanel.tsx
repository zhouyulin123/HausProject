import { useEffect, useRef, useState } from "react";
import { Download, RefreshCw } from "lucide-react";
import HomeQuotePanel from "./HomeQuotePanel";
import HomeFrozenDeliveryPanel from "./HomeFrozenDeliveryPanel";
import {
  compareHomeDesigns,
  getHomeDelivery,
  getHomeDesignVersions,
} from "@/api/homeDesignApi";
import type {
  HomeDelivery,
  HomeComparison,
  HomeVersionList,
} from "@/types/homeDesign";
const quantityLabel: Record<string, string> = {
  measured: "按绑定空间净面积计算",
  counted: "按保存物件逐件计数",
  pending_scale: "待确认尺度",
  unmeasurable: "暂不可计量",
  no_design_elements: "尚无设计要素",
};
export function DeliverySummary({ delivery }: { delivery: HomeDelivery }) {
  return (
    <section className="hd-delivery-summary">
      <h3>
        家装 V{delivery.home_version} · 空间 V{delivery.space_version}
      </h3>
      <p>总价：待报价</p>
      <p>
        {delivery.validation.valid ? "当前几何检查通过" : "存在待修正几何问题"}
      </p>
      {delivery.lines.map((line) => (
        <article key={`${line.entity_type}-${line.id}`}>
          <strong>
            {line.room_name} · {line.name}
          </strong>
          <p>
            {line.material.name} ·{" "}
            {line.quantity === null ? "—" : line.quantity.toLocaleString()}{" "}
            {line.unit === "m2" ? "平方米" : "件"}
          </p>
          <small>
            {quantityLabel[line.quantity_status] ?? line.quantity_status} ·
            待报价
          </small>
          {line.asset && <p><small>{line.asset.kind === "product" ? "商品家具" : "本任务作品"} #{line.asset.source_id} · 冻结来源 V{line.asset.source_version}</small></p>}
        </article>
      ))}
      {delivery.gaps.length > 0 && (
        <div role="status">
          <strong>清单缺项</strong>
          {delivery.gaps.map((gap, index) => (
            <p key={index}>{quantityLabel[gap.code] ?? gap.code}</p>
          ))}
        </div>
      )}
      <ul>
        {delivery.limitations.map((text) => (
          <li key={text}>{text}</li>
        ))}
      </ul>
    </section>
  );
}
export default function HomeDeliveryPanel({
  taskId,
  version,
  dirty,
}: {
  taskId: number;
  version: number;
  dirty: boolean;
}) {
  const [delivery, setDelivery] = useState<HomeDelivery | null>(null),
    [comparison, setComparison] = useState<HomeComparison | null>(null),
    [versions, setVersions] = useState<HomeVersionList | null>(null),
    [from, setFrom] = useState(""),
    [to, setTo] = useState(String(version)),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const generation = useRef(0);
  const load = async () => {
    const key = ++generation.current;
    setBusy(true);
    setError("");
    setDelivery(null);
    setComparison(null);
    try {
      const list = await getHomeDesignVersions(taskId);
      const result =
        version > 0 ? await getHomeDelivery(taskId, version) : null;
      if (key !== generation.current) return;
      setVersions(list);
      setDelivery(result);
      setTo(String(version));
      setFrom(
        String(list.versions.find((v) => v.version !== version)?.version ?? ""),
      );
    } catch {
      if (key === generation.current)
        setError("清单读取失败，可能无权限、版本不存在或网络异常。请重试。");
    } finally {
      if (key === generation.current) setBusy(false);
    }
  };
  useEffect(() => {
    void load();
    return () => {
      generation.current++;
    };
  }, [taskId, version]);
  const compare = async () => {
    const key = ++generation.current;
    setBusy(true);
    setError("");
    setComparison(null);
    try {
      const result = await compareHomeDesigns(taskId, Number(from), Number(to));
      if (key === generation.current) setComparison(result);
    } catch {
      if (key === generation.current)
        setError("版本比较失败，请重试；未生成替代结果。");
    } finally {
      if (key === generation.current) setBusy(false);
    }
  };
  const more = async () => {
    if (!versions?.next_before_version) return;
    const key = ++generation.current;
    setError("");
    setBusy(true);
    try {
      const result = await getHomeDesignVersions(
        taskId,
        versions.next_before_version,
      );
      if (key !== generation.current) return;
      setVersions({
        ...result,
        versions: [...versions.versions, ...result.versions],
      });
    } catch {
      if (key === generation.current) setError("历史列表读取失败，请重试");
    } finally {
      if (key === generation.current) setBusy(false);
    }
  };
  const download = () => {
    if (!delivery) return;
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(delivery, null, 2)], {
        type: "application/json",
      }),
    );
    const a = document.createElement("a");
    a.href = url;
    a.download = `家装概念清单-${taskId}-v${delivery.home_version}.json`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  return (
    <div className="hd-delivery">
      <p>概念方案沟通资料 · 非施工交付</p>
      {dirty && (
        <p role="status">
          当前有未保存修改。以下仅引用已保存版本，不包含草稿。
        </p>
      )}
      {!version && <p>保存首个家装版本后可读取清单。</p>}
      <button disabled={busy} onClick={() => void load()}>
        <RefreshCw size={16} />
        重新读取
      </button>
      {error && <p role="alert">{error}</p>}
      {busy && <p role="status">正在读取…</p>}
      {delivery && (
        <>
          <button onClick={download}>
            <Download size={16} />
            下载此版本 JSON
          </button>
          <DeliverySummary delivery={delivery} />
        </>
      )}
      {version>0 && <HomeQuotePanel taskId={taskId} version={version} dirty={dirty}/>}
      {version>0 && <HomeFrozenDeliveryPanel key={`${taskId}-${version}`} taskId={taskId} version={version} dirty={dirty}/>}
      <h3>比较已保存版本</h3>
      <div className="hd-fields">
        <label>
          原版本
          <select
            value={from}
            onChange={(e) => {
              setFrom(e.target.value);
              setComparison(null);
            }}
            disabled={busy}
          >
            <option value="">请选择</option>
            {versions?.versions.map((v) => (
              <option key={v.version} value={v.version}>
                V{v.version} / 空间 V{v.space_version}
              </option>
            ))}
          </select>
        </label>
        <label>
          目标版本
          <select
            value={to}
            onChange={(e) => {
              setTo(e.target.value);
              setComparison(null);
            }}
            disabled={busy}
          >
            <option value="">请选择</option>
            {versions?.versions.map((v) => (
              <option key={v.version} value={v.version}>
                V{v.version} / 空间 V{v.space_version}
              </option>
            ))}
          </select>
        </label>
      </div>
      <button
        disabled={busy || !from || !to || from === to}
        onClick={() => void compare()}
      >
        比较版本
      </button>
      {versions?.next_before_version && (
        <button disabled={busy} onClick={() => void more()}>
          加载更早版本
        </button>
      )}
      {comparison && (
        <section>
          <h3>
            V{comparison.from_version} → V{comparison.to_version}
          </h3>
          {comparison.space_changed && (
            <p role="status">
              空间版本不同：V{comparison.from_space_version} → V
              {comparison.to_space_version}，数量变化可能来自空间修改。
            </p>
          )}
          {comparison.validation_changed && <p>几何检查结果发生变化</p>}
          {!comparison.changes.length && <p>设计要素无变化</p>}
          {comparison.changes.map((c) => (
            <article key={`${c.entity_type}-${c.id}`}>
              <strong>
                {{ added: "新增", removed: "移除", modified: "修改" }[c.change]}{" "}
                · {(c.after_line ?? c.before_line)?.name ?? (c.after && "name" in c.after ? c.after.name : c.before && "name" in c.before ? c.before.name : c.id)}
              </strong>
              <p>{c.changed_fields.join("、")}</p>
              <small>
                数量：{c.before_line?.quantity ?? "—"} →{" "}
                {c.after_line?.quantity ?? "—"}
              </small>
            </article>
          ))}
        </section>
      )}
    </div>
  );
}
