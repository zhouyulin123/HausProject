import type { HomeObject, HomePoint } from "@/types/homeDesign";

export const pointLabels: Record<HomePoint["kind"], string> = {
  socket: "插座", switch: "开关", water: "给水", drain: "排水", network: "网络", other: "其他",
};
function number(form: FormData, key: string) {
  const raw = form.get(key);
  if (typeof raw !== "string" || !raw.trim() || !Number.isFinite(Number(raw))) throw Error("请填写有效的数值");
  return Number(raw);
}
export function pointFromForm(form: FormData, id: string): HomePoint {
  return {
    id, name: String(form.get("name")), room_id: String(form.get("room")),
    kind: form.get("kind") as HomePoint["kind"],
    position: {x:number(form,"x"),y:number(form,"y"),z:number(form,"z")},
    confirmed: form.get("confirmed") === "on",
  };
}
export function objectRequirements(form: FormData, frozen: boolean): Pick<HomeObject,"installation" | "clearance" | "point_requirement"> {
  const kind = form.get("installation") as NonNullable<HomeObject["installation"]>["kind"] | null;
  if (frozen && kind && kind !== "floor") throw Error("冻结家具目前仅支持落地安装");
  const wall = kind === "wall" ? String(form.get("installation_wall") ?? "") : null;
  if (kind === "wall" && !wall) throw Error("请选择安装宿主墙");
  const clearance = form.get("clearance_enabled") === "on" ? {
    front:number(form,"clearance_front"),back:number(form,"clearance_back"),left:number(form,"clearance_left"),right:number(form,"clearance_right"),above:number(form,"clearance_above"),confirmed:form.get("clearance_confirmed") === "on",
  } : null;
  const pointId = String(form.get("point_requirement") ?? "");
  return {installation:kind ? {kind,wall_id:wall} : null,clearance,point_requirement:pointId ? {point_id:pointId,max_distance_m:number(form,"point_distance")} : null};
}
export function clearanceBox(object: Pick<HomeObject,"size" | "clearance">) {
  const c = object.clearance;
  if (!c) return null;
  return {width:object.size.width+c.left+c.right,height:object.size.height+c.above,depth:object.size.depth+c.front+c.back,x:(c.right-c.left)/2,y:(object.size.height+c.above)/2,z:(c.front-c.back)/2};
}
