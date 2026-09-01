import type { ReactNode } from "react";
import { useLocation } from "react-router-dom";
import { motion } from "framer-motion";
import { ArrowDown, LibraryBig } from "lucide-react";
import { getContentCollection } from "@/lib/contentCollections";

export default function CollectionPage({ children }: { children: ReactNode }) {
  const collection = getContentCollection(useLocation().pathname);

  return (
    <div className="min-h-[calc(100vh-4rem)] bg-[#e9e7de]">
      <section className="home-grid relative overflow-hidden bg-[#0b0f0c] px-5 pt-12 pb-32 text-[#f0eee6] sm:px-8 lg:px-12 lg:pt-16 lg:pb-40">
        <div className="home-noise pointer-events-none absolute inset-0 opacity-25" />
        <div className="relative mx-auto max-w-[1400px]">
          <div className="flex items-center justify-between border-b border-white/10 pb-5 text-[10px] tracking-[0.2em] uppercase">
            <span className="flex items-center gap-2 text-[#d5ff67]"><LibraryBig className="h-3.5 w-3.5" />Haus intelligence library</span>
            <span className="font-mono text-[#747f76]">Collection / {collection.index}</span>
          </div>
          <div className="mt-12 grid gap-12 lg:grid-cols-[1fr_auto] lg:items-end">
            <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.6 }}>
              <p className="font-mono text-[10px] tracking-[0.22em] text-[#99a49a] uppercase">{collection.code}</p>
              <h1 className="mt-5 whitespace-pre-line font-display text-5xl leading-[0.98] tracking-[-0.05em] !text-[#f0eee6] sm:text-6xl lg:text-7xl">{collection.title}</h1>
              <p className="mt-6 max-w-2xl text-sm leading-7 text-[#9aa59b] sm:text-base">{collection.description}</p>
            </motion.div>
            <div className="flex gap-8 border-l border-white/10 pl-8">
              {collection.metrics.map((metric) => <div key={metric.label}><p className="font-mono text-2xl text-[#e7eadf]">{metric.value}</p><p className="mt-1 text-[9px] tracking-[0.15em] text-[#6f7a70] uppercase">{metric.label}</p></div>)}
            </div>
          </div>
          <div className="mt-12 flex items-center gap-2 text-[9px] tracking-[0.18em] text-[#687269] uppercase"><ArrowDown className="h-3.5 w-3.5" />Explore collection</div>
        </div>
      </section>
      <motion.div initial={{ opacity: 0, y: 24 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.55, delay: 0.12 }} className="relative mx-auto -mt-20 max-w-[1400px] px-4 pb-20 sm:px-6">
        <div className="rounded-[2rem] border border-[#1d241f]/15 bg-[#f4f1e9] p-5 shadow-[0_30px_80px_rgb(20_28_22/.12)] sm:p-8">
          {children}
        </div>
      </motion.div>
    </div>
  );
}
