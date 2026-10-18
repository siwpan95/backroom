# backrooms_raycaster.py
import pygame
import numpy as np
import math
import random
from pygame import Vector2
import threading
import time

# 尝试导入音频库
try:
    import sounddevice as sd
    HAS_AUDIO = True
except ImportError:
    HAS_AUDIO = False
    print("Warning: sounddevice not found, audio disabled")

# 初始化pygame-ce
pygame.init()


# ============ 音频引擎 ============
class AmbientAudioEngine:
    """环境音频引擎 - 生成氛围音乐"""
    
    def __init__(self, sample_rate=22050):  # 降低采样率增强低沉感
        self.SR = sample_rate
        self.BPM = 60  # 更慢的节奏增加压抑感
        self.VOL = 0.12
        
        # 音符频率（降低一个八度）
        self.NOTES = {
            "C3": 130.81, "Eb3": 155.56, "E3": 164.81,
            "Gb3": 185.00, "G3": 196.00, "Ab3": 207.65,
            "Bb3": 233.08, "B3": 246.94, "C4": 261.63,
            "Eb4": 311.13, "E4": 329.63, "Gb4": 369.99,
            "G4": 392.00, "A4": 440.00, "Bb4": 466.16,
        }
        
        # 后室氛围音乐模式
        self.RIFF = ["C3", "Eb3", "Gb3", "Bb3", "C3", "Eb3", "G3", "Bb3"]
        self.DRONE = ["C3", None, "C3", None, "Eb3", None, "Eb3", None]
        
        self.beat = 0
        self.pattern = self.RIFF
        self.stream = None
        self.is_playing = False
        self.lock = threading.Lock()
        
        # 混响参数
        self.reverb_buffer = np.zeros(int(self.SR * 0.8))  # 0.8秒混响
        self.reverb_index = 0
        self.reverb_amount = 0.35
        
        # 失真参数
        self.distortion_gain = 2.5
        self.distortion_mix = 0.4
        
        # 实体音效参数
        self.heartbeat_timer = 0.0
        self.heartbeat_intensity = 0.3
        self.beats_per_sample = 1.0 / (1.2 * self.SR / 1024)
        self.beat_progress = 0.0
        self.warning_timer = 0.0
        self.warning_intensity = 0.0
        self.breath_timer = 0.0
        self.footstep_timer = 0.0
    
    def init_audio(self):
        """初始化音频流"""
        if not HAS_AUDIO:
            return False
        try:
            self.stream = sd.OutputStream(
                samplerate=self.SR,
                channels=2,
                dtype='float32',
                callback=self.audio_callback,
                blocksize=1024,
                latency='low'
            )
            return True
        except Exception as e:
            print(f"Audio init failed: {e}")
            return False
    
    def saw(self, t, f):
        """锯齿波振荡器"""
        return 2 * (np.mod(t * f, 1.0)) - 1
    
    def sine(self, t, f):
        """正弦波（用于低频Drone）"""
        return np.sin(2 * np.pi * f * t)
    
    def envelope(self, n, attack=0.005, release=0.3):
        """ADSR包络"""
        att_samples = int(attack * n)
        rel_samples = int(release * n)
        e = np.ones(n)
        if att_samples > 0:
            e[:att_samples] = np.linspace(0, 1, att_samples)
        if rel_samples > 0:
            e[-rel_samples:] = np.linspace(1, 0, rel_samples)
        return e
    
    def apply_distortion(self, signal):
        """应用软失真"""
        # 软剪辑失真
        distorted = np.tanh(signal * self.distortion_gain)
        # 混合原信号和失真信号
        return signal * (1 - self.distortion_mix) + distorted * self.distortion_mix
    
    def apply_reverb(self, signal):
        """应用简单的房间混响"""
        output = np.copy(signal)
        for i in range(len(signal)):
            # 读取混响缓冲区
            reverb_sample = self.reverb_buffer[self.reverb_index]
            # 添加到输出
            output[i] = signal[i] + reverb_sample * self.reverb_amount
            # 更新混响缓冲区
            self.reverb_buffer[self.reverb_index] = (
                signal[i] * 0.5 + reverb_sample * 0.4
            )
            # 移动索引
            self.reverb_index = (self.reverb_index + 1) % len(self.reverb_buffer)
        return output
    
    def get_next_note(self):
        """获取下一个音符"""
        with self.lock:
            idx = int(self.beat) % len(self.pattern)
            note = self.pattern[idx]
            self.beat += 0.5
            if self.beat >= len(self.pattern) * 2:
                self.beat = 0
            return note
    
    def audio_callback(self, outdata, frames, time_info, status):
        """音频回调函数"""
        if not self.is_playing:
            outdata[:] = np.zeros((frames, 2))
            return
        
        t = np.arange(frames) / self.SR
        
        # 生成主旋律
        note = self.get_next_note()
        if note:
            f = self.NOTES.get(note, 130.81)
            sig = self.saw(t, f) * self.envelope(frames, 0.01, 0.25)
        else:
            sig = np.zeros(frames)
        
        # 添加低频Drone - 降低音量避免掩盖其他声音
        drone_f = 55.0  # 低沉的A1
        drone = self.sine(t, drone_f) * 0.08
        drone += self.sine(t, drone_f * 1.5) * 0.04  # 五度泛音
        
        # 添加随机白噪声（模拟环境声）
        noise = np.random.randn(frames) * 0.01
        
        # 混合所有声音 - 降低背景音乐整体音量
        mix = sig * 0.35 + drone + noise
        
        # 应用效果
        if frames <= len(mix):
            signal_mono = mix[:frames]
        else:
            signal_mono = np.pad(mix, (0, frames - len(mix)))
        
        # 实体音效 - 增大音量确保能听到
        entity_sound = np.zeros(frames)
        with self.lock:
            # 心跳音效（理智低时）
            if self.heartbeat_timer > 0:
                t_range = np.arange(frames) / self.SR
                beat_pos = int((self.beats_per_sample - self.beat_progress) * frames)
                if 0 <= beat_pos < frames:
                    heartbeat = self.sine(t_range[max(0, frames-beat_pos):], 60)
                    heartbeat *= np.exp(-np.arange(len(heartbeat)) / (frames * 0.1))
                    entity_sound[-len(heartbeat):] += heartbeat * 0.5 * self.heartbeat_intensity
            
            # 实体接近警告音（高频脉冲）- 显著提高音量
            if self.warning_timer > 0:
                t_range = np.arange(frames) / self.SR
                warning_freq = 800 + self.warning_intensity * 200
                warning = self.sine(t_range, warning_freq) * self.warning_timer * 0.2
                entity_sound += warning
            
            # 实体呼吸声（低频白噪声调制）
            if self.breath_timer > 0:
                breath_env = np.sin(np.arange(frames) / frames * np.pi * 2) * 0.5 + 0.5
                breath_noise = np.random.randn(frames) * 0.08
                entity_sound += breath_noise * breath_env * self.breath_timer
            
            # 脚步声 - 提高音量
            if self.footstep_timer > 0:
                t_range = np.arange(frames) / self.SR
                # 低频冲击
                footstep = self.sine(t_range, 80) * np.exp(-np.arange(frames) / (frames * 0.05))
                # 添加噪声
                footstep += np.random.randn(frames) * 0.05 * np.exp(-np.arange(frames) / (frames * 0.03))
                entity_sound += footstep * 0.3 * self.footstep_timer
        
        # 转换为立体声并应用效果
        # 降低背景音乐音量，让实体音效更突出
        left = self.apply_distortion(self.apply_reverb(signal_mono)) * 0.5
        right = self.apply_distortion(self.apply_reverb(signal_mono * 0.95)) * 0.5
        
        # 混合实体音效 - 提高音量使警告音更明显
        left = left + entity_sound * 0.8
        right = right + entity_sound * 0.8
        
        # 更新心跳进度
        self.beat_progress += frames * self.beats_per_sample
        if self.beat_progress >= 1.0:
            self.beat_progress -= 1.0
        
        # 衰减特效音量
        self.heartbeat_timer = max(0, self.heartbeat_timer - 0.02)
        self.warning_timer = max(0, self.warning_timer - 0.01)
        self.breath_timer = max(0, self.breath_timer - 0.015)
        self.footstep_timer = max(0, self.footstep_timer - 0.1)
        
        # 输出
        outdata[:, 0] = np.clip(left * self.VOL, -1, 1)
        outdata[:, 1] = np.clip(right * self.VOL, -1, 1)
    
    def start(self):
        """启动音频"""
        if self.stream and not self.stream.active:
            self.stream.start()
            self.is_playing = True
    
    def stop(self):
        """停止音频"""
        self.is_playing = False
        if self.stream and self.stream.active:
            self.stream.stop()
    
    def set_intensity(self, sanity):
        """根据理智值调整音频强度"""
        # 理智越低，混响越大，失真越强，心跳越快
        if sanity < 30:
            self.reverb_amount = 0.5
            self.distortion_mix = 0.6
            self.VOL = 0.15
            self.beats_per_sample = 1.0 / (0.4 * self.SR / 1024)  # 每0.4秒心跳
            self.heartbeat_intensity = 1.0
        elif sanity < 50:
            self.reverb_amount = 0.42
            self.distortion_mix = 0.5
            self.VOL = 0.13
            self.beats_per_sample = 1.0 / (0.7 * self.SR / 1024)  # 每0.7秒心跳
            self.heartbeat_intensity = 0.7
        else:
            self.reverb_amount = 0.35
            self.distortion_mix = 0.4
            self.VOL = 0.12
            self.beats_per_sample = 1.0 / (1.2 * self.SR / 1024)  # 每1.2秒心跳
            self.heartbeat_intensity = 0.3
    
    def trigger_entity_warning(self, intensity=1.0):
        """触发实体接近警告"""
        with self.lock:
            self.warning_timer = 1.0
            self.warning_intensity = min(1.0, intensity)
            self.breath_timer = 1.0
    
    def trigger_entity_near(self, distance):
        """触发实体接近效果"""
        with self.lock:
            # 距离越近，警告越强
            intensity = max(0.2, 1.5 - distance)
            self.heartbeat_timer = 1.0
            self.heartbeat_intensity = min(1.0, intensity)
            self.warning_timer = 1.0
            self.warning_intensity = min(1.0, intensity)
            self.breath_timer = 1.0
            
            # 理智越低，心跳越快
            if self.heartbeat_intensity > 0.7:
                self.beats_per_sample *= 1.5
    
    def trigger_footstep(self):
        """触发脚步声"""
        with self.lock:
            self.footstep_timer = 1.0

