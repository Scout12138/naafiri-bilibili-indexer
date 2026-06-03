#!/usr/bin/env python3
"""Extract frames at 2-second intervals from downloaded videos."""
import subprocess, os, sys, csv

# Resolve ffmpeg path with priority:
# 1) Project-local tools/ffmpeg/bin/ffmpeg.exe
# 2) FFMPEG_PATH environment variable
# 3) System PATH (just "ffmpeg")
def _resolve_ffmpeg():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    local = os.path.join(project_root, "tools", "ffmpeg", "bin", "ffmpeg.exe")
    if os.path.isfile(local):
        return local
    env_path = os.environ.get("FFMPEG_PATH", "")
    if env_path and os.path.isfile(env_path):
        return env_path
    return "ffmpeg"

FFMPEG = _resolve_ffmpeg()

VIDEO_DIR = "data/videos"
FRAME_DIR = "data/frames"


def extract(video_path, output_dir, start_number=1):
    os.makedirs(output_dir, exist_ok=True)
    pattern = os.path.join(output_dir, "frame_%06d.jpg")
    cmd = [
        FFMPEG, "-y", "-i", video_path,
        "-vf", "fps=1/2", "-q:v", "2",
        "-start_number", str(start_number), pattern,
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=7200)
    if result.returncode != 0:
        stderr = (result.stderr or b"").decode("utf-8", errors="replace")[-500:]
        print(f"  FFMPEG ERROR (exit {result.returncode}): {stderr}", file=sys.stderr)
        return -1
    return len([f for f in os.listdir(output_dir) if f.endswith(".jpg")])


def main(bv_id):
    # Verify ffmpeg before extraction
    print(f"FFMPEG: {FFMPEG}")
    ver = subprocess.run([FFMPEG, "-version"], capture_output=True, timeout=10)
    if ver.returncode != 0:
        print(f"ERROR: ffmpeg not usable: {ver.stderr.decode('utf-8',errors='replace')[:300]}")
        sys.exit(1)
    ver_line = (ver.stdout or ver.stderr).decode("utf-8", errors="replace").split("\n")[0]
    print(f"  Version: {ver_line}")

    frame_dir = os.path.join(FRAME_DIR, bv_id)
    videos = sorted([
        f for f in os.listdir(VIDEO_DIR)
        if bv_id in f and f.endswith(".mp4")
    ])
    print(f"Video parts: {len(videos)}")
    # Clean existing frames to avoid duplicates on re-run
    if os.path.isdir(frame_dir):
        import shutil
        shutil.rmtree(frame_dir)
        os.makedirs(frame_dir)
    cumulative = 1
    for v in videos:
        path = os.path.join(VIDEO_DIR, v)
        before = len([f for f in os.listdir(frame_dir) if f.endswith(".jpg")]) if os.path.isdir(frame_dir) else 0
        n = extract(path, frame_dir, cumulative)
        if n < 0:
            print(f"  FAILED: {v}")
            sys.exit(1)
        after = len([f for f in os.listdir(frame_dir) if f.endswith(".jpg")]) if os.path.isdir(frame_dir) else 0
        print(f"  {v}: +{after - before} frames (total: {after})")
        cumulative = after + 1

    # Build index
    frames = sorted([f for f in os.listdir(frame_dir) if f.endswith(".jpg")])
    with open(os.path.join(frame_dir, "frames_index.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["frame_file", "timestamp_sec", "timestamp_hms"])
        w.writeheader()
        for i, fn in enumerate(frames):
            ts = i * 2
            w.writerow({
                "frame_file": fn, "timestamp_sec": ts,
                "timestamp_hms": f"{ts//3600:02d}:{(ts%3600)//60:02d}:{ts%60:02d}",
            })
    print(f"Index: {len(frames)} entries")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python extract_frames.py <BV_ID>")
        sys.exit(1)
    from pathlib import Path
    os.chdir(Path(__file__).resolve().parent.parent)
    main(sys.argv[1])
