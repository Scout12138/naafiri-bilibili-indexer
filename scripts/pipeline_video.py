#!/usr/bin/env python3
"""
Final pipeline: OpenCLIP ViT-L/14, v2 assets, full 3-video validation.
Outputs per-video Excel with Top3 candidates + summary.
"""
import csv, os, time, pickle, json, re, shutil
import numpy as np, torch, cv2
from PIL import Image
import open_clip, xlsxwriter
from collections import defaultdict
from datetime import datetime

DEVICE = "cuda"
ASSETS_DIR = "data/assets/lol_loading_v2"
CHAMPION_MAP = "data/assets/champion_map_v2.csv"
REF_CACHE = "data/crops/ref_v2_vit_l14.pkl"
FRAME_DIR = "data/frames"
VIDEO_DIR = "data/videos"
OUT_DIR = "output"
TARGET = "Naafiri"
MERGE_WINDOW = 300

TOP = {"x": 556, "y": 61, "w": 163, "h": 240}
BOT = {"x": 556, "y": 411, "w": 163, "h": 240}
targets = ["BV1hgVQ6eEzh", "BV1L1VJ6nE7n", "BV1HsVL6EEGc"]

print(f"Device: {DEVICE}")

# ===== Load reference =====
ref_paths, ref_champs, ref_skins_list = [], [], []
with open(CHAMPION_MAP, "r", encoding="utf-8-sig") as f:
    for row in csv.DictReader(f):
        p = os.path.join(ASSETS_DIR, row["image_path"])
        if os.path.exists(p):
            ref_paths.append(p); ref_champs.append(row["champion_en"])
            ref_skins_list.append(int(row["skin_num"]))
print(f"Refs: {len(ref_paths)} images")

# Load Chinese names
cn_map = {}
with open(CHAMPION_MAP, "r", encoding="utf-8-sig") as f:
    for row in csv.DictReader(f):
        cn_map[row["champion_en"]] = row["champion_cn"]

# ===== Load ViT-L/14 =====
print("Loading OpenCLIP ViT-L/14...")
model, _, preprocess = open_clip.create_model_and_transforms(
    "ViT-L-14", pretrained="datacomp_xl_s13b_b90k"
)
model = model.to(DEVICE); model.eval()

with open(REF_CACHE, "rb") as f:
    cache = pickle.load(f)
ref_embs = cache["embeddings"].to(DEVICE)
print(f"  Ref cache: {len(ref_embs)} embeddings")

def encode_crop(crop_bgr):
    pil = Image.fromarray(cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2RGB))
    t = preprocess(pil).unsqueeze(0).to(DEVICE)
    with torch.no_grad():
        e = model.encode_image(t); return e / e.norm(dim=-1, keepdim=True)

# ===== Coarse filter =====
def coarse_filter_frame(img):
    h, w = img.shape[:2]
    y1, y2 = int(h*0.15), int(h*0.85)
    left = img[y1:y2, 0:int(w*0.10)]
    right = img[y1:y2, int(w*0.90):w]
    top_mid = img[TOP["y"]:TOP["y"]+TOP["h"], TOP["x"]:TOP["x"]+TOP["w"]]
    bot_mid = img[BOT["y"]:BOT["y"]+BOT["h"], BOT["x"]:BOT["x"]+BOT["w"]]
    def bg_feat(bg):
        hsv = cv2.cvtColor(bg, cv2.COLOR_BGR2HSV)
        n = hsv.shape[0]*hsv.shape[1]
        m = np.zeros((hsv.shape[0],hsv.shape[1]),dtype=np.uint8)
        m = cv2.bitwise_or(m, cv2.inRange(hsv,(35,30,0),(85,255,80)))
        m = cv2.bitwise_or(m, cv2.inRange(hsv,(90,20,0),(140,255,80)))
        m = cv2.bitwise_or(m, cv2.inRange(hsv,(0,0,0),(180,255,30)))
        return cv2.countNonZero(m)/n*100, hsv[:,:,2].mean()
    ld,lv = bg_feat(left); rd,rv = bg_feat(right)
    v_bg = (lv+rv)/2
    top_g = cv2.cvtColor(top_mid, cv2.COLOR_BGR2GRAY)
    bot_g = cv2.cvtColor(bot_mid, cv2.COLOR_BGR2GRAY)
    dv = (top_g.mean()+bot_g.mean())/2 - v_bg
    top_tex = cv2.Laplacian(top_g, cv2.CV_64F).var()
    bot_tex = cv2.Laplacian(bot_g, cv2.CV_64F).var()
    return sum([v_bg<55, dv>20, top_tex>100 and bot_tex>100]) >= 3

