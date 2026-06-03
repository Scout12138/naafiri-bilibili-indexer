# Workflow — Naafiri 中单索引构建（技术详设）

## 环境依赖

| 组件 | 版本/说明 | 安装方式 |
|------|-----------|----------|
| Python | 3.11+ (推荐 conda env `agent-reach`) | conda / 系统安装 |
| PyTorch | 2.6+ CUDA 12.4 | pip install torch |
| open-clip-torch | 最新版 | pip install open-clip-torch |
| opencv-python | 4.x | pip install opencv-python |
| xlsxwriter | 最新版 | pip install xlsxwriter |
| pillow | 最新版 | pip install pillow |
| numpy | 最新版 | pip install numpy |
| requests | 最新版 | pip install requests |
| yt-dlp | 2026.03+ | pip install yt-dlp |
| ffmpeg | 8.1.1+ | 已内置在 `tools/ffmpeg/bin/` |
| GPU | RTX 4050 6GB+ 或 CPU fallback | |

### ffmpeg 设置

项目依赖 ffmpeg 抽帧，需将 ffmpeg 放到 `tools/ffmpeg/bin/`：

```bash
mkdir -p tools/ffmpeg/bin
# 从 https://ffmpeg.org/download.html 下载 Windows 版本
# 将 ffmpeg.exe, ffprobe.exe, ffplay.exe 复制到 tools/ffmpeg/bin/
```

### 一键安装

```bash
pip install -r requirements.txt
```

## 目录结构（完整版）

```
learn_lol_naafiri/
├── run_pipeline.py            # ★ 统一入口
├── config.json                # ★ 所有参数
├── README.md                  # 用户文档
├── WORKFLOW.md                # 本文档
├── requirements.txt           # Python 依赖
├── gold_set_naafiri_loading_from_screenshot.csv  # 人工标注 (16条)
│
├── scripts/
│   ├── env_check.py           # 环境自检 (依赖/CUDA/ffmpeg/素材/embedding)
│   ├── bilibili_utils.py      # B站工具集 (cookies验证/视频发现/720p检查/下载)
│   ├── extract_frames.py      # ffmpeg抽帧 (2秒/帧, 项目内ffmpeg优先)
│   ├── pipeline_video.py      # ★ 主管线 (粗筛→CLIP→Naafiri判定→合并→Excel)
│   ├── download_assets.py     # 下载 Data Dragon loading 图
│   ├── audit_assets.py        # 素材库完整性审计
│   ├── build_embeddings.py    # 构建 ViT-L/14 reference embedding
│   ├── benchmark.py           # Gold set 模型 benchmark
│   └── _fetch_video_info.py   # B站 wbi API 工具 (开发用)
│
├── tools/
│   └── ffmpeg/bin/            # 项目内置 ffmpeg (ffmpeg/ffprobe/ffplay)
│
├── data/
│   ├── assets/
│   │   ├── lol_loading_v2/    # 2084 张官方 loading 图 (Data Dragon 16.11.1)
│   │   └── champion_map_v2.csv # 英雄映射表 (en/cn/skin_id)
│   ├── crops/
│   │   └── ref_v2_vit_l14.pkl # ViT-L/14 reference embedding (2084×768)
│   ├── videos/                # 下载的 720p mp4 + .info.json
│   ├── frames/                # 抽帧 BV*/frame_xxxxxx.jpg + frames_index.csv
│   └── screenshots/           # 每局完整加载界面截图
│
├── output/                    # Excel + 报告
└── archive_deprecated/        # 废弃文件 (可删除)
```

## 管线流程（详细）

```
┌─────────────────────────────────────────────────────────┐
│ 1. 环境检查 (env_check.py)                               │
│    ├─ Python 依赖 (numpy, torch, open_clip, cv2, ...)    │
│    ├─ CUDA 可用性                                        │
│    ├─ ffmpeg 路径 (tools/ffmpeg/bin/ → FFMPEG_PATH → PATH)│
│    ├─ 素材库 v2 + champion_map_v2.csv                    │
│    └─ Reference embedding cache                          │
├─────────────────────────────────────────────────────────┤
│ 2. Cookies 验证 (bilibili_utils.py)                      │
│    ├─ 解析 Netscape cookies.txt (支持 #HttpOnly_)        │
│    ├─ POST /nav → isLogin=true?                          │
│    └─ 失败则提示重新导出 cookies                          │
├─────────────────────────────────────────────────────────┤
│ 3. 视频发现 (bilibili_utils.py)                          │
│    ├─ --bv 模式: wbi API 获取单视频信息                   │
│    └─ --latest 模式:                                     │
│        ├─ yt-dlp --flat-playlist 获取最新 BV 列表         │
│        ├─ wbi API 逐个获取详情 (时长/标题/分P)            │
│        └─ 筛选: ≥10min, 排除关键词 (切片/集锦/高光/...)   │
├─────────────────────────────────────────────────────────┤
│ 4. 下载 (bilibili_utils.py)                              │
│    ├─ yt-dlp -F 确认 720p (1280x720)                     │
│    ├─ yt-dlp -f 30064+30280 下载全部分P                  │
│    ├─ --write-info-json 保存元数据                        │
│    └─ OpenCV 验证首文件分辨率 = 1280×720                  │
├─────────────────────────────────────────────────────────┤
│ 5. 抽帧 (extract_frames.py)                               │
│    ├─ ffmpeg -vf fps=1/2 -q:v 2 每2秒1帧                 │
│    ├─ 多P顺序拼接，frame_000001 起连续编号                 │
│    └─ 生成 frames_index.csv (timestamp_sec + hms)         │
├─────────────────────────────────────────────────────────┤
│ 6. 主管线 (pipeline_video.py)                             │
│    ├─ 粗筛: 暗背景 + 卡片亮度差 + 纹理方差 ≥ 3/3          │
│    ├─ CLIP: ViT-L/14 编码 top/bottom 中单卡片              │
│    ├─ 匹配: 与 2084 张 reference embedding 余弦相似度     │
│    ├─ Naafiri判定: sim≥0.76 AND gap≥0.03                  │
│    ├─ 5min窗口合并: 同对手多帧投票取最高sim               │
│    ├─ 置信度: 高(sim≥0.82,gap≥0.06) 中(≥0.78,≥0.04) 低   │
│    └─ 多P时间轴映射: info.json → Web URL timestamp         │
├─────────────────────────────────────────────────────────┤
│ 7. Excel 导出 (pipeline_video.py)                         │
│    ├─ 冻结表头 + 自动筛选                                 │
│    ├─ 嵌入完整截图 (scale 0.22)                           │
│    ├─ B站跳转链接 (精确到秒)                               │
│    └─ Top3 候选 + 投票详情                                │
└─────────────────────────────────────────────────────────┘
```

