import {request} from "./designApi";
import type {HomeDesignDocument,HomeDeliveryLine,HomeValidation,HomeQuote} from "@/types/homeDesign";
import type {SpatialDocument} from "@/types/spatial";

type DeliveryQuote = Pick<HomeQuote["snapshot"], "currency"|"known_subtotal"|"pending_count"|"total_price"|"created_at"|"limitations"> & {
  lines: Pick<HomeQuote["snapshot"]["lines"][number], "entity_type"|"id"|"unit_price"|"total_price"|"source_data_version"|"source_version"|"rule_evidence"|"rule_evidence_digest">[];
};
export interface DeliverySnapshot {
  schema_version:string;home_version:number;space_version:number;
  document:HomeDesignDocument;space:SpatialDocument;lines:Omit<HomeDeliveryLine,"asset">[];
  validation:HomeValidation;gaps:{code:string;entity_type:string|null;id:string|null}[];
  limitations:string[];quote:DeliveryQuote|null;
}
export interface FrozenDelivery {id:number;task_id:number;home_version:number;space_version:number;quote_id:number|null;content_digest:string;created_at:string;snapshot:DeliverySnapshot}
export type DeliverySummary=Omit<FrozenDelivery,"snapshot">;
export interface DeliveryConfirmation {id:number;delivery_id:number;snapshot_digest:string;decision:"reviewed"|"needs_changes";note:string;created_at:string}
export interface DeliveryShare {id:number;delivery_id:number;expires_at:string;revoked_at:string|null;token:string|null;share_url:string|null;replayed:boolean}
export interface Page<T>{items:T[];next_before_id:number|null}
const path=(id:number)=>`/api/design/tasks/${id}/home-design`;
const post=<T>(url:string,payload:unknown)=>request<T>(url,{method:"POST",body:JSON.stringify(payload)});
export const createDelivery=(id:number,payload:{home_version:number;quote_id:number|null;client_mutation_id:string})=>post<FrozenDelivery>(`${path(id)}/deliveries`,payload);
export const getDeliveries=(id:number,version:number,before?:number)=>request<Page<DeliverySummary>>(`${path(id)}/deliveries?home_version=${version}${before?`&before_id=${before}`:""}`);
export const getDelivery=(id:number,delivery:number)=>request<FrozenDelivery>(`${path(id)}/deliveries/${delivery}`);
export const confirmDelivery=(id:number,delivery:number,payload:{client_mutation_id:string;snapshot_digest:string;decision:"reviewed"|"needs_changes";note:string})=>post<DeliveryConfirmation>(`${path(id)}/deliveries/${delivery}/confirmations`,payload);
export const getDeliveryConfirmations=(id:number,delivery:number,before?:number)=>request<Page<DeliveryConfirmation>>(`${path(id)}/deliveries/${delivery}/confirmations${before?`?before_id=${before}`:""}`);
export const createDeliveryShare=(id:number,delivery:number,payload:{client_mutation_id:string;consent_public:boolean;expires_in_hours:number;include_private_models:boolean;include_source_image:boolean})=>post<DeliveryShare>(`${path(id)}/deliveries/${delivery}/shares`,payload);
export const getDeliveryShares=(id:number,before?:number)=>request<Page<DeliveryShare>>(`${path(id)}/shares${before?`?before_id=${before}`:""}`);
export const revokeDeliveryShare=(id:number,share:number)=>post<{id:number;status:"revoked"}>(`${path(id)}/shares/${share}/revoke`,{});
export async function readPublicDelivery(token:string):Promise<{expires_at:string;snapshot:DeliverySnapshot}>{
  const response=await fetch(`/api/home-shares/${encodeURIComponent(token)}`,{credentials:"omit",cache:"no-store",referrerPolicy:"no-referrer",headers:{Accept:"application/json"}});
  if(response.status===404)throw Error("分享链接不存在或已失效");
  if(!response.ok)throw Error("暂时无法读取分享方案");
  const value=await response.json();
  if(value?.snapshot?.schema_version!=="public-home-delivery/1.0")throw Error("分享方案格式无效");
  return value;
}