class BackroomsRenderer:
    def __init__(self, width=320, height=240, scale=3):
        """初始化渲染器"""
        self.base_res = (width, height)
        self.scale = scale
        self.screen = pygame.display.set_mode(
            (width * scale, height * scale)
        )
        self.display = pygame.Surface((width, height))
        self.clock = pygame.time.Clock()
        
        # 渲染状态
        self.zbuffer = np.full(width, 9999.0, dtype=np.float32)
        self.walls = []
        self.floor_color = (60, 55, 50)  # 米黄色地砖
        self.ceiling_color = (45, 42, 38)  # 暗黄色天花板
        
        # 字体
        self.font = pygame.font.Font(None, 16)
        
        # 视野效果
        self.distortion = 0.0
        self.flicker = 0.0
        
    def cast_rays(self, pos, angle, map_grid, fov=90, render_distance=20):
        """射线投射主函数 - 修正版"""
        width, height = self.display.get_size()
        self.zbuffer.fill(9999.0)
        
        # 计算方向和相机平面
        rad = math.radians(angle)
        dir_x, dir_y = math.cos(rad), math.sin(rad)
        plane_length = math.tan(math.radians(fov) / 2)
        plane_x, plane_y = -dir_y * plane_length, dir_x * plane_length
        
        self.walls = []
        
        for col in range(width):
            # 计算射线方向
            camera_x = 2 * col / width - 1
            ray_dir_x = dir_x + plane_x * camera_x
            ray_dir_y = dir_y + plane_y * camera_x
            
            # 执行DDA算法
            dist, wall_type, wall_x, side = self._dda(
                pos.x, pos.y, ray_dir_x, ray_dir_y, map_grid, render_distance
            )
            
            if dist < render_distance:
                self.zbuffer[col] = dist
                self.walls.append({
                    'col': col,
                    'dist': dist,
                    'type': wall_type,
                    'tex_x': wall_x,
                    'side': side
                })
    
    def _dda(self, px, py, rx, ry, map_grid, max_dist):
        """数字微分分析算法 - 支持无限地图"""
        map_x, map_y = int(px), int(py)
        
        # 避免除零
        delta_x = 1e30 if abs(rx) < 0.000001 else abs(1 / rx)
        delta_y = 1e30 if abs(ry) < 0.000001 else abs(1 / ry)
        
        # 步进方向
        step_x = 1 if rx >= 0 else -1
        step_y = 1 if ry >= 0 else -1
        
        # 初始距离
        if rx >= 0:
            side_x = (map_x + 1.0 - px) * delta_x
        else:
            side_x = (px - map_x) * delta_x
            
        if ry >= 0:
            side_y = (map_y + 1.0 - py) * delta_y
        else:
            side_y = (py - map_y) * delta_y
        
        # DDA主循环
        for _ in range(int(max_dist * 2)):
            if side_x < side_y:
                side_x += delta_x
                map_x += step_x
                side = 0
            else:
                side_y += delta_y
                map_y += step_y
                side = 1
            
            # 使用 get_tile 支持无限地图
            cell = map_grid.get_tile(map_x, map_y)
            if cell > 0:  # 撞到墙
                if side == 0:
                    dist = (map_x - px + (1 - step_x) / 2) / rx
                    wall_x = py + dist * ry
                else:
                    dist = (map_y - py + (1 - step_y) / 2) / ry
                    wall_x = px + dist * rx
                
                wall_x -= math.floor(wall_x)
                return dist, cell, wall_x, side
                
        return max_dist, 0, 0, 0
    
    def render_walls(self, time=0):
        """渲染墙体"""
        width, height = self.display.get_size()
        half_height = height // 2
        
        # 清屏
        self.display.fill(self.ceiling_color)
        pygame.draw.rect(self.display, self.floor_color, 
                        (0, half_height, width, half_height))
        
        # 从远到近绘制墙体
        self.walls.sort(key=lambda w: w['dist'], reverse=True)
        
        for wall in self.walls:
            col = wall['col']
            dist = wall['dist']
            
            # 计算墙高
            wall_height = int(height / (dist + 0.001))
            wall_height = min(wall_height, height)
            
            # 基础颜色（更明显）
            if wall['type'] == 1:  # 普通墙 - 暖色调
                base_color = (220, 200, 180)
            elif wall['type'] == 2:  # 门/特殊 - 深棕色
                base_color = (180, 140, 100)
            else:  # 异常墙 - 冷色调
                base_color = (200, 200, 220)
            
            # 距离衰减（改进：保持墙壁更亮）
            darkness = max(0.4, 1.0 - (dist * 0.04))
            r = int(base_color[0] * darkness)
            g = int(base_color[1] * darkness)
            b = int(base_color[2] * darkness)
            
            # 侧墙稍暗
            if wall['side'] == 1:
                r = int(r * 0.85)
                g = int(g * 0.85)
                b = int(b * 0.85)
            
            # 添加轻微纹理
            noise = int((math.sin(col * 0.3 + time * 0.001) + 1) * 6)
            r = min(255, r + noise)
            g = min(255, g + noise)
            b = min(255, b + noise)
            
            # 确保颜色不太暗
            r = max(40, r)
            g = max(40, g)
            b = max(40, b)
            
            # 绘制垂直条纹（增加宽度）
            top = max(0, (height - wall_height) // 2)
            bottom = min(height, top + wall_height)
            pygame.draw.line(self.display, (r, g, b), 
                           (col, top), (col, bottom - 1), 1)
    
    def render_entities(self, player_pos, player_angle, entities, time=0, fov=90):
        """渲染2D精灵实体"""
        width, height = self.display.get_size()
        half_fov = fov / 2
        rad = math.radians(player_angle)
        
        for entity in entities:
            # 计算相对位置
            dx = entity['x'] - player_pos.x
            dy = entity['y'] - player_pos.y
            
            # 距离检查
            dist = math.sqrt(dx*dx + dy*dy)
            if dist < 0.5 or dist > 20:
                continue
            
            # 计算角度和屏幕位置
            angle = math.degrees(math.atan2(dy, dx) - rad)
            angle = (angle + 180) % 360 - 180
            
            if abs(angle) < half_fov:
                # 计算屏幕X坐标
                screen_x = int((angle + half_fov) * width / fov)
                
                # 深度测试
                if 0 <= screen_x < width and dist < self.zbuffer[screen_x]:
                    # 透视缩放
                    size = int(100 / dist)
                    size = max(8, min(size, 100))
                    
                    # 选择颜色
                    if entity['type'] == 'static':
                        color = (200, 100, 100)
                    else:  # animated
                        pulse = int((math.sin(time * 0.01) + 1) * 30)
                        color = (100, 200, 100 + pulse)
                    
                    # 绘制实体
                    y = height // 2
                    if entity.get('shape') == 'circle':
                        pygame.draw.circle(self.display, color, 
                                         (screen_x, y), size//2)
                    else:  # 默认方形
                        pygame.draw.rect(self.display, color,
                                       (screen_x - size//2, y - size//2, 
                                        size, size))
    
    def render_items(self, player_pos, player_angle, items, time=0, fov=90):
        """渲染可收集道具"""
        width, height = self.display.get_size()
        half_fov = fov / 2
        rad = math.radians(player_angle)
        
        for item in items:
            dx = item['x'] - player_pos.x
            dy = item['y'] - player_pos.y
            
            dist = math.sqrt(dx*dx + dy*dy)
            if dist < 0.5 or dist > 20:
                continue
            
            angle = math.degrees(math.atan2(dy, dx) - rad)
            angle = (angle + 180) % 360 - 180
            
            if abs(angle) < half_fov:
                screen_x = int((angle + half_fov) * width / fov)
                
                if 0 <= screen_x < width and dist < self.zbuffer[screen_x]:
                    size = int(15 / dist)  # 道具大小
                    size = max(4, min(size, 20))
                    
                    # 杏仁水 - 淡蓝色发光效果
                    if item['type'] == 'almond_water':
                        # 发光效果
                        pulse = int((math.sin(time * 0.005) + 1) * 10)
                        glow_color = (100 + pulse, 150 + pulse, 255)
                        pygame.draw.circle(self.display, glow_color,
                                          (screen_x, height//2), size)
                        # 内部
                        inner_color = (200, 220, 255)
                        pygame.draw.circle(self.display, inner_color,
                                          (screen_x, height//2), size//2)
    
    def render_effects(self, time, sanity=100):
        """渲染视觉效果"""
        width, height = self.display.get_size()
        
        # 屏幕噪点
        if sanity < 70:
            noise_count = int(width * height * 0.003)  # 0.3%像素
            for _ in range(noise_count):
                x = random.randint(0, width-1)
                y = random.randint(0, height-1)
                alpha = random.randint(20, 60)
                self.display.set_at((x, y), (255, 255, 255, alpha))
        
        # 暗角效果（只在地理智时轻微启用）
        if sanity < 50:
            vignette = pygame.Surface((width, height), pygame.SRCALPHA)
            intensity = (50 - sanity) / 50 * 60  # 最大60的alpha
            for y in range(height):
                for x in range(width):
                    dx = (x - width/2) / (width/2)
                    dy = (y - height/2) / (height/2)
                    dist = math.sqrt(dx*dx + dy*dy)
                    alpha = int(min(intensity, dist * 80))
                    vignette.set_at((x, y), (0, 0, 0, alpha))
            self.display.blit(vignette, (0, 0), special_flags=pygame.BLEND_RGBA_ADD)
        
        # 理智值低时的颜色偏移
        if sanity < 30:
            color_shift = pygame.Surface((width, height), pygame.SRCALPHA)
            intensity = int((30 - sanity) * 3)
            color_shift.fill((intensity, 0, 0, 20))
            self.display.blit(color_shift, (0, 0), 
                            special_flags=pygame.BLEND_RGBA_ADD)
        
        # 闪烁效果
        if sanity < 50 and random.random() < 0.01:
            flash = pygame.Surface((width, height))
            flash.fill((255, 255, 255))
            flash.set_alpha(random.randint(30, 80))
            self.display.blit(flash, (0, 0))
    
    def render_ui(self, sanity=100, time_elapsed=0):
        """渲染UI"""
        # 理智条
        bar_width = 100
        bar_height = 6
        bar_x = 10
        bar_y = self.display.get_height() - 15
        
        # 背景
        pygame.draw.rect(self.display, (40, 40, 40), 
                       (bar_x, bar_y, bar_width, bar_height))
        
        # 前景
        fill = int(bar_width * (sanity / 100))
        if sanity > 50:
            color = (100, 200, 100)
        elif sanity > 20:
            color = (200, 200, 100)
        else:
            color = (200, 100, 100)
        
        pygame.draw.rect(self.display, color, 
                        (bar_x, bar_y, fill, bar_height))
        
        # 理智文字
        text = self.font.render(f"SANITY: {int(sanity)}", True, (180, 180, 180))
        self.display.blit(text, (bar_x, bar_y - 15))
    
    def present(self):
        """最终呈现"""
        scaled = pygame.transform.scale_by(self.display, self.scale)
        self.screen.blit(scaled, (0, 0))
        pygame.display.flip()
        return self.clock.tick(60)


class BackroomsGenerator:
    """关卡生成器 - 支持伪无限地图"""
    def __init__(self, seed=None):
        self.seed = seed or random.randint(0, 9999)
        self.random = random.Random(self.seed)
        self.np_random = np.random.RandomState(self.seed)
        
        # 区块缓存（用于无限地图）
        self.chunk_cache = {}
        self.chunk_size = 24  # 每个区块的大小
        
    def _seed_from_chunk(self, cx, cy):
        """基于区块坐标生成确定性种子"""
        return hash((cx, cy, self.seed)) % 1000000
    
    def generate_chunk(self, cx, cy):
        """生成指定区块"""
        if (cx, cy) in self.chunk_cache:
            return self.chunk_cache[(cx, cy)]
        
        # 为这个区块创建独立的随机状态
        chunk_seed = self._seed_from_chunk(cx, cy)
        rng = random.Random(chunk_seed)
        
        size = self.chunk_size
        
        # 使用递归回溯法生成连通迷宫
        grid = self._generate_maze_recursive(size, rng)
        
        # 添加大型房间（增加探索空间）
        self._add_rooms(grid, 2, 3, 5, rng)
        
        # 添加异常区域
        self._add_anomalies(grid, rng)
        
        self.chunk_cache[(cx, cy)] = grid
        return grid
    
    def _generate_maze_recursive(self, size, rng):
        """递归回溯法生成完全连通的迷宫"""
        # 使用目标尺寸，直接生成
        grid = [[1 for _ in range(size)] for _ in range(size)]
        
        # 递归回溯雕刻迷宫（使用奇数坐标）
        def carve(x, y):
            directions = [(0, -2), (2, 0), (0, 2), (-2, 0)]
            rng.shuffle(directions)
            
            for dx, dy in directions:
                nx, ny = x + dx * 2, y + dy * 2
                if 1 <= nx < size - 1 and 1 <= ny < size - 1 and grid[ny][nx] == 1:
                    grid[y + dy][x + dx] = 0
                    grid[ny][nx] = 0
                    carve(nx, ny)
        
        # 从(1,1)开始
        grid[1][1] = 0
        carve(1, 1)
        
        # 打通墙壁创建开放空间
        for _ in range(size * 3):
            x = rng.randint(1, size - 2)
            y = rng.randint(1, size - 2)
            if grid[y][x] == 1:
                grid[y][x] = 0
        
        # BFS找连通区域
        def bfs_connected(start_x, start_y):
            visited = set()
            queue = [(start_x, start_y)]
            while queue:
                x, y = queue.pop(0)
                if (x, y) in visited:
                    continue
                if not (0 <= x < size and 0 <= y < size):
                    continue
                if grid[y][x] != 0:
                    continue
                visited.add((x, y))
                queue.extend([(x+1, y), (x-1, y), (x, y+1), (x, y-1)])
            return visited
        
        # 找所有地板格子
        all_floors = [(x, y) for y in range(size) for x in range(size) if grid[y][x] == 0]
        if not all_floors:
            return [[1 for _ in range(size)] for _ in range(size)]
        
        # 从第一个地板开始找主连通区域
        start = all_floors[0]
        connected = bfs_connected(start[0], start[1])
        connected_set = set(connected)
        
        # 找出所有孤立的地板并连接
        isolated = [(x, y) for x, y in all_floors if (x, y) not in connected_set]
        
        for ix, iy in isolated:
            # 找最近的已连接点
            min_dist = float('inf')
            nearest = None
            for cx, cy in connected:
                dist = abs(cx - ix) + abs(cy - iy)
                if dist < min_dist:
                    min_dist = dist
                    nearest = (cx, cy)
            
            if nearest:
                # 画L形路径
                x, y = nearest
                while x != ix:
                    if 0 < x < size - 1:
                        grid[y][x] = 0
                    x += 1 if x < ix else -1
                while y != iy:
                    if 0 < y < size - 1:
                        grid[y][x] = 0
                    y += 1 if y < iy else -1
                if 0 < ix < size - 1 and 0 < iy < size - 1:
                    grid[iy][ix] = 0
        
        return grid
    
    def _add_rooms(self, grid, min_rooms, max_rooms, max_size, rng):
        """添加房间"""
        height = len(grid)
        width = len(grid[0])
        num_rooms = rng.randint(min_rooms, max_rooms)
        
        for _ in range(num_rooms):
            room_w = rng.randint(4, max_size)
            room_h = rng.randint(4, max_size)
            room_x = rng.randint(2, width - room_w - 2)
            room_y = rng.randint(2, height - room_h - 2)
            
            for y in range(room_y, room_y + room_h):
                for x in range(room_x, room_x + room_w):
                    if 0 <= y < height and 0 <= x < width:
                        grid[y][x] = 0
            
            if rng.random() > 0.6:
                center_x = room_x + room_w // 2
                center_y = room_y + room_h // 2
                if 0 <= center_y < height and 0 <= center_x < width:
                    grid[center_y][center_x] = 2
    
    def _add_anomalies(self, grid, rng):
        """添加异常区域"""
        height = len(grid)
        width = len(grid[0])
        
        for _ in range(rng.randint(2, 5)):
            x = rng.randint(1, width-2)
            y = rng.randint(1, height-2)
            
            for dy in range(-1, 2):
                for dx in range(-1, 2):
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < height and 0 <= nx < width:
                        if rng.random() > 0.5:
                            grid[ny][nx] = 3
    
    def get_tile(self, world_x, world_y):
        """获取世界坐标对应的格子"""
        cx = int(world_x) // self.chunk_size
        cy = int(world_y) // self.chunk_size
        local_x = int(world_x) % self.chunk_size
        local_y = int(world_y) % self.chunk_size
        
        if local_x < 0:
            local_x += self.chunk_size
        if local_y < 0:
            local_y += self.chunk_size
        
        chunk = self.generate_chunk(cx, cy)
        if 0 <= local_y < len(chunk) and 0 <= local_x < len(chunk[0]):
            return chunk[local_y][local_x]
        return 1  # 超出范围视为墙
    
    def generate_level(self, width=32, height=32):
        """生成固定大小的后室迷宫（用于兼容）"""
        grid = [[1 for _ in range(width)] for _ in range(height)]
        
        self._divide(grid, 1, 1, width-2, height-2, self.random)
        
        for y in range(height):
            grid[y][0] = 1
            grid[y][width-1] = 1
        for x in range(width):
            grid[0][x] = 1
            grid[height-1][x] = 1
        
        self._add_rooms(grid, 3, 6, 8, self.random)
        self._add_anomalies(grid, self.random)
        
        return grid
    
    def generate_level(self, width=32, height=32):
        """生成固定大小的后室迷宫（用于兼容）"""
        grid = [[1 for _ in range(width)] for _ in range(height)]
        
        rng = random.Random(self.seed)
        self._divide(grid, 1, 1, width-2, height-2, rng)
        
        for y in range(height):
            grid[y][0] = 1
            grid[y][width-1] = 1
        for x in range(width):
            grid[0][x] = 1
            grid[height-1][x] = 1
        
        self._add_rooms(grid, 3, 6, 8, rng)
        self._add_anomalies(grid, rng)
        
        return grid
    
    def generate_entities(self, grid, count=5):
        """寻找安全的出生点"""
        height = len(grid)
        width = len(grid[0])
        
        for _ in range(100):  # 最多尝试100次
            x = random.uniform(2, width-3)
            y = random.uniform(2, height-3)
            
            # 检查3x3区域是否都是空地
            safe = True
            for dy in range(-1, 2):
                for dx in range(-1, 2):
                    check_y, check_x = int(y) + dy, int(x) + dx
                    if (0 <= check_y < height and 0 <= check_x < width):
                        if grid[check_y][check_x] != 0:
                            safe = False
                            break
                if not safe:
                    break
            
            if safe:
                return Vector2(x, y)
        
        # 如果没找到，返回地图中心附近
        return Vector2(width//2, height//2)


class BackroomsPlayer:
    """玩家控制器"""
    def __init__(self, x=1.5, y=1.5):
        self.pos = Vector2(x, y)
        self.angle = 0.0
        self.sanity = 100.0
        self.speed = 0.05
        self.rot_speed = 2.0
        
        # 移动状态
        self.moving_forward = False
        self.moving_back = False
        self.turn_left = False
        self.turn_right = False
        self.strafe_left = False
        self.strafe_right = False
        self.running = False
        
        # 交互
        self.near_entity = None
    
    def update(self, dt, map_grid, entities):
        """更新玩家状态"""
        # 移动
        self._move(map_grid)
        
        # 更新理智
        self._update_sanity(dt, entities)
    
    def _move(self, map_grid):
        """移动和碰撞检测"""
        move_speed = self.speed * (1.8 if self.running else 1.0)
        rot_speed = self.rot_speed * (1.5 if self.running else 1.0)
        
        # 旋转
        if self.turn_left:
            self.angle = (self.angle - rot_speed) % 360
        if self.turn_right:
            self.angle = (self.angle + rot_speed) % 360
        
        # 计算移动向量
        move_vec = Vector2(0, 0)
        rad = math.radians(self.angle)
        
        if self.moving_forward:
            move_vec.x += math.cos(rad) * move_speed
            move_vec.y += math.sin(rad) * move_speed
        if self.moving_back:
            move_vec.x -= math.cos(rad) * move_speed
            move_vec.y -= math.sin(rad) * move_speed
        if self.strafe_left:
            move_vec.x += math.cos(rad - math.pi/2) * move_speed * 0.7
            move_vec.y += math.sin(rad - math.pi/2) * move_speed * 0.7
        if self.strafe_right:
            move_vec.x += math.cos(rad + math.pi/2) * move_speed * 0.7
            move_vec.y += math.sin(rad + math.pi/2) * move_speed * 0.7
        
        # 应用移动
        if move_vec.length() > 0:
            new_x = self.pos.x + move_vec.x
            new_y = self.pos.y + move_vec.y
            
            if self._can_move_to(new_x, new_y, map_grid):
                self.pos.x = new_x
                self.pos.y = new_y
            else:
                # 尝试分别移动X和Y
                if self._can_move_to(new_x, self.pos.y, map_grid):
                    self.pos.x = new_x
                if self._can_move_to(self.pos.x, new_y, map_grid):
                    self.pos.y = new_y
    
    def _can_move_to(self, x, y, map_grid):
        """碰撞检测 - 边界圆检测"""
        radius = 0.2
        
        # 检查四个边界点
        checks = [
            (x - radius, y - radius),
            (x + radius, y - radius),
            (x - radius, y + radius),
            (x + radius, y + radius),
        ]
        
        for cx, cy in checks:
            # 对于无限地图，直接使用 get_tile 方法
            tile = map_grid.get_tile(cx, cy)
            if tile != 0:
                return False
        
        return True
    
    def _update_sanity(self, dt, entities):
        """更新理智值"""
        # 基础衰减
        self.sanity = max(0, self.sanity - 0.01)
        
        # 靠近实体时加速衰减
        self.near_entity = None
        for entity in entities:
            dx = entity['x'] - self.pos.x
            dy = entity['y'] - self.pos.y
            dist = math.sqrt(dx*dx + dy*dy)
            
            if dist < 2.5:  # 实体影响范围
                self.sanity = max(0, self.sanity - 0.03)
                self.near_entity = entity
                
                # 极近距离恐慌
                if dist < 1.0:
                    self.sanity = max(0, self.sanity - 0.1)
                    break
        
        # 随机惊吓事件
        if self.sanity < 30 and random.random() < 0.001:
            self.sanity = max(0, self.sanity - random.uniform(3, 8))


class BackroomsGame:
    """主游戏类 - 支持伪无限地图"""
    def __init__(self):
        # 初始化系统
        self.renderer = BackroomsRenderer(width=320, height=240, scale=3)
        self.generator = BackroomsGenerator(seed=None)  # 每次新种子
        self.entities = []
        self.items = []  # 可收集道具
        self.player = None
        self.time_elapsed = 0
        
        # 游戏状态
        self.running = True
        self.game_state = "exploring"
        self.last_time = pygame.time.get_ticks()
        self.last_chunk = (0, 0)  # 追踪当前位置区块
        
        # 音频引擎
        self.audio = None
        if HAS_AUDIO:
            self.audio = AmbientAudioEngine()
            if self.audio.init_audio():
                self.audio.start()
                print("Audio: ON (ambient drone + saw synth)")
            else:
                print("Audio: FAILED")
        else:
            print("Audio: DISABLED (sounddevice not installed)")
        
        # 生成初始区块
        self._generate_initial_area()
        
        print("=== 伪无限后室模式 ===")
        print("探索无尽可能的走廊...每次都是新地图！")
        print("Controls: WASD move, Q/E strafe, Shift run, G new map")
    
    def _generate_initial_area(self):
        """生成玩家初始区域"""
        # 寻找安全的初始位置
        for _ in range(100):
            x = self.generator.random.uniform(4, 20)
            y = self.generator.random.uniform(4, 20)
            if self.generator.get_tile(x, y) == 0:
                self.player = BackroomsPlayer(x, y)
                break
        else:
            self.player = BackroomsPlayer(12, 12)
        
        self.player.angle = self.generator.random.uniform(0, 360)
        self._spawn_entities()
        self._spawn_items()
    
    def _spawn_entities(self):
        """在附近生成实体"""
        self.entities = []
        cx, cy = int(self.player.pos.x) // self.generator.chunk_size, int(self.player.pos.y) // self.generator.chunk_size
        
        for _ in range(8):
            angle = self.generator.random.uniform(0, 360)
            dist = self.generator.random.uniform(3, 12)
            x = self.player.pos.x + math.cos(angle) * dist
            y = self.player.pos.y + math.sin(angle) * dist
            
            # 确保生成在空地上
            if self.generator.get_tile(x, y) == 0:
                self.entities.append({
                    'x': x,
                    'y': y,
                    'type': 'static' if self.generator.random.random() > 0.4 else 'animated',
                    'shape': self.generator.random.choice(['square', 'circle']),
                    'id': len(self.entities)
                })
    
    def _spawn_items(self):
        """在附近生成可收集道具"""
        cx, cy = int(self.player.pos.x) // self.generator.chunk_size, int(self.player.pos.y) // self.generator.chunk_size
        
        # 生成杏仁水道具 - 恢复理智
        for _ in range(6):
            angle = self.generator.random.uniform(0, 360)
            dist = self.generator.random.uniform(4, 15)
            x = self.player.pos.x + math.cos(angle) * dist
            y = self.player.pos.y + math.sin(angle) * dist
            
            if self.generator.get_tile(x, y) == 0:
                self.items.append({
                    'x': x,
                    'y': y,
                    'type': 'almond_water',  # 杏仁水
                    'sanity_restore': 20,   # 恢复20点理智
                    'id': len(self.items)
                })
    
    def _check_item_collection(self):
        """检查玩家是否收集到道具"""
        collected = None
        for item in self.items:
            dx = item['x'] - self.player.pos.x
            dy = item['y'] - self.player.pos.y
            dist = math.sqrt(dx*dx + dy*dy)
            
            if dist < 0.5:  # 接触距离
                collected = item
                break
        
        if collected:
            # 恢复理智
            self.player.sanity = min(100, self.player.sanity + collected['sanity_restore'])
            # 播放收集音效提示（通过警告音效短暂触发）
            if self.audio:
                self.audio.warning_timer = 0.3
                self.audio.warning_intensity = 0.5
            # 移除已收集的道具
            self.items.remove(collected)
            return True
        return False
    
    def _generate_level(self):
        """生成新关卡（重新生成初始区域）"""
        self.generator = BackroomsGenerator(seed=None)
        self._generate_initial_area()
    
    def _check_chunk_change(self):
        """检查玩家是否进入新区块，动态更新实体"""
        cx = int(self.player.pos.x) // self.generator.chunk_size
        cy = int(self.player.pos.y) // self.generator.chunk_size
        current_chunk = (cx, cy)
        
        # 预先生成周围区块（提升体验）
        for dx in range(-1, 2):
            for dy in range(-1, 2):
                self.generator.generate_chunk(cx + dx, cy + dy)
        
        # 如果进入了新区块，更新实体和道具
        if current_chunk != self.last_chunk:
            self.last_chunk = current_chunk
            # 移除太远的实体
            self.entities = [e for e in self.entities 
                          if math.sqrt((e['x'] - self.player.pos.x)**2 + 
                                      (e['y'] - self.player.pos.y)**2) < 25]
            # 移除太远的道具
            self.items = [item for item in self.items
                        if math.sqrt((item['x'] - self.player.pos.x)**2 +
                                    (item['y'] - self.player.pos.y)**2) < 25]
            # 生成新实体和道具
            self._spawn_entities()
            self._spawn_items()
    
    def handle_events(self):
        """处理输入事件"""
        events = pygame.event.get()
        
        for event in events:
            if event.type == pygame.QUIT:
                self.running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    self.running = False
                elif event.key == pygame.K_r and self.game_state == "game_over":
                    # 重新开始
                    self._generate_level()
                    self.game_state = "exploring"
                    self.time_elapsed = 0
                elif event.key == pygame.K_g:  # 重新生成关卡
                    self._generate_level()
                elif event.key == pygame.K_f:  # 切换全屏
                    pygame.display.toggle_fullscreen()
        
        # 持续按键检测
        keys = pygame.key.get_pressed()
        self.player.moving_forward = keys[pygame.K_w] or keys[pygame.K_UP]
        self.player.moving_back = keys[pygame.K_s] or keys[pygame.K_DOWN]
        self.player.turn_left = keys[pygame.K_a] or keys[pygame.K_LEFT]
        self.player.turn_right = keys[pygame.K_d] or keys[pygame.K_RIGHT]
        self.player.strafe_left = keys[pygame.K_q]
        self.player.strafe_right = keys[pygame.K_e]
        self.player.running = keys[pygame.K_LSHIFT]
    
    def run(self):
        """游戏主循环"""
        while self.running:
            # 计算帧时间
            current_time = pygame.time.get_ticks()
            dt = current_time - self.last_time
            self.last_time = current_time
            
            # 处理输入
            self.handle_events()
            
            if self.game_state == "exploring":
                # 更新时间
                self.time_elapsed += dt
                
                # 检查是否进入新区块
                self._check_chunk_change()
                
                # 更新玩家
                self.player.update(dt, self.generator, self.entities)
                
                # 检查道具收集
                self._check_item_collection()
                
                # 根据理智值调整音频
                if self.audio:
                    self.audio.set_intensity(self.player.sanity)
                    
                    # 脚步声（基于移动状态和理智值）
                    is_moving = (self.player.moving_forward or self.player.moving_back or 
                               self.player.strafe_left or self.player.strafe_right)
                    if is_moving:
                        # 奔跑时脚步更快更响
                        step_chance = 0.15 if self.player.running else 0.08
                        # 理智低时脚步更随机
                        if self.player.sanity < 50:
                            step_chance *= 1.5
                        if random.random() < step_chance:
                            self.audio.trigger_footstep()
                    
                    # 检测实体接近并触发音效
                    for entity in self.entities:
                        dx = entity['x'] - self.player.pos.x
                        dy = entity['y'] - self.player.pos.y
                        dist = math.sqrt(dx*dx + dy*dy)
                        
                        # 实体警告范围 8 单位
                        if dist < 8:
                            intensity = max(0.3, 1.0 - dist / 8)
                            self.audio.trigger_entity_near(dist)
                        # 实体可见但较远
                        elif dist < 15:
                            if random.random() < 0.01:  # 偶尔触发
                                self.audio.trigger_entity_warning(0.5)
                
                # 渲染
                self.renderer.cast_rays(
                    self.player.pos, 
                    self.player.angle, 
                    self.generator
                )
                self.renderer.render_walls(self.time_elapsed)
                self.renderer.render_entities(
                    self.player.pos, 
                    self.player.angle, 
                    self.entities,
                    self.time_elapsed,
                    fov=90
                )
                # 渲染可收集道具
                self.renderer.render_items(
                    self.player.pos,
                    self.player.angle,
                    self.items,
                    self.time_elapsed,
                    fov=90
                )
                self.renderer.render_effects(self.time_elapsed, self.player.sanity)
                self.renderer.render_ui(self.player.sanity, self.time_elapsed)
                
                # 添加额外氛围效果
                self._add_atmosphere_effects()
                
                # 检查游戏结束
                if self.player.sanity <= 0:
                    self.game_state = "game_over"
            
            elif self.game_state == "game_over":
                self._render_game_over()
            
            # 显示帧率
            fps = self.renderer.clock.get_fps()
            fps_text = self.renderer.font.render(f"FPS: {int(fps)}", 
                                                True, (100, 100, 100))
            self.renderer.display.blit(fps_text, (5, 5))
            
            # 呈现
            self.renderer.present()
        
        pygame.quit()
    
    def _add_atmosphere_effects(self):
        """添加氛围效果"""
        # 随理智值降低增加扭曲
        if self.player.sanity < 30:
            self.renderer.distortion = (30 - self.player.sanity) / 30
        
        # 随机闪烁
        if self.player.sanity < 50 and random.random() < 0.005:
            self.renderer.flicker = random.uniform(0.1, 0.3)
        
        # 应用闪烁
        if self.renderer.flicker > 0:
            flicker_surf = pygame.Surface(self.renderer.display.get_size(), 
                                        pygame.SRCALPHA)
            flicker_surf.fill((255, 255, 255, 
                             int(self.renderer.flicker * 100)))
            self.renderer.display.blit(flicker_surf, (0, 0))
            self.renderer.flicker *= 0.9
        
        # 显示附近的实体
        if self.player.near_entity:
            text = self.renderer.font.render("SOMETHING IS NEAR...", 
                                           True, (200, 100, 100))
            self.renderer.display.blit(text, 
                                     (self.renderer.display.get_width()//2 - 60, 
                                      self.renderer.display.get_height() - 40))
        
        # 显示附近的可收集道具
        for item in self.items:
            dx = item['x'] - self.player.pos.x
            dy = item['y'] - self.player.pos.y
            dist = math.sqrt(dx*dx + dy*dy)
            if dist < 2:  # 靠近时显示提示
                if item['type'] == 'almond_water':
                    text = self.renderer.font.render("Almond Water! Walk over to drink.", 
                                                   True, (100, 180, 255))
                    self.renderer.display.blit(text, 
                                             (self.renderer.display.get_width()//2 - 90, 
                                              self.renderer.display.get_height() - 25))
                break
    
    def _render_game_over(self):
        """渲染游戏结束画面"""
        width, height = self.renderer.display.get_size()
        
        # 半透明覆盖
        overlay = pygame.Surface((width, height))
        overlay.fill((20, 0, 0))
        overlay.set_alpha(180)
        self.renderer.display.blit(overlay, (0, 0))
        
        # 游戏结束文字
        font_large = pygame.font.Font(None, 32)
        font_small = pygame.font.Font(None, 20)
        
        texts = [
            ("YOU ARE LOST", font_large, (200, 50, 50)),
            ("The static consumes you", font_small, (150, 150, 150)),
            ("Press R to restart", font_small, (150, 150, 150)),
            ("Press ESC to quit", font_small, (150, 150, 150)),
        ]
        
        y_offset = height//2 - 50
        for text, font, color in texts:
            rendered = font.render(text, True, color)
            x = width//2 - rendered.get_width()//2
            self.renderer.display.blit(rendered, (x, y_offset))
            y_offset += 30


def main():
    """主函数"""
    print("=== Backrooms Raycaster ===")
    print("Controls: WASD to move, Q/E to strafe, Shift to run")
    print("R: Restart, G: Generate new level, F: Toggle fullscreen")
    print("===========================")
    
    game = None
    try:
        game = BackroomsGame()
        game.run()
    except KeyboardInterrupt:
        print("\nGame interrupted.")
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # 停止音频
        if game and game.audio:
            game.audio.stop()
        pygame.quit()


if __name__ == "__main__":
    main()