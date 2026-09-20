import { renderToStaticMarkup } from "react-dom/server";
import { describe, it, expect } from "vitest";
import HomeDesignCanvas from "./HomeDesignCanvas";
import type { SpatialDocument } from "@/types/spatial";
import type { HomeDesignDocument } from "@/types/homeDesign";
const space: SpatialDocument = {
  schema_version: "spatial/1.0",
  unit: "m",
  source_image_id: null,
  scale_status: "confirmed",
  rooms: [
    {
      id: "r1",
      name: "客厅",
      height: 2.8,
      polygon: [
        { x: 0, z: 0 },
        { x: 4, z: 0 },
        { x: 4, z: 4 },
        { x: 0, z: 4 },
      ],
    },
    {
      id: "r2",
      name: "卧室",
      height: 2.8,
      polygon: [
        { x: 4, z: 0 },
        { x: 8, z: 0 },
        { x: 8, z: 4 },
        { x: 4, z: 4 },
      ],
    },
  ],
  walls: [],
  openings: [],
};
const document: HomeDesignDocument = {
  schema_version: "home-design/1.0",
  space_version: 1,
  surfaces: [
    {
      id: "s",
      room_id: "r1",
      kind: "floor",
      wall_id: null,
      material: { name: "蓝", color: "#123456" },
    },
  ],
  objects: [
    {
      id: "o",
      name: "座椅",
      room_id: "r1",
      category: "furniture",
      position: { x: 2, y: 0, z: 2 },
      size: { width: 1, height: 1, depth: 1 },
      rotation: 30,
      material: { name: "木", color: "#abcdef" },
    },
  ],
};
describe("家装同源二维画布", () => {
  it("位置、旋转和材料来自文档", () => {
    const html = renderToStaticMarkup(
      <HomeDesignCanvas
        space={space}
        document={document}
        roomId=""
        mode="2d"
        selected="o"
        onSelect={() => {}}
        showCeiling={false}
      />,
    );
    expect(html).toContain("translate(2 2) rotate(-30)");
    expect(html).toContain("#123456");
    expect(html).toContain("选择座椅");
  });
  it("按房间过滤物件并保留全局坐标", () => {
    const html = renderToStaticMarkup(
      <HomeDesignCanvas
        space={space}
        document={document}
        roomId="r2"
        mode="2d"
        selected={null}
        onSelect={() => {}}
        showCeiling={false}
      />,
    );
    expect(html).not.toContain("选择座椅");
    expect(html).toContain("4,0 8,0");
  });
});
