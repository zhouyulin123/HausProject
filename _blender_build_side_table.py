import bpy

# ===== 清空场景（保留用户偏好，含 GPU 配置）=====
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)

# ===== 材质工具 =====
def make_material(name, color, metallic=0.0, roughness=0.7):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (*color, 1.0)
    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.inputs["Roughness"].default_value = roughness
    return mat

wood  = make_material("WoodTop",  (0.45, 0.30, 0.18), 0.0, 0.55)
metal = make_material("MetalLeg", (0.12, 0.12, 0.14), 1.0, 0.35)
floor = make_material("Floor",    (0.82, 0.82, 0.85), 0.0, 0.95)

# ===== 桌面 =====
bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, 0.42))
top = bpy.context.object
top.dimensions = (1.1, 0.6, 0.04)
top.data.materials.append(wood)
top.name = "TableTop"

# ===== 4 根桌腿（圆柱）=====
leg_r, leg_h = 0.022, 0.40
for i, (x, y) in enumerate([(-0.5, -0.25), (0.5, -0.25), (-0.5, 0.25), (0.5, 0.25)]):
    bpy.ops.mesh.primitive_cylinder_add(radius=leg_r, depth=leg_h, location=(x, y, leg_h / 2))
    leg = bpy.context.object
    leg.data.materials.append(metal)
    leg.name = f"Leg_{i+1}"

# ===== 地面 =====
bpy.ops.mesh.primitive_plane_add(size=10, location=(0, 0, 0))
fl = bpy.context.object
fl.data.materials.append(floor)
fl.name = "Floor"

# ===== 灯光 =====
world = bpy.context.scene.world
world.node_tree.nodes["Background"].inputs[0].default_value = (0.90, 0.90, 0.92, 1)

bpy.ops.object.light_add(type='AREA', location=(1.2, -1.2, 2.2))
key = bpy.context.object
key.data.size = 3.0
key.data.energy = 80
key.data.color = (1.0, 0.98, 0.95)
key.constraints.new(type='TRACK_TO').target = top
key.constraints["Track To"].up_axis = 'UP_Y'
key.constraints["Track To"].track_axis = 'TRACK_NEGATIVE_Z'

bpy.ops.object.light_add(type='AREA', location=(-1.5, 1.5, 1.5))
fill = bpy.context.object
fill.data.size = 2.0
fill.data.energy = 25

# ===== 相机 =====
bpy.ops.object.camera_add(location=(1.8, -1.8, 1.0))
cam = bpy.context.object
cam.data.lens = 35
cam.constraints.new(type='TRACK_TO').target = top
cam.constraints["Track To"].up_axis = 'UP_Y'
cam.constraints["Track To"].track_axis = 'TRACK_NEGATIVE_Z'
bpy.context.scene.camera = cam

# ===== 渲染设置（尝试 GPU / OPTIX，失败回退 CPU）=====
scene = bpy.context.scene
scene.render.engine = 'CYCLES'
cprefs = bpy.context.preferences.addons['cycles'].preferences
try:
    cprefs.compute_device_type = 'OPTIX'
    cprefs.get_devices()
    gpu_ok = any(d.use for d in cprefs.devices)
    scene.cycles.device = 'GPU' if gpu_ok else 'CPU'
except Exception:
    scene.cycles.device = 'CPU'
scene.cycles.samples = 128
scene.render.resolution_x = 1280
scene.render.resolution_y = 720
scene.render.filepath = r"D:/code/MyselfProject/generated_side_table.png"
scene.render.image_settings.file_format = 'PNG'

# ===== 导出 GLB（仅桌子，隐藏地面，避免大地面撑爆视框）=====
fl.hide_viewport = True
bpy.ops.export_scene.gltf(
    filepath=r"D:/code/MyselfProject/generated_side_table.glb",
    export_format='GLB',
    export_yup=True,
    use_visible=True,
)
fl.hide_viewport = False

# ===== 渲染出图 =====
bpy.ops.render.render(write_still=True)
print("DONE: side table built + rendered + exported GLB")
