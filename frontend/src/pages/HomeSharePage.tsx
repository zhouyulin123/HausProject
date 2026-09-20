import {useEffect,useState} from "react";
import {useParams} from "react-router-dom";
import {Printer} from "lucide-react";
import {readPublicDelivery,type DeliverySnapshot} from "@/api/homeDeliveryApi";
import HomeDeliveryView from "@/components/homeDesign/HomeDeliveryView";

export default function HomeSharePage(){
  const {token=""}=useParams();return <PublicDelivery key={token} token={token}/>;
}
function PublicDelivery({token}:{token:string}){
  const [data,setData]=useState<{expires_at:string;snapshot:DeliverySnapshot}|null>(null),[error,setError]=useState(""),[retry,setRetry]=useState(0);
  useEffect(()=>{let active=true;setData(null);setError("");void readPublicDelivery(token).then(value=>{if(active)setData(value);}).catch(e=>{if(active)setError(e instanceof Error?e.message:"分享读取失败");});return()=>{active=false;};},[token,retry]);
  return <main className="hdelivery">{data?<><div className="hdelivery-controls"><span>只读分享 · 到期 {new Date(data.expires_at).toLocaleString()}</span><button title="打印方案" onClick={()=>window.print()}><Printer size={18}/></button></div><HomeDeliveryView snapshot={data.snapshot}/></>:<><h1>{error||"正在读取分享方案…"}</h1>{error&&<button onClick={()=>setRetry(value=>value+1)}>重新读取</button>}</>}</main>;
}
