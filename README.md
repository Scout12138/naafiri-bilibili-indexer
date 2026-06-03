# Naafiri B站录播中单索引 — 一键式自动化工具

从 B站 UP 主「过往的上路游乐场」的游戏录播中，自动识别"中单位出现纳亚菲利"的对局，生成可检索 Excel 索引表。

## 方法

- 每 2 秒抽帧 → 背景粗筛 → OpenCLIP ViT-L/14 识别中单英雄
- 5 分钟窗口合并 + 多帧投票 → 多 P 时间轴映射 → Excel 导出
- 素材库：Data Dragon 16.11.1，2084 张官方 loading 图

---

## 快速开始

### 1. 环境准备（一次性）

```bash
# 安装 Python 依赖
pip install -r requirements.txt

# 下载 LOL 素材库
python scripts/download_assets.py

# 构建 CLIP reference embedding
python scripts/build_embeddings.py
```

### 2. 准备 cookies

每次运行前，需要提供新的 B站 Netscape 格式 cookies：
1. 浏览器安装扩展 **"Get cookies.txt LOCALLY"**
2. 打开 `bilibili.com` 确保已登录
3. 点击扩展图标 → Export cookies.txt
4. 保存到项目目录或任意位置

### 3. 一键运行

```bash
# 处理指定视频
python run_pipeline.py --bv BV1xKVC6NEw2

# 处理 UP主最新 3 个长录播
python run_pipeline.py --latest 3

# 跳过下载（视频已存在时）
python run_pipeline.py --bv BV1xKVC6NEw2 --skip-download

# 跳过环境检查（已确认环境无误时）
python run_pipeline.py --latest 1 --skip-env
```

**程序会自动：**
1. 🧪 检查环境（Python依赖、CUDA、ffmpeg、素材库、模型）
2. 🍪 提示输入 cookies 路径 → 验证登录状态
3. 🔍 发现目标视频（指定 BV 或 UP主最新长录播）
4. ✅ 确认 720p 可用 → 下载全部 P
5. 🎬 抽帧（2秒/帧）
6. 🤖 OpenCLIP ViT-L/14 英雄识别
7. 🐺 Naafiri 判定 → 5分钟窗口合并投票
8. 📊 生成 Excel 索引表 + 汇总报告

---

## 当前结果

### 试运行 3 个视频 (ViT-L/14)

| BV号 | 对局数 | 日期 |
|------|:--:|------|
| BV1hgVQ6eEzh | 6 | 2026-05-31 |
| BV1L1VJ6nE7n | 7 | 2026-05-31 |
| BV1HsVL6EEGc | 6 | 2026-05-30 |

详见 `output/` 目录。

### 最新验证 (2026-06-03)

| BV号 | 对局数 | 置信度 |
|------|:--:|:--:|
| BV1xKVC6NEw2 | 5 | 全部高置信度 |

---

## 配置

所有参数集中在 `config.json`：
- 裁剪坐标、CLIP 阈值、置信度阈值
- UP主主页、下载格式、排除关键词
- 所有目录路径、模型配置

修改 `config.json` 即可调整行为，无需修改代码。

---

## 产出

| 文件 | 路径 | 说明 |
|------|------|------|
| 单视频 Excel | `output/naafiri_mid_index_{BV}_final_v2.xlsx` | 包含截图嵌入 |
| 汇总报告 | `output/pipeline_report.txt` | 多视频批处理汇总 |
| 抽帧 | `data/frames/{BV}/` | 原始帧 + frames_index.csv |
| 截图 | `data/screenshots/{BV}/` | 每局完整加载界面截图 |
| 视频 | `data/videos/` | 720p mp4 + info.json |

---

## 目录结构

```
learn_lol_naafiri/
├── run_pipeline.py          ← 统一入口，一键运行
├── config.json              ← 所有可配置参数
├── README.md
├── WORKFLOW.md              ← 详细技术文档
├── requirements.txt
├── scripts/
│   ├── env_check.py         ← 环境检查
│   ├── bilibili_utils.py    ← B站 API + 下载 + cookies验证
│   ├── extract_frames.py    ← 抽帧（ffmpeg）
│   ├── pipeline_video.py    ← 主识别管线
│   ├── download_assets.py   ← 下载素材库
│   ├── build_embeddings.py  ← 构建 embedding
│   └── benchmark.py         ← 模型 benchmark
├── tools/ffmpeg/bin/        ← 项目内置 ffmpeg
├── data/
│   ├── assets/lol_loading_v2/  ← 2084 张 loading 图
│   ├── crops/ref_v2_vit_l14.pkl ← CLIP embedding
│   ├── videos/              ← 下载的 720p 视频
│   └── frames/              ← 抽帧结果
└── output/                  ← Excel + 报告
```

---

## 故障排除

| 问题 | 原因 | 解决 |
|------|------|------|
| cookies 验证失败 | cookies 过期 | 重新导出 cookies.txt |
| 720p 不可用 | B站未登录或视频不支持 | 检查 cookies 登录状态 |
| ffmpeg 未找到 | PATH 问题 | 程序自动使用 `tools/ffmpeg/bin/` |
| 素材库缺失 | 未运行准备步骤 | `python scripts/download_assets.py` |
| 0 局识别 | 视频无 Naafiri 对局 | 检查视频内容，正常情况 |
| CUDA 不可用 | PyTorch CUDA 版本不对 | 程序会自动 fallback 到 CPU |

---

## 完整文档

- [WORKFLOW.md](WORKFLOW.md) — 技术详设、参数、扩展指南
- [config.json](config.json) — 所有可调参数及说明