# ===== Build timeline =====
def build_timeline(bv_id):
    parts = []
    for f in sorted(os.listdir(VIDEO_DIR)):
        if bv_id not in f or not f.endswith(".info.json") or "NA_" in f: continue
        with open(os.path.join(VIDEO_DIR,f),"r",encoding="utf-8") as fh:
            d = json.load(fh)
        m = re.search(r"[?&]p=(\d+)", d.get("webpage_url",""))
        parts.append({"p":int(m.group(1)) if m else 0, "duration":int(d.get("duration",0) or 0),
                      "title":d.get("title","")})
    parts.sort(key=lambda x: x["p"])
    cum=0
    for pt in parts: pt["cumulative_start"]=cum; cum+=pt["duration"]
    base = re.sub(r"\s+p\d+\s+.*$","",parts[0]["title"]) if parts else bv_id
    base = re.sub(r"\s+p\d+$","",base)
    return parts, base

def global_to_part(parts, gts):
    for pt in parts:
        end=pt["cumulative_start"]+pt["duration"]
        if pt["cumulative_start"]<=gts<end: return pt["p"], gts-pt["cumulative_start"]
    return 1, gts

# ===== Process one video =====
def process_video(bv_id):
    print(f"\n{'='*50}\n{bv_id}\n{'='*50}")
    frame_dir = os.path.join(FRAME_DIR, bv_id)
    frames_all = sorted([f for f in os.listdir(frame_dir) if f.endswith(".jpg")])
    print(f"Frames: {len(frames_all)}")

    # Frame index
    ts_map = {}
    idx_path = os.path.join(frame_dir, "frames_index.csv")
    if os.path.exists(idx_path):
        with open(idx_path,"r") as f:
            for row in csv.DictReader(f): ts_map[row["frame_file"]] = int(row["timestamp_sec"])

    # Coarse filter
    candidates = []
    for i, fname in enumerate(frames_all):
        img = cv2.imread(os.path.join(frame_dir, fname))
        if img is None: continue
        if coarse_filter_frame(img):
            candidates.append({"fname": fname, "ts": ts_map.get(fname, i*2)})
    print(f"Coarse: {len(candidates)}/{len(frames_all)}")

    # CLIP match
    naafiri_frames = []
    for ci, cand in enumerate(candidates):
        img = cv2.imread(os.path.join(frame_dir, cand["fname"]))
        if img is None: continue
        top_crop = img[TOP["y"]:TOP["y"]+TOP["h"], TOP["x"]:TOP["x"]+TOP["w"]]
        bot_crop = img[BOT["y"]:BOT["y"]+BOT["h"], BOT["x"]:BOT["x"]+BOT["w"]]

        top_emb = encode_crop(top_crop); bot_emb = encode_crop(bot_crop)
        top_sims = (top_emb @ ref_embs.T).squeeze(0).cpu().numpy()
        bot_sims = (bot_emb @ ref_embs.T).squeeze(0).cpu().numpy()
        top_idx = np.argsort(top_sims)[::-1]; bot_idx = np.argsort(bot_sims)[::-1]

        top_hero = ref_champs[top_idx[0]]; top_sim = float(top_sims[top_idx[0]]); top_gap = float(top_sims[top_idx[0]]-top_sims[top_idx[1]])
        bot_hero = ref_champs[bot_idx[0]]; bot_sim = float(bot_sims[bot_idx[0]]); bot_gap = float(bot_sims[bot_idx[0]]-bot_sims[bot_idx[1]])

        # Top-3 for both sides
        top_top3 = [(ref_champs[top_idx[j]], float(top_sims[top_idx[j]]), ref_skins_list[top_idx[j]]) for j in range(3)]
        bot_top3 = [(ref_champs[bot_idx[j]], float(bot_sims[bot_idx[j]]), ref_skins_list[bot_idx[j]]) for j in range(3)]

        side = None; opp_hero = None; n_sim = 0; n_gap = 0
        if top_hero == TARGET and top_sim >= 0.76 and top_gap >= 0.03:
            side = "上方"; opp_hero = bot_hero; n_sim = top_sim; n_gap = top_gap
        elif bot_hero == TARGET and bot_sim >= 0.76 and bot_gap >= 0.03:
            side = "下方"; opp_hero = top_hero; n_sim = bot_sim; n_gap = bot_gap

        if side:
            naafiri_frames.append({
                "ts": cand["ts"], "fname": cand["fname"],
                "side": side, "opponent": opp_hero,
                "naafiri_sim": n_sim, "naafiri_gap": n_gap,
                "top_hero": top_hero, "top_sim": top_sim, "top_gap": top_gap,
                "bot_hero": bot_hero, "bot_sim": bot_sim, "bot_gap": bot_gap,
                "top_top3": top_top3, "bot_top3": bot_top3,
            })

        if (ci+1) % 100 == 0:
            print(f"  CLIP: {ci+1}/{len(candidates)} | {len(naafiri_frames)} Naafiri")

    print(f"Naafiri frames: {len(naafiri_frames)}")

    # Merge (5-min window + voting)
    naafiri_frames.sort(key=lambda x: x["ts"])
    groups = []
    if naafiri_frames:
        cur = [naafiri_frames[0]]
        for f in naafiri_frames[1:]:
            if f["ts"] - cur[-1]["ts"] <= MERGE_WINDOW: cur.append(f)
            else: groups.append(cur); cur = [f]
        groups.append(cur)

    merged = []
    for grp in groups:
        votes = defaultdict(lambda: {"cnt":0,"sims":[],"frames":[]})
        for f in grp:
            v = votes[f["opponent"]]; v["cnt"]+=1; v["sims"].append(f["naafiri_sim"]); v["frames"].append(f)
        # Pick best opponent by count, tiebreak by avg sim
        best_opp = max(votes.items(), key=lambda x: (x[1]["cnt"], np.mean(x[1]["sims"])))
        best_frame = max(best_opp[1]["frames"], key=lambda f: f["naafiri_sim"])
        best_frame["opponent"] = best_opp[0]
        best_frame["group_size"] = len(grp)
        best_frame["vote_details"] = {k: v["cnt"] for k, v in sorted(votes.items(), key=lambda x: -x[1]["cnt"])}
        merged.append(best_frame)

    print(f"Games: {len(merged)}")

    # Confidence
    for g in merged:
        ns, ng = g["naafiri_sim"], g["naafiri_gap"]
        if ns >= 0.82 and ng >= 0.06: g["conf"] = "高"
        elif ns >= 0.78 and ng >= 0.04: g["conf"] = "中"
        else: g["conf"] = "低"

    return merged, ts_map

