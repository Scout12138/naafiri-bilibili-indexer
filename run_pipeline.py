#!/usr/bin/env python3
"""
Naafiri B站录播中单索引 — 统一入口程序
=========================================
用法:
  python run_pipeline.py --bv BV1xKVC6NEw2          # 处理指定视频
  python run_pipeline.py --latest 3                  # 处理UP主最新3个长录播

流程:
  环境检查 → cookies验证 → 720p确认 → 下载 → 抽帧 →
  粗筛 → OpenCLIP识别 → Naafiri判定 → 合并投票 → Excel导出
"""
import argparse, json, os, sys, time, subprocess
from datetime import datetime


# ─── Helpers ─────────────────────────────────────────────────────────────
def log(msg, level="INFO"):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [{level}] {msg}")


def fatal(msg):
    log(msg, "FATAL")
    sys.exit(1)


def load_config():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, "config.json")
    if not os.path.isfile(config_path):
        fatal(f"config.json not found at {config_path}")
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_cookies_path():
    """Prompt user for cookies.txt path."""
    print("\n" + "=" * 60)
    print("B站 cookies 验证")
    print("=" * 60)
    print("请提供 Netscape 格式的 cookies.txt 文件路径。")
    print("可通过浏览器扩展 'Get cookies.txt LOCALLY' 导出。")
    print()
    path = input("cookies.txt 路径 (直接回车使用 ./cookies.txt): ").strip()
    # Strip BOM (U+FEFF) that may come from piped input on Windows
    path = path.lstrip("﻿").strip()
    if not path:
        path = "cookies.txt"
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        fatal(f"文件不存在: {path}")
    log(f"使用 cookies: {path}")
    return path


# ─── Pipeline steps ──────────────────────────────────────────────────────
def step_env_check(config):
    """Run environment checks."""
    log("Step 1/6: 环境检查")
    from scripts.env_check import run_all_checks
    if not run_all_checks(config):
        fatal("环境检查未通过，请修复上述问题后重试。")

def step_cookies_verify(cookies_path):
    """Verify cookies login."""
    log("Step 2/6: cookies 验证")
    from scripts.bilibili_utils import verify_bilibili_login
    ok, uname, msg = verify_bilibili_login(cookies_path)
    if not ok:
        fatal(f"Cookies 验证失败: {msg}\n请重新导出 cookies.txt 后重试。")
    return uname

def get_output_xlsx_path(bv_id, config):
    """Return expected output Excel path for a BV."""
    out_dir = config.get("paths", {}).get("output_dir", "output")
    return os.path.join(out_dir, f"naafiri_mid_index_{bv_id}_final_v2.xlsx")


def is_already_processed(bv_id, config):
    """Check if a BV has already been processed (output Excel exists and > 1KB)."""
    path = get_output_xlsx_path(bv_id, config)
    if os.path.isfile(path) and os.path.getsize(path) > 1024:
        return True
    return False


def step_discover_videos(args, config):
    """Discover target videos based on mode."""
    log("Step 3/6: 确定目标视频")

    if args.bv:
        # Single BV mode
        if not args.force and is_already_processed(args.bv, config):
            path = get_output_xlsx_path(args.bv, config)
            log(f"  跳过: {args.bv} 已处理 (→ {path})")
            log(f"  使用 --force 可强制重新处理")
            return [], 1  # (empty list, skipped count)

        from scripts.bilibili_utils import get_video_info
        info = get_video_info(args.bv)
        if not info:
            fatal(f"无法获取视频信息: {args.bv}\n请检查BV号是否正确。")
        dur = info.get("duration", 0)
        title = info.get("title", "")
        parts = info.get("videos", 1)
        log(f"  目标: {args.bv} | {parts}P | {dur//60}m{dur%60:02d}s | {title[:60]}")
        return [{
            "bv_id": args.bv,
            "title": title,
            "duration_sec": dur,
            "parts": parts,
        }], 0

    elif args.latest:
        # Latest N mode
        n = args.latest
        mid = config.get("up主", {}).get("mid", 70971218)
        log(f"  获取UP主 mid={mid} 最新视频...")

        from scripts.bilibili_utils import fetch_latest_videos, filter_long_recordings
        # Fetch more than requested to compensate for already-processed ones
        fetch_count = max(n * 5, 50)
        latest_bvs = fetch_latest_videos(mid, count=fetch_count)
        if not latest_bvs:
            fatal("无法获取UP主视频列表。请检查网络连接。")

        candidates = filter_long_recordings(latest_bvs, config)
        if not candidates:
            fatal("未找到符合条件的长录播。请检查筛选关键词配置。")

        # Filter out already-processed (unless --force)
        skipped = 0
        if not args.force:
            new_candidates = []
            for v in candidates:
                if is_already_processed(v["bv_id"], config):
                    skipped += 1
                else:
                    new_candidates.append(v)
            if skipped:
                log(f"  自动跳过 {skipped} 个已处理视频 (--force 可强制重处理)")
            candidates = new_candidates

        if not candidates:
            log(f"  所有 {skipped} 个候选视频均已处理过，无需重复。")
            return [], skipped

        selected = candidates[:n]
        log(f"  待处理: {len(selected)} 个 (跳过 {skipped} 个已处理)")
        for v in selected:
            log(f"    {v['bv_id']} | {v['parts']}P | {v['duration_sec']//60}m | {v['title'][:50]}")
        return selected, skipped

    else:
        fatal("请指定 --bv <BV号> 或 --latest <数量>")

