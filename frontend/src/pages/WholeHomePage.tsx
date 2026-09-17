import { useEffect,useState } from "react";
import { Link,useParams } from "react-router-dom";
import { fetchDesignAgentState } from "@/api/designApi";
import WholeHomeWorkspace from "@/components/spatial/WholeHomeWorkspace";
import { parseDesignProjectId } from "@/lib/designWorkspaceRouting";
import { useDesignProjectStore } from "@/store/useDesignProjectStore";
import type { RoomSource } from "@/types/roomModel";
export default function WholeHomePage() {
  const { projectId }=useParams();
  const taskId=parseDesignProjectId(projectId);
  const project=useDesignProjectStore(s => taskId? s.projects[taskId]:undefined);
  const [source,setSource]=useState<RoomSource|null>(null);
  useEffect(() => {
    let active=true; setSource(null); if(taskId)
      void fetchDesignAgentState(taskId).then(checkpoint => {
        if(active)
          setSource(checkpoint.room_source??null);
      }).catch(() => { }); return () => { active=false; };
  },[taskId]);
  if(!taskId)
    return <div className="p-8"><h1>空间地址无效</h1><Link to="/design/new">返回设计首页</Link></div>;
  return <WholeHomeWorkspace key={taskId} taskId={taskId} title={project?.title??"住宅设计"} roomSource={source} />;
}
