import type { HomeAsset, HomeAssetKind, HomeAssetOption, HomeAssetOptions, HomeAssetRequest } from "@/types/homeDesign";
type API = {
  list: (task: number, kind: HomeAssetKind, after?: number) => Promise<HomeAssetOptions>;
  freeze: (task: number, payload: HomeAssetRequest) => Promise<HomeAsset>;
};
type State = {
  kind: HomeAssetKind;
  options: HomeAssetOption[];
  next: number | null;
  loading: boolean;
  freezing: boolean;
  error: string;
  asset: HomeAsset | null;
  pending: HomeAssetRequest | null;
};
export class HomeAssetLibrary {
  private state: State = {kind: "product", options: [], next: null, loading: false, freezing: false, error: "", asset: null, pending: null};
  private listeners = new Set<() => void>();
  private generation = 0;
  private listGeneration = 0;
  constructor(readonly taskId: number, private api: API) {}
  subscribe = (f: () => void) => {
    this.listeners.add(f);
    return () => { this.listeners.delete(f); };
  };
  getSnapshot = () => this.state;
  private publish(next: Partial<State>) {
    this.state = {...this.state, ...next};
    this.listeners.forEach(f => f());
  }
  async switchKind(kind: HomeAssetKind) {
    ++this.generation;
    ++this.listGeneration;
    this.publish({kind, options: [], next: null, asset: null, pending: null, freezing: false, error: "", loading: false});
    await this.load();
  }
  async load(more = false) {
    if (this.state.loading || (more && this.state.next === null)) return;
    const token = ++this.listGeneration;
    const {kind, next, options} = this.state;
    this.publish({loading: true, error: ""});
    try {
      const result = await this.api.list(this.taskId, kind, more ? next! : undefined);
      if (token !== this.listGeneration) return;
      const combined = more ? [...options, ...result.items] : result.items;
      this.publish({
        options: [...new Map(combined.map(item => [`${item.kind}-${item.source_id}-${item.source_version}`, item])).values()],
        next: result.next_after_id,
      });
    } catch (e) {
      if (token === this.listGeneration) this.publish({error: e instanceof Error ? e.message : "家具库读取失败"});
    } finally {
      if (token === this.listGeneration) this.publish({loading: false});
    }
  }
  async freeze(option: HomeAssetOption) {
    if (!option.available || !option.source_version || this.state.freezing) return;
    ++this.generation;
    this.publish({
      pending: {client_mutation_id: `library-v1:${option.kind}:${option.source_id}:${option.source_version}`, kind: option.kind, source_id: option.source_id, source_version: option.source_version},
      asset: null,
    });
    await this.retry();
  }
  async retry() {
    const pending = this.state.pending;
    if (!pending || this.state.freezing) return;
    const token = this.generation;
    this.publish({freezing: true, error: ""});
    try {
      const asset = await this.api.freeze(this.taskId, pending);
      if (token !== this.generation) return;
      if (asset.task_id !== this.taskId || asset.kind !== pending.kind || asset.source_id !== pending.source_id || asset.source_version !== pending.source_version) {
        throw Error("家具冻结来源不匹配");
      }
      this.publish({asset, pending: null});
    } catch (e) {
      if (token === this.generation) this.publish({error: e instanceof Error ? e.message : "冻结失败，请重试原请求"});
    } finally {
      if (token === this.generation) this.publish({freezing: false});
    }
  }
}
