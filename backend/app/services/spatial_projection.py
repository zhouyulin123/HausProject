"""将已确认的整屋版本精确投影为只读单房间场景，不修订既有交付。"""

from math import hypot

from app.schemas.scenes import SceneDocument
from app.schemas.spatial import SpatialDocument


def project_room(document: SpatialDocument, room_id: str) -> SceneDocument:
    room = next((item for item in document.rooms if item.id == room_id), None)
    if room is None:
        raise LookupError("房间不存在")
    if document.scale_status != "confirmed":
        raise ValueError("请先确认整屋尺度")
    walls = [wall for wall in document.walls if room_id in wall.room_ids]
    # 单房间历史契约只有一种墙厚和完整层高，不能把不兼容结构悄悄投影成默认墙。
    if not walls or any(abs(wall.height - room.height) > 1e-7 for wall in walls):
        raise ValueError("房间墙体尚未完整确认，或墙高与层高不一致")
    if any(abs(wall.thickness - walls[0].thickness) > 1e-7 for wall in walls):
        raise ValueError("该房间具有不同墙厚，旧单房间场景不能精确表达")
    openings = []
    for index, start in enumerate(room.polygon):
        end = room.polygon[(index + 1) % len(room.polygon)]
        length = hypot(end.x - start.x, end.z - start.z)
        ux, uz = (end.x - start.x) / length, (end.z - start.z) / length
        intervals = []
        for wall in walls:

            def on_line(point):
                return abs((point.x - start.x) * uz - (point.z - start.z) * ux) < 1e-7

            if not on_line(wall.start) or not on_line(wall.end):
                continue
            a = (wall.start.x - start.x) * ux + (wall.start.z - start.z) * uz
            b = (wall.end.x - start.x) * ux + (wall.end.z - start.z) * uz
            low, high = sorted((a, b))
            intervals.append((max(0, low), min(length, high)))
            for opening in document.openings:
                if opening.wall_id != wall.id:
                    continue
                offset = (
                    a + opening.offset if b > a else a - opening.offset - opening.width
                )
                if offset >= -1e-7 and offset + opening.width <= length + 1e-7:
                    openings.append(
                        {
                            "id": opening.id,
                            "type": opening.type,
                            "wallIndex": index,
                            "offset": max(0, offset),
                            "width": opening.width,
                            "height": opening.height,
                            "sillHeight": opening.sill_height,
                        }
                    )
                elif offset < length - 1e-7 and offset + opening.width > 1e-7:
                    raise ValueError("开口跨越房间边界分段，旧单房间场景不能精确表达")
        covered = 0.0
        for low, high in sorted(intervals):
            if high <= 0 or low >= length:
                continue
            if low > covered + 1e-7:
                break
            covered = max(covered, high)
        if covered < length - 1e-7:
            raise ValueError("房间边界的墙体尚未完整确认")
    return SceneDocument.model_validate(
        {
            "schemaVersion": "1.0",
            "unit": "m",
            "room": {
                "id": room.id,
                "name": room.name,
                "floorPolygon": [p.model_dump() for p in room.polygon],
                "ceilingHeight": room.height,
                "wallThickness": walls[0].thickness,
            },
            "openings": openings,
            "items": [],
        }
    )
