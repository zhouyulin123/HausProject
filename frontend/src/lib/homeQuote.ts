import type { HomeQuote, HomeQuoteList, HomeQuoteRequest } from "@/types/homeDesign";
type API = {create: (id:number,p:HomeQuoteRequest)=>Promise<HomeQuote>;list:(id:number,version:number,before?:number)=>Promise<HomeQuoteList>};
type StorageLike = Pick<Storage,"getItem"|"setItem"|"removeItem">;
interface State { items:HomeQuote[]; selected:HomeQuote|null; next:number|null; busy:boolean; error:string; pending:HomeQuoteRequest|null }
export class HomeQuoteController {
  private state:State={items:[],selected:null,next:null,busy:false,error:"",pending:null};
  private listeners=new Set<()=>void>();
  private generation=0;
  constructor(private id:number,private version:number,private api:API,private storage:StorageLike|null=null) {
    try {
      const pending=JSON.parse(storage?.getItem(this.key) ?? "null") as HomeQuoteRequest|null;
      if(pending && pending.home_version===version && /^[A-Z0-9-]{2,32}$/.test(pending.region) && typeof pending.client_mutation_id==="string" && pending.client_mutation_id.trim()) this.state.pending=pending;
    }catch{this.state.error="本机估价重试记录无效，未恢复";}
  }
  private get key(){return `haus-home-quote-pending-${this.id}-${this.version}`;}
  subscribe=(listener:()=>void)=>{this.listeners.add(listener);return()=>{this.listeners.delete(listener);};};
  getSnapshot=()=>this.state;
  private publish(p:Partial<State>){this.state={...this.state,...p};this.listeners.forEach(l=>l());}
  private persist(){try{if(this.state.pending)this.storage?.setItem(this.key,JSON.stringify(this.state.pending));else this.storage?.removeItem(this.key);}catch{this.publish({error:"本机估价重试记录无法保存，请勿关闭页面后重复创建"});}}
  private check(quote:HomeQuote){if(quote.task_id!==this.id || quote.home_version!==this.version || (quote.snapshot.home_version!==undefined && quote.snapshot.home_version!==this.version))throw Error("估价版本不匹配，未载入");}
  async load(more=false){
    if(this.state.busy || this.version<1 || (more && !this.state.next))return;
    const generation=++this.generation;this.publish({busy:true,error:""});
    try{const result=await this.api.list(this.id,this.version,more?this.state.next!:undefined);if(generation!==this.generation)return;result.items.forEach(q=>this.check(q));const items=more?[...this.state.items,...result.items.filter(q=>!this.state.items.some(p=>p.id===q.id))]:result.items;this.publish({items,next:result.next_before_id,selected:this.state.selected ?? items[0] ?? null});}
    catch(e){if(generation===this.generation)this.publish({error:e instanceof Error?e.message:"估价历史读取失败"});}
    finally{if(generation===this.generation)this.publish({busy:false});}
  }
  async create(region:string){
    if(this.state.busy || this.version<1 || this.state.pending)return;
    if(!/^[A-Z0-9-]{2,32}$/.test(region)){this.publish({error:"请填写地区代码，例如 CN-SH"});return;}
    this.publish({pending:{home_version:this.version,region,client_mutation_id:crypto.randomUUID()}});this.persist();await this.retry();
  }
  async retry(){
    if(this.state.busy || !this.state.pending)return;
    const generation=++this.generation;const payload=this.state.pending;this.publish({busy:true,error:""});
    try{const result=await this.api.create(this.id,payload);if(generation!==this.generation)return;this.check(result);this.publish({selected:result,items:[result,...this.state.items.filter(q=>q.id!==result.id)],pending:null});this.persist();}
    catch(e){if(generation===this.generation){const rejected=(e as {status?:number})?.status===422;this.publish({error:e instanceof Error?e.message:rejected?"估价参数未通过，请修正后重试":"估价创建失败，请重试原请求",...(rejected?{pending:null}:{})});if(rejected)this.persist();}}
    finally{if(generation===this.generation)this.publish({busy:false});}
  }
  select(id:number){const quote=this.state.items.find(q=>q.id===id);if(quote)this.publish({selected:quote});}
  dispose(){this.generation++;this.publish({busy:false});}
}
