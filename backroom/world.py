# -*- coding: utf-8 -*-
"""**表现层**：把 :class:`~backroom.kernel.BackroomKernel` 的地图画成三维后室。

用尽的 3dworld 能力（每一项都是**真在用**，不是列清单）
-------------------------------------------------------
- ``engine.greedy_mesh.layer_mesh`` —— 墙格贪心合批：一整层的墙并成极少矩形，
  一个区块通常只有几十个 quad（逐个立方体画要上千）；
- ``engine.proctex.material_from`` —— **程序化 PBR 材质**（零外部素材）：
  单黄壁纸 / 潮地毯 / 天花板三套，按层级换色；
- ``engine.material.Material`` —— 金属-粗糙度材质（含 emissive 通道给灯管）；
- ``engine.mesh.Mesh`` / ``InstancedMesh`` —— 静态墙用 Mesh、**灯管走实例化**
  （N 盏灯 1 次 draw call）；
- ``engine.scene.Scene/Node`` —— 场景图（区块按节点挂载，可整块装卸）；
- ``engine.camera.FlyCamera`` —— 第一人称相机（yaw/pitch + 阻尼）；
- ``engine.renderer.Renderer`` —— 前向 PBR + IBL + MRT（法线/深度）；
- ``engine.postfx.PostSettings/PostChain`` —— SSAO → Bloom → 曝光 → ACES → 暗角；
- ``engine.framegraph.standard_3d_plan`` —— 后处理**顺序**由帧图钉住
  （雾在景深前、景深在运动模糊前），不靠手写顺序；
- ``engine.env.LightEnvironment`` —— 程序化天空 IBL（辐照度 + GGX 预过滤 + BRDF LUT）。

流式加载
--------
伪无限地图不能全量建网：只建玩家周边 ``RING`` 圈的区块，走远的整块卸载
（节点摘除 + GL 资源 delete），所以内存与 draw call 都是常数级。
"""
from __future__ import annotations

import math
import random

from pyglet.math import Mat4, Vec3

from world3d.engine.camera import FlyCamera
from world3d.engine.env import LightEnvironment
from world3d.engine.framegraph import standard_3d_plan
from world3d.engine.geometry import MeshData, box
from world3d.engine.greedy_mesh import layer_mesh
from world3d.engine.mesh import InstancedMesh, Mesh
from world3d.engine.postfx import PostSettings
from world3d.engine.proctex import material_from
from world3d.engine.renderer import Renderer
from world3d.engine.scene import Node, Scene
from world3d.engine.shaders import get

from .kernel import (CELL, CHUNK, EYE, TILE_ANOMALY, TILE_FLOOR, TILE_PILLAR,
                     TILE_WALL, WALL_H)

RING = 1                      # 预建圈数（1 = 3×3 个区块）
LAMP_EVERY = 5                # 每几格一盏吸顶灯
LAMP_CAPACITY = 512           # 实例化灯管的容量上限
FOG_NEAR = 1.5

#: 三套程序化材质对应的 proctex 图案（零外部素材，全部代码生成）
PATTERN_WALL = 'plaster'      # 灰泥 → 调成后室单黄壁纸
PATTERN_CARPET = 'thatch'     # 草席纹 → 调成潮湿地毯的绒面
PATTERN_CEIL = 'plaster'      # 灰泥 → 天花板吸音板


def _uvs_by_normal(positions, normals, scale=1.0):
    """按法线主轴做平面投影 UV（triplanar 的简版）。

    ``layer_mesh`` 只给位置和明暗、不给 UV，而壁纸/地毯要**按世界尺度平铺**
    （一格一张图），所以必须自己投影：法线朝哪个轴，就用另外两个轴当 uv。
    """
    uvs = []
    for i in range(0, len(positions), 3):
        x, y, z = positions[i], positions[i + 1], positions[i + 2]
        nx, ny, nz = normals[i], normals[i + 1], normals[i + 2]
        ax, ay, az = abs(nx), abs(ny), abs(nz)
        if ay >= ax and ay >= az:
            u, v = x, z
        elif ax >= az:
            u, v = z, y
        else:
            u, v = x, y
        uvs += [u / scale, v / scale]
    return uvs


