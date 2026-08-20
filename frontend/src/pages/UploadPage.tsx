import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowRight, LayoutTemplate, Sofa, BedDouble } from "lucide-react";
import UploadPanel from "@/components/upload/UploadPanel";
import AnalysisResult from "@/components/upload/AnalysisResult";
import RoomCalibration from "@/components/upload/RoomCalibration";
import type { AnalysisStatus } from "@/components/upload/AnalysisResult";
import PageTitle from "@/components/common/PageTitle";
import Button from "@/components/common/Button";
import { analyzeRoomImage } from "@/api/designApi";
import { useRoomModelStore } from "@/store/useRoomModelStore";
import type { ImageAnalysis } from "@/types/requirement";

const examples = [
  {
    icon: LayoutTemplate,
    title: "户型图",
    description: "识别空间比例与动线",
    gradient: "from-[#eef0ea] to-[#ccd6c2]",
    mockName: "示例_三室两厅户型图.png",
  },
  {
    icon: Sofa,
    title: "客厅照片",
    description: "分析采光与家具摆放",
    gradient: "from-[#f7efe2] to-[#dcc09a]",
    mockName: "示例_客厅照片.jpg",
  },
  {
    icon: BedDouble,
    title: "卧室照片",
    description: "评估收纳与布局潜力",
    gradient: "from-[#f4ece4] to-[#d9bcaa]",
    mockName: "示例_卧室照片.jpg",
  },
];

interface UploadedFile {
  name: string;
  size: string;
}

export default function UploadPage() {
  const navigate = useNavigate();
  const [uploaded, setUploaded] = useState<UploadedFile | null>(null);
  const [status, setStatus] = useState<AnalysisStatus>("waiting");
  const [analysis, setAnalysis] = useState<ImageAnalysis | null>(null);

  const runAnalysis = async (file: File) => {
    setUploaded({
      name: file.name,
      size:
        file.size > 1024 * 1024
          ? `${(file.size / 1024 / 1024).toFixed(1)} MB`
          : `${Math.max(1, Math.round(file.size / 1024))} KB`,
    });
    setStatus("waiting");
    setAnalysis(null);
    // 模拟「等待分析 → 分析中 → 已完成」状态流转
    setTimeout(() => setStatus("analyzing"), 400);
    const result = await analyzeRoomImage(file);
    setAnalysis(result);
    useRoomModelStore.getState().setRoomModel(result.roomModel ?? null);
    setStatus("done");
  };

  const runExample = (name: string) => {
    // 用示例卡片模拟一次上传
    const fakeFile = new File([new Uint8Array(256 * 1024)], name, {
      type: "image/png",
    });
    void runAnalysis(fakeFile);
  };

  return (
    <div className="mx-auto max-w-4xl px-4 py-10 sm:px-6">
      <PageTitle
        title="上传户型图或房间照片"
        description="上传户型图后，AI 可以更准确地识别空间比例、动线和家具摆放方式。也可以暂时跳过，直接与 AI 沟通需求。"
      />

      <div className="mt-8 space-y-6">
        <UploadPanel onFile={runAnalysis} />

        {!uploaded && (
          <div>
            <p className="mb-3 text-sm font-semibold text-stone-600">
              没有合适的图片？点击示例体验 AI 识别：
            </p>
            <div className="grid gap-4 sm:grid-cols-3">
              {examples.map((example) => (
                <button
                  key={example.title}
                  type="button"
                  onClick={() => runExample(example.mockName)}
                  className="group overflow-hidden rounded-3xl border border-cream-200 bg-white/70 text-left transition-all hover:-translate-y-1 hover:shadow-soft"
                >
                  <div
                    className={`flex h-28 items-center justify-center bg-gradient-to-br ${example.gradient}`}
                  >
                    <example.icon
                      className="h-10 w-10 text-stone-500/60 transition-transform group-hover:scale-110"
                      strokeWidth={1.3}
                    />
                  </div>
                  <div className="p-4">
                    <h3 className="text-sm font-semibold text-stone-700">
                      {example.title}
                    </h3>
                    <p className="mt-1 text-xs text-stone-400">{example.description}</p>
                  </div>
                </button>
              ))}
            </div>
          </div>
        )}

        {uploaded && (
          <AnalysisResult
            fileName={uploaded.name}
            fileSize={uploaded.size}
            status={status}
            analysis={analysis}
          />
        )}

        {uploaded && analysis?.roomModel && (
          <RoomCalibration
            analysis={analysis}
            onCalibrated={(roomModel) => {
              setAnalysis((prev) => (prev ? { ...prev, roomModel } : prev));
              useRoomModelStore.getState().setRoomModel(roomModel);
            }}
          />
        )}

        <div className="flex flex-col-reverse items-center justify-between gap-3 border-t border-cream-200 pt-6 sm:flex-row">
          <Button variant="ghost" onClick={() => navigate("/chat")}>
            暂时跳过，直接与 AI 沟通
          </Button>
          <Button
            onClick={() => navigate("/chat")}
            disabled={Boolean(uploaded) && status !== "done"}
            className="w-full sm:w-auto"
          >
            下一步：确认需求
            <ArrowRight className="h-4 w-4" />
          </Button>
        </div>
      </div>
    </div>
  );
}
