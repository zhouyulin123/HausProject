import { Link } from "react-router-dom";
import { motion } from "framer-motion";
import { ArrowRight, Lamp, PawPrint, ScanLine, Sofa, Sparkles } from "lucide-react";
import Button from "@/components/common/Button";
import Tag from "@/components/common/Tag";

const trustStats = [
  { value: "12,000+", label: "套灵感方案" },
  { value: "30+", label: "家装风格" },
  { value: "预算 · 户型 · 生活习惯", label: "综合分析" },
];

export default function HeroSection() {
  return (
    <section className="relative overflow-hidden">
      {/* 背景柔和光斑 */}
      <div className="pointer-events-none absolute -top-24 -right-24 h-96 w-96 rounded-full bg-terra-100/70 blur-3xl" />
      <div className="pointer-events-none absolute top-40 -left-32 h-80 w-80 rounded-full bg-sage-100/80 blur-3xl" />

      <div className="relative mx-auto grid max-w-7xl items-center gap-12 px-4 py-16 sm:px-6 lg:grid-cols-2 lg:py-24">
        {/* 左侧文案 */}
        <motion.div
          initial={{ opacity: 0, y: 28 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, ease: "easeOut" }}
        >
          <span className="inline-flex items-center gap-1.5 rounded-full border border-sage-200 bg-sage-50 px-3.5 py-1.5 text-xs font-medium text-sage-700">
            <Sparkles className="h-3.5 w-3.5" />
            AI 驱动的家装定制平台
          </span>
          <h1 className="mt-6 text-4xl leading-tight font-semibold sm:text-5xl sm:leading-[1.2]">
            让 AI 为你
            <br />
            定制理想中的<span className="text-sage-600">家</span>
          </h1>
          <p className="mt-5 max-w-lg text-base leading-relaxed text-stone-500 sm:text-lg">
            输入户型、预算与生活习惯，智能生成空间布局、家具搭配与装修方案。让
            AI 先帮你看见家的样子。
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <Link to="/customize">
              <Button size="lg">
                立即开始定制
                <ArrowRight className="h-4 w-4" />
              </Button>
            </Link>
            <Link to="/styles">
              <Button variant="outline" size="lg">
                查看设计案例
              </Button>
            </Link>
          </div>
          <div className="mt-10 flex flex-wrap gap-x-10 gap-y-4">
            {trustStats.map((s) => (
              <div key={s.label}>
                <div className="font-display text-lg font-semibold text-stone-800">
                  {s.value}
                </div>
                <div className="mt-0.5 text-xs text-stone-400">{s.label}</div>
              </div>
            ))}
          </div>
        </motion.div>

        {/* 右侧方案预览卡片 */}
        <motion.div
          initial={{ opacity: 0, y: 28 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.15, ease: "easeOut" }}
          className="relative mx-auto w-full max-w-md"
        >
          <div className="rounded-3xl bg-white p-3 shadow-lift">
            {/* 室内空间占位图 */}
            <div className="relative h-56 overflow-hidden rounded-2xl bg-gradient-to-br from-[#f7efe2] via-[#ecd9bd] to-[#cfae83] sm:h-64">
              {/* 简单的室内插画：窗 + 沙发 + 灯 */}
              <div className="absolute top-6 left-7 h-24 w-20 rounded-t-full border-4 border-white/70 bg-gradient-to-b from-[#fdf6e9] to-[#f3dfc0]" />
              <div className="absolute right-8 bottom-14 flex items-end gap-2">
                <Lamp className="h-14 w-14 text-wood-700/70" strokeWidth={1.2} />
              </div>
              <div className="absolute bottom-10 left-10">
                <Sofa className="h-24 w-24 text-wood-700/80" strokeWidth={1.1} />
              </div>
              <div className="absolute right-0 bottom-0 left-0 h-8 bg-wood-500/25" />
            </div>
            <div className="px-3 pt-4 pb-3">
              <div className="flex items-center justify-between">
                <h3 className="font-display text-lg font-semibold text-stone-800">
                  奶油原木客厅方案
                </h3>
                <Tag tone="sage">匹配度 98%</Tag>
              </div>
              <div className="mt-2 flex items-center gap-2 text-sm text-stone-500">
                <span className="font-semibold text-terra-600">预算 ¥86,000</span>
                <span className="text-stone-300">|</span>
                <span>三口之家 / 有宠物 / 高收纳</span>
              </div>
              <div className="mt-3 flex flex-wrap gap-1.5">
                <Tag tone="wood">奶油风</Tag>
                <Tag tone="wood">原木风</Tag>
                <Tag tone="wood">现代简约</Tag>
              </div>
            </div>
          </div>

          {/* 浮动小卡片 */}
          <motion.div
            className="absolute -top-5 -left-4 flex items-center gap-2 rounded-2xl bg-white/90 px-3.5 py-2.5 text-xs font-medium text-stone-600 shadow-card backdrop-blur sm:-left-10"
            animate={{ y: [0, -8, 0] }}
            transition={{ duration: 5, repeat: Infinity, ease: "easeInOut" }}
          >
            <ScanLine className="h-4 w-4 text-sage-600" />
            AI 正在分析采光
          </motion.div>
          <motion.div
            className="absolute -right-3 top-1/3 flex items-center gap-2 rounded-2xl bg-white/90 px-3.5 py-2.5 text-xs font-medium text-stone-600 shadow-card backdrop-blur sm:-right-8"
            animate={{ y: [0, -10, 0] }}
            transition={{ duration: 6, repeat: Infinity, ease: "easeInOut", delay: 0.8 }}
          >
            <PawPrint className="h-4 w-4 text-terra-500" />
            已优化收纳动线
          </motion.div>
          <motion.div
            className="absolute -bottom-4 left-10 flex items-center gap-2 rounded-2xl bg-white/90 px-3.5 py-2.5 text-xs font-medium text-stone-600 shadow-card backdrop-blur"
            animate={{ y: [0, -6, 0] }}
            transition={{ duration: 4.5, repeat: Infinity, ease: "easeInOut", delay: 1.6 }}
          >
            <Sofa className="h-4 w-4 text-wood-600" />
            推荐 6 件家具
          </motion.div>
        </motion.div>
      </div>
    </section>
  );
}