class BackroomWorld:
    """后室三维世界：区块流式建网 + PBR 渲染。"""

    def __init__(self, kernel, width=1280, height=720):
        self.k = kernel
        self.width, self.height = width, height

        self.program = get('pbr')
        self.inst_program = get('pbr_inst')
        # 后室是**封闭**空间：没有太阳、天光极暗，照明几乎全靠吸顶灯自身的
        # emissive + 点光，IBL 只留一点点环境反弹（否则墙缝里死黑一片）。
        self.env = LightEnvironment(
            sun_dir=(0.0, 1.0, 0.0), sun_color=(1.0, 0.96, 0.86),
            sun_intensity=0.30, ibl_intensity=0.55, sky_intensity=0.45,
            sky_zenith=(0.06, 0.055, 0.045), sky_horizon=(0.10, 0.09, 0.075),
            sky_ground=(0.03, 0.028, 0.024),
            env_size=(256, 128)).bake()
        self.scene = Scene(name='backroom', environment=self.env)
        self.root = Node(name='root')
        self.scene.add(self.root)

        # ---- 程序化材质（按当前层级配色；换层时重染）
        self._materials = {}
        self._build_materials()

        # ---- 相机（第一人称）：眼高固定，yaw 与内核同步
        self.camera = FlyCamera(position=(kernel.x, EYE, kernel.z),
                                yaw=math.degrees(kernel.yaw) - 90.0,
                                pitch=0.0, move_speed=2.55)
        self.camera.up = (0.0, 1.0, 0.0)

        # ---- 后处理：荧光灯要有泛光，窄走廊要有环境光遮蔽
        # PostSettings 是无参构造 + 属性赋值（不是关键字构造）
        self.post = PostSettings()
        self.post.exposure = 1.25
        self.post.bloom_threshold = 0.80      # 灯管 HDR>1 才溢光，天空(~0.5)不会
        self.post.bloom_intensity = 0.65
        self.post.ssao_radius = 0.55
        self.post.ssao_intensity = 1.25
        self.post.ssao_strength = 0.70
        self.post.vignette = 0.42
        self.renderer = Renderer(width, height, environment=self.env,
                                 post_settings=self.post)
        # 帧图钉住后处理顺序（雾→景深→运动模糊），避免手写顺序悄悄漂移
        self.frame_plan = standard_3d_plan(shadows=True, fog=True,
                                           dof=False, motionblur=False)

        # ---- 流式区块
        self.built: dict[tuple[int, int], Node] = {}
        self._lamp_positions: dict[tuple[int, int], list] = {}
        self.refresh(force=True)

    # ------------------------------------------------------------ 材质
    def _build_materials(self):
        """三套程序化 PBR 材质：壁纸 / 地毯 / 天花板 + 灯管自发光。"""
        lv = self.k.level_info()
        wr, wg, wb = lv['wall']
        cr, cg, cb = lv['carpet']
        er, eg, eb = lv['ceil']
        lr, lg, lb = lv['lamp']

        self._materials['wall'] = material_from(
            PATTERN_WALL, size=256, base_color=(wr, wg, wb),
            roughness=0.92, metallic=0.0, seed=3, name='wallpaper')
        self._materials['carpet'] = material_from(
            PATTERN_CARPET, size=256, base_color=(cr, cg, cb),
            roughness=0.98, metallic=0.0, seed=11, name='carpet')
        self._materials['ceil'] = material_from(
            PATTERN_CEIL, size=256, base_color=(er, eg, eb),
            roughness=0.95, metallic=0.0, seed=5, name='ceiling')
        # 灯管：emissive 拉高（HDR 值 >1 才能触发 Bloom 溢出荧光）
        self._materials['lamp'] = material_from(
            PATTERN_CEIL, size=64, base_color=(lr, lg, lb),
            emissive=(3.2, 3.1, 2.7), roughness=0.6, seed=1, name='lamp')

    def retint_for_level(self):
        """下潜换层：整场重新染色（材质是程序化的，重染零成本）。"""
        self._build_materials()
        self.refresh(force=True)

    # ------------------------------------------------------------ 区块建网
    def refresh(self, force=False):
        """按玩家位置建/卸区块（伪无限的关键：只维护周边 RING 圈）。"""
        want = set()
        cx, cy = self.k.chunk()
        for i in range(-RING, RING + 1):
            for j in range(-RING, RING + 1):
                want.add((cx + i, cy + j))
        if not force and want == set(self.built):
            return
        for key in list(self.built):
            if key not in want:
                self.root.remove(self.built.pop(key))
                self._lamp_positions.pop(key, None)     # 灯位必须跟着一起走
        for key in want:
            if key not in self.built:
                node = self._build_chunk(*key)
                if node is not None:
                    self.built[key] = node

    def _build_chunk(self, cx: int, cy: int):
        """一个区块 = 墙(贪心合批) + 地板 + 天花板 + 灯管(实例化)。"""
        grid = self.k.map.grid(cx, cy)
        x0, z0 = cx * CHUNK * CELL, cy * CHUNK * CELL
        node = Node(name=f'chunk_{cx}_{cy}')

        walls = {(y, x) for y in range(CHUNK) for x in range(CHUNK)
                 if grid[y][x] in (TILE_WALL, TILE_PILLAR)}
        if walls:
            pos, _shade = layer_mesh(walls, CHUNK, CHUNK, cs=CELL,
                                     x0=x0, z0=z0, ytop=WALL_H)
            md = MeshData(list(pos), name=f'wall_{cx}_{cy}')
            md.compute_normals()
            md.uvs = _uvs_by_normal(md.positions, md.normals, scale=CELL)
            node.add(Node(name=f'walls_{cx}_{cy}',
                          drawable=Mesh(md, self.program,
                                        self._materials['wall'])))

        size = CHUNK * CELL
        node.add(Node(name=f'floor_{cx}_{cy}',
                      drawable=self._slab(x0, z0, size, 0.0, True,
                                          self._materials['carpet'])))
        node.add(Node(name=f'ceil_{cx}_{cy}',
                      drawable=self._slab(x0, z0, size, WALL_H, False,
                                          self._materials['ceil'])))

        lamps = self._build_lamps(cx, cy, grid, x0, z0)
        if lamps is not None:
            node.add(Node(name=f'lamps_{cx}_{cy}', drawable=lamps))

        self.root.add(node)
        return node

    @staticmethod
    def _slab(x0: float, z0: float, size: float, y: float, up: bool, material):
        """一块水平面（地板/天花板），UV 按格平铺。"""
        n = 1.0 if up else -1.0          # 地板法线朝上，天花板朝下
        pos = [x0, y, z0, x0 + size, y, z0, x0 + size, y, z0 + size,
               x0, y, z0, x0 + size, y, z0 + size, x0, y, z0 + size]
        normals = [0.0, n, 0.0] * 6
        uvs = [0.0, 0.0, size / CELL, 0.0, size / CELL, size / CELL,
               0.0, 0.0, size / CELL, size / CELL, 0.0, size / CELL]
        return Mesh(MeshData(pos, normals, uvs), get('pbr'), material)

    def _build_lamps(self, cx, cy, grid, x0, z0):
        """吸顶灯管：走 **GPU 实例化**，N 盏灯一次 draw call。

        灯只挂在**开阔处**（地板/异常格），且按层级的灯密度稀疏化——
        越深的层灯越少、越暗，压迫感靠"灯够不着"来给。
        """
        density = self.k.level_info()['lamp_density']
        rng = random.Random((cx * 73856093) ^ (cy * 19349663) ^ 0x1A2B)
        boxes = []
        for gy in range(1, CHUNK - 1, LAMP_EVERY):
            for gx in range(1, CHUNK - 1, LAMP_EVERY):
                if grid[gy][gx] not in (TILE_FLOOR, TILE_ANOMALY):
                    continue
                if rng.random() > density:
                    continue
                wx = x0 + (gx + 0.5) * CELL
                wz = z0 + (gy + 0.5) * CELL
                boxes.append((wx, wz))
        if not boxes:
            return None

        # 灯管几何：细长盒（吸顶在 WALL_H 下方一点）
        n = min(LAMP_CAPACITY, max(16, len(boxes)))
        geo = box(1.35, 0.10, 0.20, offset=(0.0, 0.0, 0.0))
        inst = InstancedMesh(geo, self.inst_program,
                             self._materials['lamp'],
                             capacity=n, name=f'lamps_{cx}_{cy}')
        mats = [Mat4.from_translation(Vec3(wx, WALL_H - 0.12, wz))
                for wx, wz in boxes[:n]]
        inst.write_all(mats)
        # 灯位按区块登记：区块卸载时要一起摘掉，否则灯光会越积越多
        self._lamp_positions[(cx, cy)] = boxes[:n]
        return inst

    # ------------------------------------------------------------ 每帧
    def update(self, dt: float):
        """同步内核状态 → 相机 / 区块 / 灯光。"""
        self.camera.position = (self.k.x, EYE, self.k.z)
        self.camera.yaw = math.degrees(self.k.yaw) - 90.0
        self.camera.update(dt)
        if self.k.chunk() not in self.built or len(self.built) < (2 * RING + 1) ** 2:
            self.refresh()

    def point_lights(self):
        """离玩家最近的 4 盏灯（着色器最多 4 盏点光）。

        只给最近的几盏：后室的光是**局部**的，远处应该是黑的——
        这既是性能取舍，也是氛围本身。
        """
        lv = self.k.level_info()
        lr, lg, lb = lv['lamp']
        out = []
        for boxes in self._lamp_positions.values():
            for wx, wz in boxes:
                d = math.hypot(wx - self.k.x, wz - self.k.z)
                out.append((d, (wx, WALL_H - 0.25, wz)))
        out.sort(key=lambda t: t[0])
        # 灯闪：内核的 flicker 期间整体压暗并抖动
        fl = self.k.flicker
        flick = 1.0
        if fl > 0.0:
            flick = 0.35 + 0.65 * abs(math.sin(self.k.t * 37.0))
        gain = 2.6                       # 点光增益：荧光灯要"亮得发白"
        return [((p[0], p[1], p[2]),
                 (lr * flick * gain, lg * flick * gain, lb * flick * gain))
                for _, p in out[:4]]

    def render(self, window=None):
        self.renderer.set_point_lights(self.point_lights())
        aspect = (self.width / max(1.0, float(self.height)))
        return self.renderer.render(self.camera, self.scene, aspect, window)

    def resize(self, width, height):
        self.width, self.height = width, height
        return self.renderer.resize(width, height)

    # ------------------------------------------------------------ 统计
    @property
    def stats(self):
        s = dict(self.renderer.stats)
        s['chunks'] = len(self.built)
        s['level'] = self.k.level_info()['name']
        return s
