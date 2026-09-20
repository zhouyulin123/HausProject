import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  createDelivery,
  getDeliveries,
  type DeliverySummary,
} from "@/api/homeDeliveryApi";
import { getHomeQuotes } from "@/api/homeDesignApi";
import type { HomeQuote } from "@/types/homeDesign";

export default function HomeFrozenDeliveryPanel({
  taskId,
  version,
  dirty,
}: {
  taskId: number;
  version: number;
  dirty: boolean;
}) {
  const [items, setItems] = useState<DeliverySummary[]>([]);
  const [quotes, setQuotes] = useState<HomeQuote[]>([]);
  const [quote, setQuote] = useState("");
  const [next, setNext] = useState<number | null>(null);
  const [quoteNext, setQuoteNext] = useState<number | null>(null);
  const [deliveryBusy, setDeliveryBusy] = useState(false);
  const [quoteBusy, setQuoteBusy] = useState(false);
  const [actionBusy, setActionBusy] = useState(false);
  const [deliveryError, setDeliveryError] = useState("");
  const [quoteError, setQuoteError] = useState("");
  const [actionError, setActionError] = useState("");
  const key = `haus-delivery-pending-${taskId}-${version}`;
  const pending = useRef<Parameters<typeof createDelivery>[1] | null>(null);
  const deliveryGeneration = useRef(0);
  const quoteGeneration = useRef(0);
  const actionGeneration = useRef(0);

  const loadDeliveries = async (more = false) => {
    const token = ++deliveryGeneration.current;
    setDeliveryBusy(true);
    setDeliveryError("");
    try {
      const result = await getDeliveries(
        taskId,
        version,
        more ? (next ?? undefined) : undefined,
      );
      if (token !== deliveryGeneration.current) return;
      if (
        result.items.some(
          (item) => item.task_id !== taskId || item.home_version !== version,
        )
      )
        throw Error("交付版本不匹配");
      setItems((old) =>
        more
          ? [...old, ...result.items.filter((item) => !old.some((p) => p.id === item.id))]
          : result.items,
      );
      setNext(result.next_before_id);
    } catch (error) {
      if (token === deliveryGeneration.current)
        setDeliveryError(error instanceof Error ? error.message : "交付历史读取失败");
    } finally {
      if (token === deliveryGeneration.current) setDeliveryBusy(false);
    }
  };

  const loadQuotes = async (more = false) => {
    if (more && !quoteNext) return;
    const token = ++quoteGeneration.current;
    setQuoteBusy(true);
    setQuoteError("");
    try {
      const result = await getHomeQuotes(
        taskId,
        version,
        more ? quoteNext ?? undefined : undefined,
      );
      if (token !== quoteGeneration.current) return;
      if (
        result.items.some(
          (item) => item.task_id !== taskId || item.home_version !== version,
        )
      )
        throw Error("估价版本不匹配");
      setQuotes((old) =>
        more
          ? [...old, ...result.items.filter((item) => !old.some((p) => p.id === item.id))]
          : result.items,
      );
      setQuoteNext(result.next_before_id);
      if (!more) setQuote("");
    } catch (error) {
      if (token === quoteGeneration.current)
        setQuoteError(error instanceof Error ? error.message : "估价读取失败");
    } finally {
      if (token === quoteGeneration.current) setQuoteBusy(false);
    }
  };

  useEffect(() => {
    try {
      const value = JSON.parse(localStorage.getItem(key) ?? "null");
      if (
        value?.home_version === version &&
        typeof value.client_mutation_id === "string"
      )
        pending.current = value;
    } catch {
      setActionError("本机交付重试记录无法恢复");
    }
    void loadDeliveries();
    void loadQuotes();
    return () => {
      deliveryGeneration.current++;
      quoteGeneration.current++;
      actionGeneration.current++;
    };
  }, [taskId, version]);

  const create = async () => {
    if (actionBusy || dirty) return;
    const token = ++actionGeneration.current;
    setActionBusy(true);
    setActionError("");
    try {
      pending.current ??= {
        home_version: version,
        quote_id: quote ? Number(quote) : null,
        client_mutation_id: crypto.randomUUID(),
      };
      localStorage.setItem(key, JSON.stringify(pending.current));
      const result = await createDelivery(taskId, pending.current);
      if (token !== actionGeneration.current) return;
      if (result.task_id !== taskId || result.home_version !== version)
        throw Error("交付版本不匹配");
      localStorage.removeItem(key);
      pending.current = null;
      setItems((old) => [result, ...old.filter((item) => item.id !== result.id)]);
    } catch (error) {
      if (token === actionGeneration.current) {
        if ((error as { status?: number })?.status === 422) {
          pending.current = null;
          localStorage.removeItem(key);
        }
        setActionError(
          error instanceof Error ? error.message : "交付创建失败，请重试原请求",
        );
      }
    } finally {
      if (token === actionGeneration.current) setActionBusy(false);
    }
  };

  return (
    <section className="hd-frozen-delivery">
      <h3>交付与审阅</h3>
      <label>
        附带估价
        <select
          value={quote}
          onChange={(event) => setQuote(event.target.value)}
          disabled={quoteBusy || actionBusy || !!pending.current}
        >
          <option value="">不附估价</option>
          {quotes.map((item) => (
            <option key={item.id} value={item.id}>
              #{item.id} · {item.snapshot.region} · 已知小计 {item.snapshot.known_subtotal}
              元 · 待报价 {item.snapshot.pending_count} 项 ·{" "}
              {new Date(item.snapshot.created_at).toLocaleString()}
            </option>
          ))}
        </select>
      </label>
      <button
        disabled={actionBusy || dirty || version < 1}
        onClick={() => void create()}
      >
        {pending.current ? "重试原交付请求" : "冻结此版本交付"}
      </button>
      {quoteNext && (
        <button
          disabled={quoteBusy || actionBusy || !!pending.current}
          onClick={() => void loadQuotes(true)}
        >
          加载更早估价
        </button>
      )}
      {pending.current && (
        <button
          disabled={actionBusy}
          onClick={() => {
            if (
              window.confirm(
                "仅解除本机重试记录，不会删除已创建的交付。请先核对交付历史，确认继续？",
              )
            ) {
              try {
                localStorage.removeItem(key);
                pending.current = null;
                setActionError("已解除本机重试记录，请核对交付历史。");
              } catch {
                setActionError("无法解除本机重试记录");
              }
            }
          }}
        >
          解除本机重试记录
        </button>
      )}
      <button disabled={deliveryBusy} onClick={() => void loadDeliveries()}>
        刷新交付历史
      </button>
      <button disabled={quoteBusy} onClick={() => void loadQuotes()}>
        刷新估价历史
      </button>
      {dirty && <p>保存草稿后才能创建交付。</p>}
      {deliveryError && <p role="alert">交付历史：{deliveryError}</p>}
      {quoteError && <p role="alert">估价历史：{quoteError}</p>}
      {actionError && <p role="alert">{actionError}</p>}
      {items.map((item) => (
        <p key={item.id}>
          <Link to={`/design/${taskId}/delivery/${item.id}`}>
            查看交付 #{item.id} · 家装 V{item.home_version}
          </Link>
        </p>
      ))}
      {next && (
        <button disabled={deliveryBusy} onClick={() => void loadDeliveries(true)}>
          更多交付记录
        </button>
      )}
    </section>
  );
}
