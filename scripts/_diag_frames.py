"""Diagnose frame doubling issue for BV19aGU6ZEtW."""
import json, os, csv

video_dir = "data/videos"
total_dur = 0
for fn in sorted(os.listdir(video_dir)):
    if "BV19aGU6ZEtW" not in fn or not fn.endswith(".info.json") or "NA_" in fn:
        continue
    with open(os.path.join(video_dir, fn), encoding="utf-8") as f:
        d = json.load(f)
    dur = int(d.get("duration", 0))
    total_dur += dur
    pid = d.get("id", "")
    print(f"  {pid}: {dur}s = {dur//60}m{dur%60}s")

print(f"\n视频总时长: {total_dur}s = {total_dur//60}m{total_dur%60}s")

n = 0
last_ts = 0
with open("data/frames/BV19aGU6ZEtW/frames_index.csv") as f:
    for row in csv.DictReader(f):
        last_ts = int(row["timestamp_sec"])
        n += 1

print(f"帧数: {n}")
print(f"帧时间范围: 0s - {last_ts}s = {last_ts//3600}h{(last_ts%3600)//60}m")
print(f"溢出: {last_ts - total_dur}s = {(last_ts-total_dur)//60}min 完全超出视频")
print(f"帧号 > {total_dur//2} (= {n - total_dur//2} 帧) 来自重复抽帧，时间戳无意义")