## 运行命令参考

### 用户命令

```bash
# 处理指定 BV
python run_pipeline.py --bv BV1xKVC6NEw2

# 处理最新 3 个长录播
python run_pipeline.py --latest 3

# 跳过下载（视频已存在）
python run_pipeline.py --bv BV1xKVC6NEw2 --skip-download

# 跳过环境检查（已确认）
python run_pipeline.py --latest 1 --skip-env
```

### 开发者命令

```bash
# 单独运行环境检查
python scripts/env_check.py

# 单独验证 cookies
python scripts/_verify_cookies.py

# 单独获取视频信息
python scripts/_fetch_video_info.py

# 单独抽帧
python scripts/extract_frames.py BV1xKVC6NEw2

# 单独运行管线
python scripts/pipeline_video.py BV1xKVC6NEw2

# 素材库准备 (仅需一次)
python scripts/download_assets.py
python scripts/build_embeddings.py

# 模型 benchmark
python scripts/benchmark.py
```

## 关键参数 (config.json)

| 参数组 | 参数 | 默认值 | 说明 |
|--------|------|--------|------|
| **crop** | top_mid | x=556,y=61,w=163,h=240 | 上方中单卡片裁剪 |
| | bottom_mid | x=556,y=411,w=163,h=240 | 下方中单卡片裁剪 |
| **pipeline** | target_champion | Naafiri | 目标英雄英文名 |
| | merge_window_sec | 300 | 同局合并窗口(秒) |
| | clip_sim_threshold | 0.76 | Naafiri匹配最低相似度 |
| | clip_gap_threshold | 0.03 | Top1-Top2最小差距 |
| | confidence.high | sim≥0.82,gap≥0.06 | 高置信度阈值 |
| | confidence.medium | sim≥0.78,gap≥0.04 | 中置信度阈值 |
| **download** | format | 30064+30280 | B站720p视频+音频流ID |
| | target_resolution | 1280x720 | 期望分辨率 |
| **filter** | min_duration_min | 10 | 最短时长(分钟) |
| | exclude_keywords | [切片,集锦,高光,...] | 排除的标题关键词 |
| **models** | clip_model | ViT-L-14 | OpenCLIP 模型 |
| | device | cuda | 推理设备 |
| **paths** | ffmpeg_dir | tools/ffmpeg/bin | ffmpeg优先查找路径 |

## 错误处理指南

所有错误都会打印明确原因和建议操作：

| 错误 | 程序输出示例 | 修复 |
|------|-------------|------|
| config.json 缺失 | `FATAL: config.json not found` | 从项目模板恢复 config.json |
| Python 依赖缺失 | `[DEPS] ✗ opencv-python — pip install opencv-python` | `pip install -r requirements.txt` |
| ffmpeg 未找到 | `[FFMPEG] NOT FOUND!` | 复制 ffmpeg 到 `tools/ffmpeg/bin/` |
| 素材库缺失 | `[ASSETS] MISSING — data/assets/lol_loading_v2` | `python scripts/download_assets.py` |
| Embedding 缺失 | `[REF] Cache not found` | `python scripts/build_embeddings.py` |
| CUDA 不可用 | `[CUDA] NOT available — will use CPU` | 检查 PyTorch CUDA 版本；程序自动 CPU |
| cookies 过期 | `Cookies 验证失败: Not logged in` | 重新导出 cookies.txt |
| 720p 不可用 | `No 720p format found` | 检查 cookies 登录；视频可能只有低分辨率 |
| 下载分辨率不对 | `Resolution mismatch: expected 1280x720, got 852x480` | 检查 yt-dlp format 配置 |
| 抽帧失败 | `FFMPEG ERROR (exit 1)` | 检查 ffmpeg 和磁盘空间 |
| 0 局识别 | `Games: 0` | 检查视频内容；可能确实无 Naafiri 出场 |

## 扩展到更多视频

1. `python run_pipeline.py --latest N` — 自动处理最新 N 个
2. 或 `python run_pipeline.py --bv BVxx` — 逐个处理
3. 输出统一在 `output/`，按 BV 号区分
4. `output/pipeline_report.txt` 汇总所有结果

## 更新素材库

当 LOL 新英雄发布时需要更新素材库：
```bash
# 重新下载素材 (会自动获取最新 Data Dragon 版本)
python scripts/download_assets.py

# 重新构建 embedding
python scripts/build_embeddings.py

# 运行审计确认完整性
python scripts/audit_assets.py
```
