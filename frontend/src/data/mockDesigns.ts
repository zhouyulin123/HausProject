import type { DesignPlan } from "@/types/design";
import { mockFurniture } from "./mockFurniture";

const pick = (...ids: string[]) =>
  ids.map((id) => mockFurniture.find((f) => f.id === id)!).filter(Boolean);

export const mockDesigns: DesignPlan[] = [
  {
    id: "plan-a",
    name: "暖居 · 奶油原木风",
    style: "奶油原木风",
    coverGradient:
      "bg-gradient-to-br from-[#f7efe2] via-[#ecd9bd] to-[#cfae83]",
    score: 98,
    budget: 86000,
    tags: ["奶油白", "原木", "高收纳", "柔和灯光"],
    suitableFor: ["小家庭", "宠物家庭", "喜欢温馨感"],
    description:
      "以奶油白为主色，搭配浅木色家具和低饱和软装，营造温暖、放松、耐看的居住氛围。整屋以收纳为骨架、灯光为氛围，适合每天回家想「松一口气」的家庭。",
    layoutSuggestions: [
      "客厅采用开放式布局，减少视觉阻隔，让采光贯穿全屋",
      "沙发靠墙摆放，释放中间活动空间，给孩子和宠物留出活动区",
      "电视墙结合整面收纳柜，提高空间利用率",
      "餐厅与客厅保持视觉连贯，使用同色系家具统一风格",
      "玄关增加顶天立地柜，进门动线上解决鞋帽收纳",
    ],
    furnitureSuggestions: pick("f1", "f2", "f3", "f8", "f11", "f7"),
    colorPalette: [
      { name: "奶油白", hex: "#F5EFE3", usage: "墙面" },
      { name: "浅木色", hex: "#D2B48C", usage: "柜体" },
      { name: "暖灰色", hex: "#B8B0A4", usage: "沙发" },
      { name: "亚麻米色", hex: "#E8DFCA", usage: "窗帘" },
      { name: "鼠尾草绿", hex: "#9CAF88", usage: "点缀色" },
    ],
    materials: [
      {
        name: "木饰面",
        description: "墙面与柜体过渡自然，增加温润感",
        gradient: "bg-gradient-to-br from-[#dfc59e] to-[#b3906327]",
      },
      {
        name: "棉麻布艺",
        description: "沙发与窗帘主材，亲肤透气",
        gradient: "bg-gradient-to-br from-[#f0e9da] to-[#d8cdb4]",
      },
      {
        name: "微水泥",
        description: "局部地面与台面，耐磨易打理",
        gradient: "bg-gradient-to-br from-[#e4e0d8] to-[#c2bcb0]",
      },
      {
        name: "哑光金属",
        description: "灯具与五金点缀，克制的精致感",
        gradient: "bg-gradient-to-br from-[#d9d4c8] to-[#a49c8c]",
      },
      {
        name: "柔光玻璃",
        description: "餐边柜门板，隐约展示不显乱",
        gradient: "bg-gradient-to-br from-[#f2f1ec] to-[#d5d3c9]",
      },
    ],
    lightingSuggestions: [
      { name: "无主灯筒灯", purpose: "基础照明", description: "4000K 均匀铺光，天花更干净" },
      { name: "柜体灯带", purpose: "氛围照明", description: "藏于收纳柜与吊顶，拉出空间层次" },
      { name: "落地灯", purpose: "局部照明", description: "沙发阅读角的暖光补充" },
      { name: "餐桌吊灯", purpose: "功能照明", description: "离桌面 75cm，聚拢用餐氛围" },
    ],
    budgetBreakdown: [
      { name: "硬装", percent: 40, amount: 34400 },
      { name: "定制柜", percent: 25, amount: 21500 },
      { name: "家具", percent: 20, amount: 17200 },
      { name: "软装", percent: 10, amount: 8600 },
      { name: "灯具与智能设备", percent: 5, amount: 4300 },
    ],
    aiTips: [
      "如果希望进一步降低预算，可以优先减少木饰面上墙的面积，用乳胶漆同色替代。",
      "家中有儿童时，建议茶几与柜体边角采用圆角设计。",
      "有宠物的家庭，建议选择耐抓、易清洁的科技布或猫抓布沙发面料。",
    ],
  },
  {
    id: "plan-b",
    name: "留白 · 现代简约风",
    style: "现代简约风",
    coverGradient:
      "bg-gradient-to-br from-[#eeece7] via-[#d8d4cc] to-[#a8a296]",
    score: 93,
    budget: 72000,
    tags: ["暖灰", "简洁线条", "隐藏收纳", "模块家具"],
    suitableFor: ["预算控制", "喜欢干净利落空间", "小户型"],
    description:
      "用暖灰与米白构建安静的底色，减少造型、强调线条与留白。收纳全部隐入墙面，家具选择可灵活重组的模块化款式，预算集中花在「每天都摸得到」的地方。",
    layoutSuggestions: [
      "取消复杂吊顶，用无主灯设计保持天花简洁",
      "定制柜全部通顶且与墙面同色，视觉上「消失」",
      "选用模块化沙发，未来换房或调整布局可重新组合",
      "走廊尽头设置端景，让动线有视觉落点",
    ],
    furnitureSuggestions: pick("f6", "f7", "f10", "f11", "f3", "f5"),
    colorPalette: [
      { name: "米白", hex: "#F2EFE9", usage: "墙面" },
      { name: "暖灰", hex: "#C7C1B6", usage: "柜体" },
      { name: "浅咖", hex: "#A89880", usage: "沙发" },
      { name: "燕麦色", hex: "#E5DED2", usage: "窗帘" },
      { name: "哑黑", hex: "#4A4741", usage: "点缀色" },
    ],
    materials: [
      {
        name: "哑光烤漆板",
        description: "柜体门板，纯净利落不反光",
        gradient: "bg-gradient-to-br from-[#efece6] to-[#cfc9be]",
      },
      {
        name: "岩板",
        description: "台面与餐桌，耐用零维护",
        gradient: "bg-gradient-to-br from-[#e6e3dd] to-[#b6b1a7]",
      },
      {
        name: "短绒地毯",
        description: "柔化大面积硬质表面",
        gradient: "bg-gradient-to-br from-[#e2ddd2] to-[#c0b9a9]",
      },
      {
        name: "细框金属",
        description: "灯具与门框线条，克制的工业感",
        gradient: "bg-gradient-to-br from-[#d5d2cb] to-[#8f8a80]",
      },
    ],
    lightingSuggestions: [
      { name: "磁吸轨道灯", purpose: "基础照明", description: "灯位可随家具布局调整" },
      { name: "窗帘盒灯带", purpose: "氛围照明", description: "夜晚模拟自然光洗墙" },
      { name: "壁灯", purpose: "局部照明", description: "床头与走廊，替代床头柜台灯" },
      { name: "感应地脚灯", purpose: "功能照明", description: "夜间起夜的柔和指引" },
    ],
    budgetBreakdown: [
      { name: "硬装", percent: 42, amount: 30240 },
      { name: "定制柜", percent: 26, amount: 18720 },
      { name: "家具", percent: 18, amount: 12960 },
      { name: "软装", percent: 8, amount: 5760 },
      { name: "灯具与智能设备", percent: 6, amount: 4320 },
    ],
    aiTips: [
      "简约风格对施工平整度要求更高，建议在墙面基层处理上不要压缩预算。",
      "全屋同色系时，可通过材质差异（布艺 / 木 / 金属）避免单调。",
      "若经常在家办公，建议为书桌区单独增加 4000K 功能照明。",
    ],
  },
  {
    id: "plan-c",
    name: "微醺 · 轻奢质感风",
    style: "轻奢质感风",
    coverGradient:
      "bg-gradient-to-br from-[#efe6dc] via-[#d9c3ae] to-[#9b7d63]",
    score: 89,
    budget: 128000,
    tags: ["石材", "金属", "皮革", "氛围灯"],
    suitableFor: ["追求品质感", "大户型", "注重材质"],
    description:
      "以暖调石材与皮革构建质感基底，金属线条勾勒轮廓，层次丰富的灯光让夜晚的家像一间安静的酒店大堂。适合在意细节、愿意为材质买单的家庭。",
    layoutSuggestions: [
      "客厅采用对称式布局，强化仪式感与秩序感",
      "沙发区下沉式地毯界定，搭配双侧边几",
      "背景墙采用大板岩板 + 灯带悬浮设计",
      "餐厅设置整面酒柜 / 展示柜，玻璃门内藏灯",
    ],
    furnitureSuggestions: pick("f11", "f12", "f6", "f8", "f9", "f7"),
    colorPalette: [
      { name: "暖白", hex: "#F1ECE4", usage: "墙面" },
      { name: "浅驼色", hex: "#C9AE8F", usage: "柜体" },
      { name: "焦糖棕", hex: "#9C6B45", usage: "沙发" },
      { name: "香槟金", hex: "#CDB287", usage: "点缀色" },
      { name: "墨绿", hex: "#3F5548", usage: "背景墙" },
    ],
    materials: [
      {
        name: "大板岩板",
        description: "背景墙与台面，大气整面无拼缝",
        gradient: "bg-gradient-to-br from-[#e9e2d8] to-[#b4a08f]",
      },
      {
        name: "头层皮革",
        description: "沙发与单椅，随使用愈发温润",
        gradient: "bg-gradient-to-br from-[#d2a97f] to-[#96683f]",
      },
      {
        name: "拉丝黄铜",
        description: "灯具、五金与家具脚的金色线条",
        gradient: "bg-gradient-to-br from-[#e3cb9a] to-[#b08d55]",
      },
      {
        name: "绒布",
        description: "窗帘与抱枕，浓郁的垂坠感",
        gradient: "bg-gradient-to-br from-[#cbb9a5] to-[#8d7660]",
      },
    ],
    lightingSuggestions: [
      { name: "分子吊灯", purpose: "基础照明", description: "客厅视觉中心，兼顾造型" },
      { name: "洗墙灯带", purpose: "氛围照明", description: "突出石材与木饰面的肌理" },
      { name: "床头吊线灯", purpose: "局部照明", description: "取代台灯，释放床头柜台面" },
      { name: "酒柜射灯", purpose: "功能照明", description: "展示层板重点打光" },
    ],
    budgetBreakdown: [
      { name: "硬装", percent: 38, amount: 48640 },
      { name: "定制柜", percent: 24, amount: 30720 },
      { name: "家具", percent: 22, amount: 28160 },
      { name: "软装", percent: 9, amount: 11520 },
      { name: "灯具与智能设备", percent: 7, amount: 8960 },
    ],
    aiTips: [
      "如果希望降低预算，可优先减少石材与复杂吊顶，保留灯光设计即可保住氛围。",
      "皮革家具在有宠物的家庭中易留抓痕，可局部替换为绒布或科技布。",
      "轻奢风格建议控制金属点缀的比例在 10% 以内，避免显「金」。",
    ],
  },
];