# ===== Export Excel =====
def export_excel(bv_id, merged):
    xlsx_path = f"{OUT_DIR}/naafiri_mid_index_{bv_id}_final_v2.xlsx"
    wb = xlsxwriter.Workbook(xlsx_path, {"nan_inf_to_errors": True})

    hdr_f = wb.add_format({"bold":True,"bg_color":"#2F5496","font_color":"white","border":1,"align":"center","valign":"vcenter","font_size":10})
    cell = wb.add_format({"border":1,"align":"center","valign":"vcenter","font_size":9})
    cell_l = wb.add_format({"border":1,"align":"left","valign":"vcenter","font_size":9,"text_wrap":True})
    link_f = wb.add_format({"border":1,"align":"center","valign":"vcenter","font_size":9,"font_color":"blue","underline":1})
    hi_f = wb.add_format({"border":1,"align":"center","valign":"vcenter","font_size":9,"font_color":"green","bold":True})
    med_f = wb.add_format({"border":1,"align":"center","valign":"vcenter","font_size":9,"font_color":"#CC8400"})
    lo_f = wb.add_format({"border":1,"align":"center","valign":"vcenter","font_size":9,"font_color":"red"})

    headers = [
        "序号","视频标题","BV号","跳转链接","对局时间(分P内)","分P",
        "Naafiri队伍","对位英雄","置信度","Naafiri_Sim","Gap","帧数",
        "对位Top3候选","截图","备注"
    ]
    col_w = [4,38,16,48,12,4,6,16,8,9,8,5,35,20,22]

    ws = wb.add_worksheet("Naafiri中单索引")
    for c,h in enumerate(headers): ws.write(0,c,h,hdr_f)
    ws.freeze_panes(1,0); ws.autofilter(0,0,len(merged),len(headers)-1)
    for c,w in enumerate(col_w): ws.set_column(c,c,w)

    parts, base_title = build_timeline(bv_id)
    frame_dir = os.path.join(FRAME_DIR, bv_id)

    for i, g in enumerate(merged):
        r = i+1
        pn, pts = global_to_part(parts, g["ts"])
        t_str = f"{pts//3600:02d}:{(pts%3600)//60:02d}:{pts%60:02d}"
        jump = f"https://www.bilibili.com/video/{bv_id}/?p={pn}&t={pts}"

        # Top-3 opponent candidates (from the OTHER side)
        opp_side = "bot_top3" if g["side"] == "上方" else "top_top3"
        top3_str = "; ".join([f"{x[0]}({x[1]:.3f})" for x in g.get(opp_side, [])])

        ws.write(r,0,i+1,cell)
        ws.write(r,1,f"{base_title} [p{pn:02d}]",cell_l)
        ws.write(r,2,bv_id,cell)
        ws.write_url(r,3,jump,link_f,string=jump)
        ws.write(r,4,t_str,cell)
        ws.write(r,5,pn,cell)
        ws.write(r,6,g["side"],cell)
        opp_display = f'{g["opponent"]} / {cn_map.get(g["opponent"],g["opponent"])}'
        ws.write(r,7,opp_display,cell)
        cf = hi_f if g["conf"]=="高" else (med_f if g["conf"]=="中" else lo_f)
        ws.write(r,8,g["conf"],cf)
        ws.write(r,9,round(g["naafiri_sim"],4),cell)
        ws.write(r,10,round(g["naafiri_gap"],4),cell)
        ws.write(r,11,g.get("group_size",1),cell)
        ws.write(r,12,top3_str,cell_l)

        # Screenshot
        ss_dir = f"data/screenshots/{bv_id}"; os.makedirs(ss_dir, exist_ok=True)
        fpath = os.path.join(frame_dir, g["fname"])
        ss_path = os.path.join(ss_dir, f"match_{g['ts']}_Naafiri_vs_{g['opponent']}.jpg")
        if not os.path.exists(ss_path) and os.path.exists(fpath):
            shutil.copy2(fpath, ss_path)
        if os.path.exists(ss_path):
            ws.set_row(r,140)
            ws.insert_image(r,13,ss_path,{"x_scale":0.22,"y_scale":0.22})

        note = ""
        if g["conf"] == "低": note = "低置信度，建议查看截图复核"
        votes = g.get("vote_details",{})
        if len(votes) > 1:
            note += f" | 投票: {votes}"
        ws.write(r,14,note,cell_l)

    wb.close()
    return xlsx_path

