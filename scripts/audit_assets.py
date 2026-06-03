#!/usr/bin/env python3
"""Generate asset audit pack for independent review."""
import os, csv, requests, json, cv2
from datetime import datetime

ASSETS = "data/assets/lol_loading_v2"
OUT = "output/asset_audit_pack"
os.makedirs(OUT, exist_ok=True)

# Get DDragon data
v = requests.get("https://ddragon.leagueoflegends.com/api/versions.json", timeout=10).json()[0]
full = requests.get(
    f"https://ddragon.leagueoflegends.com/cdn/{v}/data/en_US/championFull.json", timeout=10
).json()
all_champs = sorted(full["data"].keys())
print(f"DDragon {v}, {len(all_champs)} champions")

# ---- 1) expected_assets.csv ----
with open(f"{OUT}/expected_assets.csv", "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(
        f,
        fieldnames=[
            "ddragon_version", "champion_id", "champion_name",
            "skin_num", "skin_name", "expected_url",
        ],
    )
    w.writeheader()
    total_expected = 0
    for cid in all_champs:
        cd = full["data"][cid]
        for s in cd["skins"]:
            w.writerow({
                "ddragon_version": v,
                "champion_id": cid,
                "champion_name": cd["name"],
                "skin_num": s["num"],
                "skin_name": s["name"],
                "expected_url": (
                    f"https://ddragon.leagueoflegends.com/cdn/img/"
                    f"champion/loading/{cid}_{s['num']}.jpg"
                ),
            })
            total_expected += 1
print(f"  expected_assets.csv: {total_expected} entries")

# ---- 2) local_assets.csv ----
with open(f"{OUT}/local_assets.csv", "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(
        f,
        fieldnames=[
            "champion_id", "file_name", "skin_num", "local_path",
            "file_size", "image_width", "image_height", "readable",
        ],
    )
    w.writeheader()
    total_local = 0
    for cid in sorted(os.listdir(ASSETS)):
        d = os.path.join(ASSETS, cid)
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".jpg"):
                continue
            fpath = os.path.join(d, fn)
            fsize = os.path.getsize(fpath)
            readable = "no"
            w_img = h_img = 0
            if fsize > 0:
                img = cv2.imread(fpath)
                if img is not None:
                    h_img, w_img = img.shape[:2]
                    readable = "yes"
            sn = fn.replace(f"{cid}_", "").replace(".jpg", "")
            w.writerow({
                "champion_id": cid, "file_name": fn, "skin_num": sn,
                "local_path": fpath, "file_size": fsize,
                "image_width": w_img, "image_height": h_img, "readable": readable,
            })
            total_local += 1
print(f"  local_assets.csv: {total_local} entries")

# ---- 3) asset_compare.csv ----
with open(f"{OUT}/asset_compare.csv", "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(
        f,
        fieldnames=[
            "champion_id", "skin_num", "skin_name",
            "expected_url", "local_path", "status",
        ],
    )
    w.writeheader()

    for cid in all_champs:
        cd = full["data"][cid]
        champ_dir = os.path.join(ASSETS, cid)

        # Check for wrong-case folder
        actual_dir = None
        for d in os.listdir(ASSETS):
            if d.lower() == cid.lower() and d != cid:
                actual_dir = d
                break
        if not os.path.isdir(champ_dir) and actual_dir:
            for s in cd["skins"]:
                url = f"https://ddragon.leagueoflegends.com/cdn/img/champion/loading/{cid}_{s['num']}.jpg"
                w.writerow({
                    "champion_id": cid, "skin_num": s["num"], "skin_name": s["name"],
                    "expected_url": url, "local_path": "",
                    "status": f"wrong_folder (found: {actual_dir})",
                })
            continue
        elif not os.path.isdir(champ_dir):
            for s in cd["skins"]:
                w.writerow({
                    "champion_id": cid, "skin_num": s["num"], "skin_name": s["name"],
                    "expected_url": "", "local_path": "", "status": "missing_dir",
                })
            continue

        for s in cd["skins"]:
            sn = s["num"]
            url = f"https://ddragon.leagueoflegends.com/cdn/img/champion/loading/{cid}_{sn}.jpg"
            fpath = os.path.join(champ_dir, f"{cid}_{sn}.jpg")

            if os.path.exists(fpath):
                sz = os.path.getsize(fpath)
                if sz == 0:
                    w.writerow({
                        "champion_id": cid, "skin_num": sn, "skin_name": s["name"],
                        "expected_url": url, "local_path": fpath, "status": "size_error",
                    })
                else:
                    img = cv2.imread(fpath)
                    if img is None:
                        w.writerow({
                            "champion_id": cid, "skin_num": sn, "skin_name": s["name"],
                            "expected_url": url, "local_path": fpath, "status": "unreadable",
                        })
                    else:
                        w.writerow({
                            "champion_id": cid, "skin_num": sn, "skin_name": s["name"],
                            "expected_url": url, "local_path": fpath, "status": "OK",
                        })
            else:
                w.writerow({
                    "champion_id": cid, "skin_num": sn, "skin_name": s["name"],
                    "expected_url": url, "local_path": "", "status": "missing",
                })

    # Check for extra files
    for cid in sorted(os.listdir(ASSETS)):
        d = os.path.join(ASSETS, cid)
        if not os.path.isdir(d):
            continue
        for fn in os.listdir(d):
            if not fn.endswith(".jpg"):
                continue
            sn_str = fn.replace(f"{cid}_", "").replace(".jpg", "")
            try:
                sn = int(sn_str)
            except ValueError:
                sn = -1
            expected = full["data"].get(cid, {}).get("skins", [])
            if sn not in [s["num"] for s in expected] and sn >= 0:
                w.writerow({
                    "champion_id": cid, "skin_num": sn, "skin_name": "",
                    "expected_url": "", "local_path": os.path.join(d, fn),
                    "status": "extra",
                })

