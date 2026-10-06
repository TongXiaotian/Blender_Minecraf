"""全局常量：区块尺寸、世界高度、面朝向等。"""

# ---------------- 世界尺寸 ----------------
CHUNK_X = 16          # 区块 X 方向方块数
CHUNK_Z = 16          # 区块 Z 方向方块数
WORLD_H = 128         # 世界高度（方块）
SEA_LEVEL = 62        # 海平面高度
BEDROCK_LEVEL = 0     # 基岩层

# ---------------- 面朝向 ----------------
FACE_PX = 0   # +X （东）
FACE_NX = 1   # -X （西）
FACE_PY = 2   # +Y （上，方块空间的 Y 是高度轴）
FACE_NY = 3   # -Y （下）
FACE_PZ = 4   # +Z （南）
FACE_NZ = 5   # -Z （北）
FACES = 6

# 面明亮度（模仿 Minecraft 的固定面光照：顶面最亮、底面最暗）
FACE_SHADE = {
    FACE_PX: 0.62,
    FACE_NX: 0.62,
    FACE_PY: 1.00,
    FACE_NY: 0.48,
    FACE_PZ: 0.82,
    FACE_NZ: 0.82,
}

# ---------------- 贴图图集 ----------------
ATLAS_COLS = 16
ATLAS_ROWS = 16
TILE_PX = 16
ATLAS_PX = ATLAS_COLS * TILE_PX   # 256

# ---------------- 玩家参数（尽量贴近原版数值） ----------------
PLAYER_WIDTH = 0.6
PLAYER_HEIGHT = 1.8
PLAYER_EYE = 1.62           # 视点高度
GRAVITY = 32.0              # 原版约 32 m/s^2
JUMP_SPEED = 8.95           # 跳跃高度约 1.25 格
WALK_SPEED = 4.317          # 原版行走速度
SPRINT_SPEED = 5.612        # 原版疾跑
SNEAK_SPEED = 1.3
FLY_SPEED = 10.9
SWIM_SPEED = 2.2
TERMINAL_VELOCITY = 78.4
REACH = 5.0                 # 交互距离
STEP_HEIGHT = 0.6

# ---------------- 渲染 ----------------
DEFAULT_RENDER_DISTANCE = 5   # 区块半径
MAX_RENDER_DISTANCE = 12
CHUNK_MESH_BUDGET = 1         # 每帧最多生成的区块数
FOV = 70.0
NEAR_CLIP = 0.05
FAR_CLIP = 1000.0

# ---------------- 颜色（UI） ----------------
UI_TEXT = (1.0, 1.0, 1.0, 1.0)
UI_TEXT_SHADOW = (0.0, 0.0, 0.0, 0.65)
HOTBAR_SLOT = (0.0, 0.0, 0.0, 0.55)
HOTBAR_SEL = (1.0, 1.0, 1.0, 0.9)
