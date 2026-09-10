---
name: furniture-open-geometry
description: 将家具自然语言意图转换为受控、可持续编辑的开放几何 DSL create/patch，不生成或执行源码。
---

# 家具开放几何参数设计

本 Skill 用于设计现有固定模板无法表达的家具。运行时唯一契约是仓库根目录
`shared/furniture_open_geometry_contract.json`，坐标使用毫米、Y 轴向上、原点为家具落地中心。

## 输出边界

- 只输出 JSON 对象，操作只能是 `create`、`patch` 或 `unsupported`。
- `create` 必须返回完整 `design`；已有设计时优先返回 `patch`。
- `patch.upsert_parts` 中每个元素是完整部件，已有部件必须复用稳定 `id`。
- 未要求修改的部件、材质和属性保持不变。
- 几何只允许 `box`、`cylinder`、`sphere`、`sweep`、`lathe`。
- v1 只支持平移和父子平移，`rotation_deg` 固定为 `[0, 0, 0]`；倾斜和弧线用 sweep 控制点表达。
- 整件等比或分轴缩放使用设计级 `scale`，例如整体加宽 10% 将当前 `scale[0]` 乘以 `1.1`。
- 不输出 Python、JavaScript、Three.js、Blender 脚本、表达式或可执行字符串。
- 用户要求超出契约能力时返回 `unsupported`，说明无法表达的造型能力。

## 落地硬约束

生成或修改任何部件前，必须按以下公式检查世界坐标最低点，所有最低点都必须大于等于 `0mm`。有父部件时，先累加全部父级 `position_mm[1]`：

- `box`：`world_position_y - size_mm[1] / 2 >= 0`
- `cylinder`：`world_position_y - height_mm / 2 >= 0`
- `sphere`：`world_position_y - radius_mm * scale[1] >= 0`
- `sweep`：`world_position_y + min(path_mm[*][1]) - radius_mm >= 0`
- `lathe`：`world_position_y + min(profile_mm[*][1]) >= 0`

落地部件应让最低点等于或略高于 `0mm`；不能只把路径控制点或部件中心放在 `0mm`，否则几何半径或半高会穿过地面。

曲线还必须满足共享契约的 `min_geometry_length_mm=0.1mm`：`sweep` 的总长度、每一段连续控制点间距，以及闭合路径末点到首点的间距都不得小于该值；`closed=true` 时末点不要重复起点。`lathe` 至少要有一个半径达到 `0.1mm`，并包含一段长度不小于 `0.1mm` 且离开旋转轴的轮廓线，否则应修正参数而不是生成不可见部件。

## 设计顺序

1. 从当前完整设计识别用户指向的稳定部件 ID。
2. 将自然语言转换成最小局部修改。
3. 同步调整因结构约束必须联动的部件。
4. 保持家具落地、主要部件连接，避免明显穿插和零厚度。
5. 输出操作 JSON，交由服务端严格校验和确定性编译。

## 输出示例

```json
{
  "operation": "patch",
  "patch": {
    "upsert_parts": [
      {
        "id": "left_support",
        "name": "左弧形支撑",
        "material_id": "frame",
        "parent_id": null,
        "position_mm": [0, 0, 0],
        "rotation_deg": [0, 0, 0],
        "geometry": {
          "type": "sweep",
          "path_mm": [[-620, 0, -280], [-650, 220, -40], [-590, 430, 210]],
          "radius_mm": 28,
          "tubular_segments": 32,
          "radial_segments": 12,
          "closed": false
        }
      }
    ],
    "remove_part_ids": []
  }
}
```

每次输出都只是候选操作。只有服务端合并、校验、编译成功并创建新版本后，前端才更新 3D。