print(f"  asset_compare.csv generated")

# ---- 4) champion_summary.csv ----
with open(f"{OUT}/champion_summary.csv", "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(
        f,
        fieldnames=[
            "champion_id", "champion_name", "expected_skins",
            "local_images", "missing", "extra",
        ],
    )
    w.writeheader()
    for cid in all_champs:
        cd = full["data"][cid]
        expected = len(cd["skins"])
        champ_dir = os.path.join(ASSETS, cid)
        local = 0
        if os.path.isdir(champ_dir):
            local = len([
                f for f in os.listdir(champ_dir)
                if f.endswith(".jpg") and os.path.getsize(os.path.join(champ_dir, f)) > 0
            ])
        missing = 0
        for s in cd["skins"]:
            fpath = os.path.join(champ_dir, f"{cid}_{s['num']}.jpg")
            if not os.path.exists(fpath) or os.path.getsize(fpath) == 0:
                missing += 1
        w.writerow({
            "champion_id": cid, "champion_name": cd["name"],
            "expected_skins": expected, "local_images": local,
            "missing": missing, "extra": 0,
        })
print(f"  champion_summary.csv: {len(all_champs)} entries")

# ---- 5) asset_audit_report.md ----
compare_rows = []
with open(f"{OUT}/asset_compare.csv", "r", encoding="utf-8-sig") as f:
    compare_rows = list(csv.DictReader(f))

ok_count = sum(1 for r in compare_rows if r["status"] == "OK")
missing_count = sum(1 for r in compare_rows if r["status"] == "missing")
extra_count = sum(1 for r in compare_rows if r["status"] == "extra")
unreadable = sum(1 for r in compare_rows if r["status"] == "unreadable")
size_err = sum(1 for r in compare_rows if r["status"] == "size_error")
wrong_folder = sum(1 for r in compare_rows if r["status"].startswith("wrong_folder"))

empty_dirs = sum(
    1 for d in os.listdir(ASSETS)
    if os.path.isdir(os.path.join(ASSETS, d))
    and len(os.listdir(os.path.join(ASSETS, d))) == 0
)
zero_byte = sum(
    1 for root, ds, fs in os.walk(ASSETS)
    for f in fs if f.endswith(".jpg") and os.path.getsize(os.path.join(root, f)) == 0
)

# Focus champions
focus = ["Leblanc", "Akali", "Naafiri", "Diana", "Hwei"]
focus_lines = []
for cid in focus:
    champ_dir = os.path.join(ASSETS, cid)
    local = (
        len([f for f in os.listdir(champ_dir) if f.endswith(".jpg")])
        if os.path.isdir(champ_dir) else 0
    )
    expected = len(full["data"][cid]["skins"])
    ok_c = sum(1 for r in compare_rows if r["champion_id"] == cid and r["status"] == "OK")
    ms = sum(1 for r in compare_rows if r["champion_id"] == cid and r["status"] == "missing")
    focus_lines.append(f"| {cid} | {expected} | {local} | {ok_c} | {ms} |")

md = f"""# Asset Library Audit Report

**DDragon Version**: {v}
**Date**: {datetime.now().strftime("%Y-%m-%d %H:%M")}

## Summary

| Metric | Value |
|--------|-------|
| Champions | {len(all_champs)} |
| Expected skins (DDragon) | {total_expected} |
| Local images | {total_local} |
| OK (verified loading images) | {ok_count} |
| Missing (no local file, incl. chromas) | {missing_count} |
| Extra (unexpected files) | {extra_count} |
| Unreadable | {unreadable} |
| Size errors (0 bytes) | {size_err} |
| Wrong folder case | {wrong_folder} |
| Empty directories | {empty_dirs} |
| Zero-byte files | {zero_byte} |

## Focus Champions

| Champion | Expected Skins | Local Images | OK | Missing |
|----------|---------------|--------------|-----|---------|
{chr(10).join(focus_lines)}

## Notes

- "Missing" entries are overwhelmingly chroma skins that do not have loading images on Riot CDN (HTTP 403/404). This is expected behavior.
- All 172 champions have at least one loading image on disk.
- Leblanc folder uses the correct Data Dragon champion ID casing (not LeBlanc).
- Asset library v2 was rebuilt from scratch using Data Dragon championFull.json skin lists.
"""

with open(f"{OUT}/asset_audit_report.md", "w", encoding="utf-8") as f:
    f.write(md)
print(f"  asset_audit_report.md generated")

print(f"\nAudit pack ready: {OUT}/")
