import { useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { ArrowLeft, Box, History, Maximize2, MessageSquareText, Minimize2, SlidersHorizontal, X } from "lucide-react";

interface Props {
  title: string;
  connection: string;
  name: string;
  versionLabel: string;
  source: "open_geometry" | "structured";
  onSourceChange: (source: "open_geometry" | "structured") => void;
  chat: ReactNode;
  preview: ReactNode;
  geometryTools: ReactNode;
  templateTools: ReactNode;
  activity: ReactNode;
  approvals: ReactNode;
}

/** 家具作品与会话共享一个画布，辅助工具按需展开，不创建第二份设计状态。 */
export default function FurnitureDesignWorkspace(props: Props) {
  const [mobileView, setMobileView] = useState<"chat" | "model">("chat");
  const [toolsOpen, setToolsOpen] = useState(false);
  const [templateVisited, setTemplateVisited] = useState(false);
  const [expanded, setExpanded] = useState(false);
  useEffect(() => {
    if (!expanded) return;
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape") setExpanded(false);
    };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [expanded]);
  const iconButton = "inline-flex h-10 w-10 shrink-0 items-center justify-center rounded border border-[#d5dbd7] text-[#48564d] hover:bg-[#e8eeea] focus-visible:outline-2 focus-visible:outline-[#637e60]";
  return (
    <div className="min-h-[calc(100dvh-4rem)] bg-[#f4f6f5] text-[#26372e]">
      <header className="flex min-h-16 flex-wrap items-center justify-between gap-3 border-b border-[#d5dbd7] px-4 py-3 lg:px-6">
        <div className="flex min-w-0 items-center gap-3">
          <Link to="/design/new" title="返回设计首页" aria-label="返回设计首页" className={iconButton}><ArrowLeft size={18} /></Link>
          <div className="min-w-0">
            <h1 className="break-words text-sm font-semibold !text-[#26372e]">{props.title}</h1>
            <p className="mt-1 text-xs text-[#68796e]">家具设计 · {props.connection}</p>
          </div>
        </div>
        <div className="flex max-w-full items-center gap-1 rounded border border-[#d5dbd7] p-1" aria-label="家具设计方式">
          {([['open_geometry', '对话作品'], ['structured', '模板定制']] as const).map(([source, label]) => (
            <button key={source} type="button" aria-pressed={props.source === source}
              onClick={() => { props.onSourceChange(source); if (source === 'structured') setTemplateVisited(true); setToolsOpen(source === 'structured'); setMobileView('model'); }}
              className={`min-h-9 px-3 text-xs ${props.source === source ? 'bg-[#304e40] text-white' : 'text-[#53655a] hover:bg-[#e8eeea]'}`}>{label}</button>
          ))}
        </div>
      </header>
      {props.approvals}
      <nav aria-label="移动端工作台视图" className="grid grid-cols-2 border-b border-[#d5dbd7] lg:hidden">
        {([['chat', '对话', MessageSquareText], ['model', '当前作品', Box]] as const).map(([id, label, Icon]) => (
          <button type="button" key={id} aria-pressed={mobileView === id} onClick={() => setMobileView(id)}
            className={`flex min-h-11 items-center justify-center gap-2 text-sm ${mobileView === id ? 'bg-[#e1eae4] text-[#304e40]' : 'text-[#68796e]'}`}><Icon size={16} />{label}</button>
        ))}
      </nav>
      <div className="grid min-w-0 lg:h-[calc(100dvh-9rem)] lg:min-h-[540px] lg:grid-cols-[clamp(420px,38%,600px)_minmax(0,1fr)]">
        <section aria-label="家具设计对话" className={`min-h-0 min-w-0 border-r border-[#d5dbd7] ${mobileView === 'chat' ? 'flex' : 'hidden lg:flex'} flex-col`}>
          {props.chat}
          <details className="shrink-0 border-t border-[#d5dbd7] bg-white text-xs">
            <summary className="cursor-pointer px-4 py-3 text-[#68796e]">执行记录</summary>
            <div className="max-h-60 overflow-y-auto">{props.activity}</div>
          </details>
        </section>
        <main aria-label="当前家具作品" className={`${expanded ? 'fixed inset-0 z-[100] flex' : mobileView === 'model' ? 'flex' : 'hidden lg:flex'} min-h-0 min-w-0 flex-col bg-[#eef1f0]`}>
          <div className="flex shrink-0 flex-wrap items-center justify-between gap-2 border-b border-[#d5dbd7] bg-white px-4 py-3">
            <div className="min-w-0">
              <p className="text-[11px] text-[#68796e]">当前作品 · {props.source === 'structured' ? '模板定制' : '对话建模'}</p>
              <h2 className="mt-1 break-words text-sm font-medium !text-[#26372e]">{props.name}</h2>
              <p className="mt-1 text-[11px] text-[#68796e]">{props.versionLabel}</p>
            </div>
            <div className="flex gap-2">
              <button type="button" className={iconButton} aria-label={props.source === 'structured' ? '模板参数' : '版本与放置'} title={props.source === 'structured' ? '模板参数' : '版本与放置'} aria-expanded={toolsOpen} aria-controls="furniture-workspace-tools" onClick={() => { if (props.source === 'structured') setTemplateVisited(true); setToolsOpen(!toolsOpen); }}><SlidersHorizontal size={18} /></button>
              <button type="button" className={iconButton} aria-label={expanded ? '退出全屏' : '全屏查看'} title={expanded ? '退出全屏' : '全屏查看'} onClick={() => setExpanded(!expanded)}>{expanded ? <Minimize2 size={18} /> : <Maximize2 size={18} />}</button>
            </div>
          </div>
          <div className="relative flex min-h-0 flex-1 flex-col overflow-y-auto lg:flex-row">
            <div className={`relative min-h-[320px] min-w-0 shrink-0 lg:min-h-0 lg:flex-1 lg:h-full ${expanded ? 'h-[calc(100dvh-6rem)]' : 'h-[calc(100dvh-17rem)]'}`} data-testid="furniture-preview">{props.preview}</div>
            <aside hidden={!toolsOpen} id="furniture-workspace-tools" aria-label={props.source === 'structured' ? '模板参数' : '版本与放置'} className="w-full shrink-0 border-l border-[#d5dbd7] bg-[#f4f6f5] lg:w-[320px] lg:overflow-y-auto">
              <div className="flex items-center justify-between px-4 py-2 text-xs"><span className="flex items-center gap-2"><History size={15} />{props.source === 'structured' ? '模板参数 · 独立于对话作品' : '版本与放置'}</span><button type="button" className={iconButton} title="收起工具" aria-label="收起工具" onClick={() => setToolsOpen(false)}><X size={16} /></button></div>
              <div hidden={props.source !== 'structured'}>{templateVisited && props.templateTools}</div>
              <div hidden={props.source !== 'open_geometry'}>{props.geometryTools}</div>
            </aside>
          </div>
        </main>
      </div>
    </div>
  );
}
