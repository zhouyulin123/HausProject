import { useParams, Link } from "react-router-dom";
import { parseDesignProjectId } from "@/lib/designWorkspaceRouting";
import HomeDesignWorkspace from "@/components/homeDesign/HomeDesignWorkspace";
export default function HomeDesignPage() {
  const { projectId } = useParams();
  const id = parseDesignProjectId(projectId);
  return id ? (
    <HomeDesignWorkspace key={id} taskId={id} />
  ) : (
    <main className="p-8">
      <h1>设计地址无效</h1>
      <Link to="/design/new">返回设计首页</Link>
    </main>
  );
}
