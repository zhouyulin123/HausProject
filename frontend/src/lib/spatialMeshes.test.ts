import { describe,expect,it } from "vitest";
import { wallPieces } from "./spatialMeshes";
describe("墙体真实开口",() => {
  it("门洞从地面挖空，窗洞保留窗台和过梁",() => {
    const wall={ id: "w",start: { x: 0,z: 0 },end: { x: 4,z: 0 },height: 3,thickness: 0.2,room_ids: ["r"] };
    const pieces=wallPieces(wall,[{ id: "door",wall_id: "w",type: "door",offset: 1,width: 1,height: 2,sill_height: 0 },{ id: "window",wall_id: "w",type: "window",offset: 3,width: 0.5,height: 1,sill_height: 1 }]);
    const volume=pieces.reduce((s,p) => s+p.width*p.height*wall.thickness,0);
    expect(volume).toBeCloseTo((4*3-1*2-0.5*1)*0.2);
    expect(pieces.some(p => p.x>1&&p.x<2&&p.y<2)).toBe(false);
  });
});
