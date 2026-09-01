export type ContentCollection = {
  path: "/styles" | "/furniture" | "/my-designs";
  index: string;
  code: string;
  title: string;
  description: string;
  metrics: readonly { value: string; label: string }[];
};

export const CONTENT_COLLECTIONS: readonly ContentCollection[] = [
  {
    path: "/styles",
    index: "01",
    code: "SPATIAL ARCHIVE",
    title: "风格不是标签，\n是空间的性格。",
    description: "从光线、色彩、材质和生活方式理解每一种风格，找到真正适合你的空间语言。",
    metrics: [{ value: "08", label: "风格母版" }, { value: "24", label: "真实空间案例" }],
  },
  {
    path: "/furniture",
    index: "02",
    code: "MATERIAL INDEX",
    title: "每一件家具，\n都是空间参数。",
    description: "尺寸、材质、价格与适用场景共同决定匹配度。这里收录的是可以进入真实方案的产品，而非装饰图片。",
    metrics: [{ value: "40+", label: "参数化产品" }, { value: "1:1", label: "真实尺寸关联" }],
  },
  {
    path: "/my-designs",
    index: "03",
    code: "DESIGN VERSIONS",
    title: "保存每一次，\n空间的演进。",
    description: "集中管理生成、优化和导出的设计版本，让每次决定都有上下文，也随时可以继续。",
    metrics: [{ value: "∞", label: "持续迭代" }, { value: "PDF", label: "提案可交付" }],
  },
] as const;

export function getContentCollection(pathname: string): ContentCollection {
  return CONTENT_COLLECTIONS.find((item) => item.path === pathname) ?? CONTENT_COLLECTIONS[0];
}