def step_download(cookies_path, video, config):
    """Download a single video."""
    bv = video["bv_id"]
    log(f"  下载: {bv}")

    from scripts.bilibili_utils import check_720p_available, download_video
    ok, msg = check_720p_available(cookies_path, bv)
    if not ok:
        fatal(f"720p 不可用: {bv} — {msg}\n请检查cookies是否有效或该视频是否支持720p。")

    ok, files, msg = download_video(cookies_path, bv, config)
    if not ok:
        fatal(f"下载失败: {bv} — {msg}")
    return files

def step_extract_frames(bv_id, config):
    """Extract frames for a single video."""
    log(f"  抽帧: {bv_id}")
    result = subprocess.run(
        [sys.executable, "scripts/extract_frames.py", bv_id],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=7200,
    )
    if result.returncode != 0:
        stderr = (result.stderr or "")[-500:]
        fatal(f"抽帧失败: {bv_id}\n{stderr}")
    # Parse frame count from output
    stdout = result.stdout or ""
    for line in stdout.splitlines():
        if "Index:" in line:
            log(f"    {line.strip()}")
    return True

def step_pipeline(bv_id, config):
    """Run the main pipeline (CLIP → Naafiri → Excel)."""
    log(f"  识别: {bv_id}")
    result = subprocess.run(
        [sys.executable, "scripts/pipeline_video.py", bv_id],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=7200,
    )
    stdout = result.stdout or ""
    stderr = result.stderr or ""

    if result.returncode != 0:
        fatal(f"Pipeline 失败: {bv_id}\n{stderr[-500:]}")

    # Parse summary
    games = 0
    low = 0
    for line in stdout.splitlines():
        if "Games:" in line:
            try: games = int(line.split("Games:")[1].strip())
            except: pass
        if "low confidence" in line or "low conf" in line.lower():
            try: low = int(line.split(",")[1].strip().split()[0])
            except: pass
    log(f"    结果: {games} 局Naafiri, {low} 低置信度")
    return games, low

def step_generate_report(results, config, skipped=0):
    """Generate batch summary report."""
    log("Step 6/6: 生成汇总报告")
    out_dir = config.get("paths", {}).get("output_dir", "output")
    os.makedirs(out_dir, exist_ok=True)

    report_path = os.path.join(out_dir, "pipeline_report.txt")
    total_games = sum(r.get("games", 0) for r in results)
    total_low = sum(r.get("low_conf", 0) for r in results)

    lines = [
        "=" * 60,
        "Naafiri B站录播中单索引 — 运行报告",
        f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "=" * 60,
        "",
    ]

    for i, r in enumerate(results):
        lines.append(f"[{i+1}] {r['bv_id']}")
        lines.append(f"    标题: {r.get('title', '?')[:60]}")
        lines.append(f"    分P: {r.get('parts', '?')} | 720p: {r.get('resolution', '?')}")
        lines.append(f"    总帧数: {r.get('total_frames', '?')} | 粗筛通过: {r.get('coarse_pass', '?')}")
        lines.append(f"    Naafiri对局: {r.get('games', '?')} | 低置信度: {r.get('low_conf', '?')}")
        lines.append(f"    Excel: {r.get('xlsx', '?')}")
        notes = r.get("notes", "")
        if notes:
            lines.append(f"    备注: {notes}")
        lines.append("")

    lines.append(f"合计: {len(results)} 视频, {total_games} 局, {total_low} 低置信度")
    if skipped:
        lines.append(f"跳过: {skipped} 个已处理视频")
    lines.append("=" * 60)

    report = "\n".join(lines)
    print("\n" + report)

    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)
    log(f"报告已保存: {report_path}")