# ===== MAIN =====
all_results = {}

# Accept BV argument(s) from command line, or use default list
import sys
if len(sys.argv) > 1:
    targets = sys.argv[1:]
else:
    targets = targets

for bv_id in targets:
    merged, ts_map = process_video(bv_id)
    xlsx = export_excel(bv_id, merged)
    all_results[bv_id] = {"merged": merged, "xlsx": xlsx}
    low = sum(1 for g in merged if g["conf"]=="低")
    print(f"Excel: {xlsx}")
    print(f"Summary: {len(merged)} games, {low} low confidence")
    for i, g in enumerate(merged):
        pn, pts = global_to_part(build_timeline(bv_id)[0], g["ts"])
        print(f"  [{i+1}] P{pn} {pts//3600:02d}:{(pts%3600)//60:02d}:{pts%60:02d} | {g['side']} | vs {g['opponent']} | {g['conf']} | sim={g['naafiri_sim']:.4f}")

# ===== Only run multi-video summary when batch processing =====
if len(targets) <= 1:
    print("Done!")
    import sys; sys.exit(0)

print(f"\n{'='*60}\nVALIDATION SUMMARY\n{'='*60}")
summary_path = f"{OUT_DIR}/final_validation_summary.xlsx"
wb2 = xlsxwriter.Workbook(summary_path, {"nan_inf_to_errors": True})

