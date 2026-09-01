import type { ReactNode } from "react";
import { useLocation } from "react-router-dom";
import { motion } from "framer-motion";
import { Activity, CircleDot } from "lucide-react";
import { DESIGN_JOURNEY, getJourneyStage } from "@/lib/designJourney";

export default function StudioPage({
  title,
  description,
  children,
  width = "wide",
}: {
  title: string;
  description: string;
  children: ReactNode;
  width?: "medium" | "wide";
}) {
  const stage = getJourneyStage(useLocation().pathname);
  const maxWidth = width === "medium" ? "max-w-5xl" : "max-w-[1400px]";

  return (
    <div className="min-h-[calc(100vh-4rem)] bg-[#e9e7de]">
      <section className="home-grid relative overflow-hidden bg-[#0b0f0c] px-5 pt-12 pb-32 text-[#f0eee6] sm:px-8 lg:px-12 lg:pt-16 lg:pb-40">
        <div className="home-noise pointer-events-none absolute inset-0 opacity-30" />
        <div className={`relative mx-auto ${maxWidth}`}>
          <div className="flex flex-wrap items-center justify-between gap-5 border-b border-white/10 pb-5">
            <div className="flex items-center gap-2 text-[10px] tracking-[0.2em] text-[#d5ff67] uppercase">
              <Activity className="h-3.5 w-3.5" />
              Design session / Active
            </div>
            <div className="font-mono text-[10px] tracking-[0.18em] text-[#778279] uppercase">
              Phase {stage.index} · {stage.technicalLabel}
            </div>
          </div>

          <div className="mt-10 grid gap-10 lg:grid-cols-[1fr_0.8fr] lg:items-end">
            <motion.div initial={{ opacity: 0, y: 18 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.55 }}>
              <p className="text-[10px] tracking-[0.22em] text-[#98a399] uppercase">{stage.label} / {stage.index}</p>
              <h1 className="mt-4 max-w-3xl font-display text-4xl leading-[1.04] font-medium tracking-[-0.045em] !text-[#f0eee6] sm:text-5xl lg:text-6xl">{title}</h1>
              <p className="mt-5 max-w-2xl text-sm leading-7 text-[#9da79e] sm:text-base">{description}</p>
            </motion.div>

            <div className="grid grid-cols-4 gap-px bg-white/10">
              {DESIGN_JOURNEY.map((item) => {
                const reached = item.progress <= stage.progress;
                const current = item.path === stage.path;
                return (
                  <div key={item.path} className={`min-h-24 p-3 ${reached ? "bg-[#171e18]" : "bg-[#0e130f]"}`}>
                    <div className="flex items-center justify-between">
                      <span className={`font-mono text-[10px] ${current ? "text-[#d5ff67]" : "text-[#667168]"}`}>{item.index}</span>
                      {current && <CircleDot className="h-3 w-3 text-[#d5ff67]" />}
                    </div>
                    <p className={`mt-7 text-[10px] leading-4 ${reached ? "text-[#c4ccc4]" : "text-[#59625a]"}`}>{item.label}</p>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </section>

      <motion.div initial={{ opacity: 0, y: 24 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.55, delay: 0.12 }} className={`relative mx-auto -mt-20 px-4 pb-20 sm:px-6 ${maxWidth}`}>
        {children}
      </motion.div>
    </div>
  );
}
