import { useState } from "react";
import { Link } from "react-router-dom";
import { motion } from "framer-motion";
import { ArrowRight, ArrowUpRight, Check, CircleDot, MoveUpRight } from "lucide-react";
import HeroSection from "@/components/home/HeroSection";
import FurnitureModelShowcase from "@/components/home/FurnitureModelShowcase";
import { HOME_EXPERIENCE_STEPS, getHomeExperienceStep } from "@/lib/homeExperience";

const projects = [
  { title: "昼光留白", style: "现代简约", image: "/case_image/modern-minimal-1.webp", meta: "89㎡ / 三口之家" },
  { title: "柔雾客厅", style: "奶油风", image: "/case_image/cream-style-2.webp", meta: "112㎡ / 有宠家庭" },
  { title: "木色秩序", style: "中古风", image: "/case_image/mid-century-3.webp", meta: "76㎡ / 独居空间" },
];

const systemCapabilities = [
  ["01", "Vision", "理解照片与户型图中的空间结构"],
  ["02", "Reasoning", "综合预算、生活习惯与设计约束"],
  ["03", "Spatial", "生成并持续编辑三维家具布局"],
  ["04", "Commerce", "关联真实商品、尺寸与分项报价"],
];

export default function HomePage() {
  const [activeStepIndex, setActiveStepIndex] = useState(0);
  const activeStep = getHomeExperienceStep(activeStepIndex);

  return (
    <div className="overflow-hidden bg-[#ece9df] text-[#171c18]">
      <HeroSection />

      <section className="border-b border-[#1d241f]/15 px-5 py-8 sm:px-8 lg:px-12">
        <div className="mx-auto flex max-w-[1400px] flex-col justify-between gap-5 text-[10px] tracking-[0.2em] text-[#5b655d] uppercase md:flex-row md:items-center">
          <span>Design Intelligence, made tangible.</span>
          <div className="flex flex-wrap gap-x-8 gap-y-2">
            <span>户型识别</span><span>空间推演</span><span>真实商品</span><span>预算交付</span>
          </div>
        </div>
      </section>

      <FurnitureModelShowcase />

      <section className="px-5 py-24 sm:px-8 lg:px-12 lg:py-36">
        <div className="mx-auto max-w-[1400px]">
          <div className="grid gap-12 lg:grid-cols-[0.7fr_1.3fr]">
            <div>
              <p className="text-[10px] tracking-[0.24em] text-[#637064] uppercase">01 / How it thinks</p>
              <h2 className="mt-6 max-w-md font-display text-4xl leading-[1.08] font-medium tracking-[-0.04em] sm:text-5xl lg:text-6xl">不是一次生成，<br />是一场空间推演。</h2>
            </div>
            <p className="max-w-2xl self-end text-base leading-8 text-[#606961] lg:text-lg">传统效果图只回答“好不好看”。我们的 AI 同时回答空间是否合理、家具能否放下、预算花在哪里，以及下一步如何落地。</p>
          </div>

          <div className="mt-16 grid overflow-hidden border border-[#1d241f]/15 lg:grid-cols-[0.78fr_1.22fr]">
            <div className="divide-y divide-[#1d241f]/15 border-[#1d241f]/15 lg:border-r">
              {HOME_EXPERIENCE_STEPS.map((step, index) => (
                <button key={step.id} type="button" onClick={() => setActiveStepIndex(index)} className={`group flex w-full items-center gap-5 px-5 py-5 text-left transition-colors sm:px-7 ${activeStepIndex === index ? "bg-[#182019] text-[#f0eee6]" : "hover:bg-[#e2dfd4]"}`}>
                  <span className={`font-mono text-xs ${activeStepIndex === index ? "text-[#d5ff67]" : "text-[#7b867d]"}`}>{step.index}</span>
                  <span className="flex-1 text-sm font-medium">{step.eyebrow}</span>
                  <ArrowUpRight className={`h-4 w-4 transition-transform ${activeStepIndex === index ? "rotate-45 text-[#d5ff67]" : "text-[#89928a] group-hover:rotate-45"}`} />
                </button>
              ))}
            </div>

            <motion.div key={activeStep.id} initial={{ opacity: 0, x: 18 }} animate={{ opacity: 1, x: 0 }} transition={{ duration: 0.35 }} className="relative min-h-[440px] bg-[#d9d8ce] p-7 sm:p-10 lg:p-14">
              <div className="home-plan-grid pointer-events-none absolute inset-0 opacity-60" />
              <div className="relative flex h-full flex-col justify-between">
                <div className="flex items-start justify-between gap-8">
                  <div><p className="text-[10px] tracking-[0.2em] text-[#677168] uppercase">{activeStep.eyebrow} / Phase {activeStep.index}</p><h3 className="mt-6 whitespace-pre-line font-display text-4xl leading-[1.05] tracking-[-0.04em] sm:text-5xl">{activeStep.title}</h3></div>
                  <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full border border-[#1c251e]/20"><CircleDot className="h-4 w-4" /></span>
                </div>
                <div className="mt-16 grid gap-8 sm:grid-cols-[1fr_auto] sm:items-end">
                  <div><p className="max-w-xl text-sm leading-7 text-[#59625b] sm:text-base">{activeStep.description}</p><div className="mt-6 flex flex-wrap gap-2">{activeStep.annotations.map((item) => <span key={item} className="rounded-full border border-[#1d241f]/15 bg-[#e7e5dc]/75 px-3 py-1.5 text-[10px] tracking-[0.08em]">{item}</span>)}</div></div>
                  <div className="border-l border-[#1d241f]/20 pl-6"><p className="font-mono text-3xl tracking-[-0.06em]">{activeStep.metric.value}</p><p className="mt-1 max-w-24 text-[9px] leading-4 tracking-[0.14em] text-[#6e796f] uppercase">{activeStep.metric.label}</p></div>
                </div>
              </div>
            </motion.div>
          </div>
        </div>
      </section>

      <section className="bg-[#111713] px-5 py-24 text-[#eeeae0] sm:px-8 lg:px-12 lg:py-36">
        <div className="mx-auto max-w-[1400px]">
          <div className="flex flex-col justify-between gap-8 md:flex-row md:items-end">
            <div><p className="text-[10px] tracking-[0.24em] text-[#9aa59a] uppercase">02 / Spatial archive</p><h2 className="mt-6 font-display text-4xl leading-none tracking-[-0.04em] sm:text-6xl">被理解的空间，<br /><span className="text-[#899389] italic">才有自己的样子。</span></h2></div>
            <Link to="/styles" className="group inline-flex items-center gap-8 border-b border-white/25 pb-3 text-sm text-[#c9d0c8]">查看全部空间档案<ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-2" /></Link>
          </div>

          <div className="mt-16 grid gap-px bg-white/10 md:grid-cols-3">
            {projects.map((project, index) => (
              <motion.article key={project.title} initial={{ opacity: 0, y: 24 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true, margin: "-10%" }} transition={{ delay: index * 0.08 }} className="group bg-[#111713]">
                <Link to="/styles" className="block">
                  <div className="relative aspect-[4/5] overflow-hidden bg-[#222a23]">
                    <img src={project.image} alt={`${project.title}${project.style}家装方案`} className="h-full w-full object-cover opacity-85 saturate-[.75] transition duration-700 group-hover:scale-[1.035] group-hover:opacity-100 group-hover:saturate-100" />
                    <div className="absolute inset-0 bg-gradient-to-t from-[#0b0f0c]/70 via-transparent to-transparent" />
                    <span className="absolute top-5 left-5 font-mono text-[10px] tracking-[0.18em] text-white/70">PROJECT / 0{index + 1}</span>
                    <span className="absolute right-5 bottom-5 flex h-11 w-11 items-center justify-center rounded-full bg-[#d5ff67] text-[#11150f] opacity-0 transition duration-300 group-hover:opacity-100"><MoveUpRight className="h-4 w-4" /></span>
                  </div>
                  <div className="flex items-start justify-between gap-4 border-x border-b border-white/10 p-5"><div><h3 className="font-display text-2xl text-[#eeece4]">{project.title}</h3><p className="mt-1 text-xs text-[#818d82]">{project.meta}</p></div><span className="rounded-full border border-white/15 px-2.5 py-1 text-[10px] text-[#b8c1b7]">{project.style}</span></div>
                </Link>
              </motion.article>
            ))}
          </div>
        </div>
      </section>

      <section className="px-5 py-24 sm:px-8 lg:px-12 lg:py-36">
        <div className="mx-auto grid max-w-[1400px] gap-16 lg:grid-cols-[0.75fr_1.25fr]">
          <div><p className="text-[10px] tracking-[0.24em] text-[#637064] uppercase">03 / One connected system</p><h2 className="mt-6 font-display text-4xl leading-[1.08] tracking-[-0.04em] sm:text-6xl">从一张照片，<br />到一份真实提案。</h2><p className="mt-7 max-w-md text-sm leading-7 text-[#626c64]">视觉模型、空间规则、生成式 AI 与自有商品库在同一条链路上工作，让设计不再止步于一张漂亮图片。</p></div>
          <div className="border-t border-[#1d241f]/20">
            {systemCapabilities.map(([index, title, description]) => <div key={index} className="group grid grid-cols-[48px_100px_1fr_auto] items-center gap-3 border-b border-[#1d241f]/20 py-6 sm:grid-cols-[70px_150px_1fr_auto]"><span className="font-mono text-[10px] text-[#778178]">{index}</span><span className="font-mono text-xs tracking-[0.12em] uppercase">{title}</span><span className="text-sm leading-6 text-[#69736b]">{description}</span><Check className="h-4 w-4 text-[#53624f] transition-transform group-hover:scale-125" /></div>)}
          </div>
        </div>
      </section>

      <section className="px-4 pb-4 sm:px-6 sm:pb-6">
        <div className="home-grid relative mx-auto max-w-[1500px] overflow-hidden rounded-[2rem] bg-[#bd5b38] px-6 py-20 text-[#fff4e8] sm:px-12 lg:px-20 lg:py-28">
          <div className="home-noise pointer-events-none absolute inset-0 opacity-20" />
          <div className="relative grid gap-12 lg:grid-cols-[1fr_auto] lg:items-end">
            <div><p className="text-[10px] tracking-[0.24em] text-[#ffd9c8] uppercase">Your home, before it exists.</p><h2 className="mt-6 max-w-4xl font-display text-5xl leading-[0.98] tracking-[-0.055em] sm:text-7xl lg:text-8xl">先让 AI 看见，<br />再让理想发生。</h2></div>
            <Link to="/design/new" className="group flex h-32 w-32 flex-col justify-between rounded-full bg-[#f7f0e5] p-6 text-[#291811] transition-transform hover:rotate-6 sm:h-40 sm:w-40"><ArrowUpRight className="ml-auto h-6 w-6 transition-transform group-hover:rotate-45" /><span className="text-sm font-semibold">创建我的<br />家装方案</span></Link>
          </div>
        </div>
      </section>
    </div>
  );
}