# ─── Main ────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Naafiri B站录播中单索引 — 一键式自动化工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python run_pipeline.py --bv BV1xKVC6NEw2
  python run_pipeline.py --latest 3
  python run_pipeline.py --bv BV1xKVC6NEw2 --skip-download  # 跳过下载(已下载时)
        """,
    )
    parser.add_argument("--bv", type=str, help="指定单个BV号处理")
    parser.add_argument("--latest", type=int, help="处理UP主最新N个长录播")
    parser.add_argument("--skip-download", action="store_true", help="跳过下载步骤(视频已存在)")
    parser.add_argument("--skip-env", action="store_true", help="跳过环境检查")
    parser.add_argument("--force", action="store_true", help="强制重新处理已输出过的视频")
    args = parser.parse_args()

    if not args.bv and not args.latest:
        parser.print_help()
        fatal("请指定 --bv 或 --latest")

    # Load config
    config = load_config()
    log(f"项目目录: {os.path.dirname(os.path.abspath(__file__))}")

    # 1. Environment check
    if not args.skip_env:
        step_env_check(config)

    # 2. Cookies
    cookies_path = get_cookies_path()
    uname = step_cookies_verify(cookies_path)

    # 3. Discover videos
    videos, skipped = step_discover_videos(args, config)
    if not videos:
        if skipped:
            log(f"全部 {skipped} 个视频已处理过，没有新视频需要处理。")
        else:
            fatal("没有找到目标视频。")
        return

    # 4-5. Process each video
    log(f"Step 4/6: 下载 ({len(videos)} 个视频)")
    log(f"Step 5/6: 抽帧 + 识别")
    print()

    results = []
    for i, v in enumerate(videos):
        bv = v["bv_id"]
        log(f"=== [{i+1}/{len(videos)}] {bv} ===")

        try:
            # Download
            if not args.skip_download:
                step_download(cookies_path, v, config)
            else:
                log(f"  跳过下载 (--skip-download)")

            # Extract frames
            step_extract_frames(bv, config)

            # Run pipeline
            games, low = step_pipeline(bv, config)

            # Collect results
            frame_dir = os.path.join(config["paths"]["frame_dir"], bv)
            total_frames = 0
            coarse_pass = 0
            if os.path.isdir(frame_dir):
                total_frames = len([f for f in os.listdir(frame_dir) if f.endswith(".jpg")])

            results.append({
                "bv_id": bv,
                "title": v.get("title", ""),
                "parts": v.get("parts", "?"),
                "resolution": config["download"]["target_resolution"],
                "total_frames": total_frames,
                "coarse_pass": coarse_pass,
                "games": games,
                "low_conf": low,
                "xlsx": f"output/naafiri_mid_index_{bv}_final_v2.xlsx",
                "notes": "",
            })

        except SystemExit:
            raise
        except Exception as e:
            log(f"  错误: {bv} — {e}", "ERROR")
            results.append({
                "bv_id": bv,
                "title": v.get("title", ""),
                "parts": v.get("parts", "?"),
                "resolution": "?",
                "total_frames": 0,
                "coarse_pass": 0,
                "games": 0,
                "low_conf": 0,
                "xlsx": "",
                "notes": f"处理失败: {e}",
            })

    # 6. Report
    step_generate_report(results, config, skipped)

    # Done
    total_games = sum(r["games"] for r in results)
    summary = f"全部完成! 处理 {len(videos)} 个视频, {total_games} 局Naafiri对局"
    if skipped:
        summary += f", 跳过 {skipped} 个已处理"
    log(summary)
    if any(r["notes"] for r in results):
        log(f"有 {sum(1 for r in results if r['notes'])} 个视频存在异常，请查看报告。", "WARN")


if __name__ == "__main__":
    main()
