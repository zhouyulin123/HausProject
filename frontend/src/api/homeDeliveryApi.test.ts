import {it,expect,vi} from "vitest";
vi.mock("./designApi",()=>({request:vi.fn()}));
import {request} from "./designApi";
import {createDelivery,createDeliveryShare,readPublicDelivery} from "./homeDeliveryApi";
it("交付与分享保留显式版本和授权",async()=>{
  const payload={home_version:3,quote_id:7,client_mutation_id:"retry"};
  await createDelivery(2,payload);expect(request).toHaveBeenLastCalledWith("/api/design/tasks/2/home-design/deliveries",{method:"POST",body:JSON.stringify(payload)});
  const share={client_mutation_id:"share",consent_public:true,expires_in_hours:24,include_private_models:false,include_source_image:false};
  await createDeliveryShare(2,4,share);expect(request).toHaveBeenLastCalledWith("/api/design/tasks/2/home-design/deliveries/4/shares",{method:"POST",body:JSON.stringify(share)});
});
it("公开访问不带会话或凭据并禁止缓存",async()=>{
  const fetch=vi.fn().mockResolvedValue({ok:true,json:async()=>({snapshot:{schema_version:"public-home-delivery/1.0"}})});vi.stubGlobal("fetch",fetch);
  try{await readPublicDelivery("token");expect(fetch).toHaveBeenCalledWith("/api/home-shares/token",expect.objectContaining({credentials:"omit",cache:"no-store",referrerPolicy:"no-referrer"}));}finally{vi.unstubAllGlobals();}
});