# Sheet 1: Overview
ws1 = wb2.add_worksheet("Overview")
fmt = {
    "hdr": wb2.add_format({"bold":True,"bg_color":"#2F5496","font_color":"white","border":1,"align":"center","valign":"vcenter","font_size":11}),
    "c": wb2.add_format({"border":1,"align":"center","valign":"vcenter","font_size":10}),
}
fields = ["BV号","对局数","低置信度","中置信度","高置信度","Top3候选支持率","需人工复核","Excel路径"]
for c,h in enumerate(fields): ws1.write(0,c,h,fmt["hdr"])
ws1.set_column(0,0,16); ws1.set_column(1,5,10); ws1.set_column(6,6,12); ws1.set_column(7,7,55)

total_games = 0
for i, bv_id in enumerate(targets):
    merged = all_results[bv_id]["merged"]
    low = sum(1 for g in merged if g["conf"]=="低")
    med = sum(1 for g in merged if g["conf"]=="中")
    hi = sum(1 for g in merged if g["conf"]=="高")
    review_items = []
    for g in merged:
        if g["conf"] == "低": review_items.append(f"低置信度: {g['opponent']}")
        votes = g.get("vote_details",{})
        if len(votes) > 1: review_items.append(f"投票分歧: {votes}")
    total_games += len(merged)
    ws1.write(i+1,0,bv_id,fmt["c"])
    ws1.write(i+1,1,len(merged),fmt["c"]); ws1.write(i+1,2,low,fmt["c"])
    ws1.write(i+1,3,med,fmt["c"]); ws1.write(i+1,4,hi,fmt["c"])
    ws1.write(i+1,5,"Yes" if any(len(g.get("vote_details",{}))>1 for g in merged) else "N/A",fmt["c"])
    ws1.write(i+1,6,"; ".join(review_items) if review_items else "无",fmt["c"])
    ws1.write(i+1,7,all_results[bv_id]["xlsx"],fmt["c"])

ws1.write(len(targets)+2,0,"合计",fmt["hdr"]); ws1.write(len(targets)+2,1,total_games,fmt["hdr"])

# Sheet 2: Per-game detail
ws2 = wb2.add_worksheet("All Games Detail")
df = ["BV号","分P","分P内时间","全局时间","Naafiri队伍","对位英雄","置信度","Naafiri_Sim","Gap","帧数","对位Top1","对位Top2","对位Top3","投票"]
for c,h in enumerate(df): ws2.write(0,c,h,fmt["hdr"])
ws2.set_column(0,0,16); ws2.set_column(1,1,4); ws2.set_column(2,2,10); ws2.set_column(3,3,8)
ws2.set_column(4,4,6); ws2.set_column(5,5,14); ws2.set_column(6,13,10)
row = 1
for bv_id in targets:
    merged = all_results[bv_id]["merged"]
    parts, _ = build_timeline(bv_id)
    for g in merged:
        pn, pts = global_to_part(parts, g["ts"])
        opp_side = "bot_top3" if g["side"]=="上方" else "top_top3"
        top3 = g.get(opp_side, [])
        ws2.write(row,0,bv_id,fmt["c"]); ws2.write(row,1,pn,fmt["c"])
        ws2.write(row,2,f"{pts//3600:02d}:{(pts%3600)//60:02d}:{pts%60:02d}",fmt["c"])
        ws2.write(row,3,g["ts"],fmt["c"]); ws2.write(row,4,g["side"],fmt["c"])
        ws2.write(row,5,f'{g["opponent"]} / {cn_map.get(g["opponent"],g["opponent"])}',fmt["c"])
        ws2.write(row,6,g["conf"],fmt["c"])
        ws2.write(row,7,round(g["naafiri_sim"],4),fmt["c"]); ws2.write(row,8,round(g["naafiri_gap"],4),fmt["c"])
        ws2.write(row,9,g.get("group_size",1),fmt["c"])
        for j in range(3):
            ws2.write(row,10+j,f'{top3[j][0]}({top3[j][1]:.3f})' if j<len(top3) else "",fmt["c"])
        ws2.write(row,13,str(g.get("vote_details",{})),fmt["c"])
        row += 1

wb2.close()
print(f"Summary: {summary_path}")
print(f"\nTotal: {total_games} games across 3 videos")
print(f"Model: OpenCLIP ViT-L/14 | Assets: v2 ({len(ref_paths)} images)")
print("Done!")
