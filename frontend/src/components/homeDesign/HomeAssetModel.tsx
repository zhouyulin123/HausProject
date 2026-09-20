import { Component, type ReactNode } from "react";
import type { HomeObject } from "@/types/homeDesign";
import type { HomeAssetEntry } from "@/lib/useHomeAssets";
import { homeAssetOffset } from "@/lib/homeAssets";
import { deterministicFurnitureRule } from "@/lib/deterministicFurniture";
import DeterministicFurnitureModel3D from "@/components/furniture/DeterministicFurnitureModel3D";
class ModelBoundary extends Component<{children:ReactNode;fallback:ReactNode;onError:()=>void},{failed:boolean}>{
  state={failed:false};
  static getDerivedStateFromError(){return {failed:true};}
  componentDidCatch(){this.props.onError();}
  render(){return this.state.failed?this.props.fallback:this.props.children;}
}
function FrozenModel({entry}:{entry:HomeAssetEntry}){
  const asset=entry.asset!;
  const rule=deterministicFurnitureRule(asset.model_spec);
  if(!rule)throw Error("冻结模型不支持确定性渲染");
  return <group position={homeAssetOffset(asset)}><DeterministicFurnitureModel3D rule={rule}/></group>;
}
export default function HomeAssetModel({object,entry,selected,onSelect,onError}:{object:HomeObject;entry?:HomeAssetEntry;selected:boolean;onSelect:()=>void;onError:()=>void}){
  const placeholder=<mesh position={[0,object.size.height/2,0]}><boxGeometry args={[object.size.width,object.size.height,object.size.depth]}/><meshBasicMaterial color={entry?.loading?"#7b8d96":"#c45242"} wireframe/></mesh>;
  return <group position={[object.position.x,object.position.y,object.position.z]} rotation={[0,object.rotation*Math.PI/180,0]} onClick={e=>{e.stopPropagation();onSelect();}}>
    {entry?.asset ? <ModelBoundary key={entry.asset.content_digest} fallback={placeholder} onError={onError}><FrozenModel entry={entry}/></ModelBoundary> : placeholder}
    {selected && <mesh position={[0,object.size.height/2,0]}><boxGeometry args={[object.size.width+.01,object.size.height+.01,object.size.depth+.01]}/><meshBasicMaterial color="#16775b" wireframe/></mesh>}
  </group>;
}
