import type { SpatialWall,SpatialOpening } from "@/types/spatial";
import { distance } from "./spatialGeometry";
export function wallPieces(wall: SpatialWall,all: SpatialOpening[]) {
  const openings=all.filter(o => o.wall_id===wall.id),length=distance(wall.start,wall.end);
  const cuts=[...new Set([0,length,...openings.flatMap(o => [o.offset,o.offset+o.width])])].sort((a,b) => a-b);
  const result: {
    x: number;
    y: number;
    z: number;
    width: number;
    height: number;
    angle: number;
  }[]=[];
  for(let i=0;i<cuts.length-1;i++) {
    const left=cuts[i],right=cuts[i+1],mid=(left+right)/2;
    const holes=openings.filter(o => mid>o.offset&&mid<o.offset+o.width).sort((a,b) => a.sill_height-b.sill_height);
    let bottom=0;
    for(const hole of [...holes,{ sill_height: wall.height,height: 0 }]) {
      if(hole.sill_height>bottom+1e-7)
        result.push({ x: wall.start.x+(wall.end.x-wall.start.x)*mid/length,z: wall.start.z+(wall.end.z-wall.start.z)*mid/length,y: (bottom+hole.sill_height)/2,width: right-left,height: hole.sill_height-bottom,angle: -Math.atan2(wall.end.z-wall.start.z,wall.end.x-wall.start.x) });
      bottom=Math.max(bottom,hole.sill_height+hole.height);
    }
  }
  return result;
}
