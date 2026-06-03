#!/usr/bin/env python3
"""
04_download_lol_loading_assets.py — 下载 Riot Data Dragon 全英雄全皮肤 loading 图
输出: data/assets/lol_loading/{ChampionName}/{ChampionName}_{skinNum}.jpg
      data/assets/champion_map.csv
"""
import requests
import json
import csv
import os
import sys
import time
import logging
from datetime import datetime
from pathlib import Path

# === CONFIG ===
ASSETS_DIR = "data/assets/lol_loading"
MAP_CSV = "data/assets/champion_map.csv"
LOG_FILE = "logs/download_assets.log"
REQUEST_DELAY = 0  # 移除延迟，加快下载速度

# Naafiri champion ID (in Data Dragon): 950
NAAFIRI_ID = "950"

os.makedirs(ASSETS_DIR, exist_ok=True)
os.makedirs("logs", exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8"), logging.StreamHandler()],
)
log = logging.getLogger(__name__)


def get_latest_version():
    """获取最新 Data Dragon 版本号"""
    url = "https://ddragon.leagueoflegends.com/api/versions.json"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    versions = resp.json()
    return versions[0]


def get_champion_list(version):
    """获取全英雄列表（英文名 + 中文名 + ID，不含 skins）"""
    url = f"https://ddragon.leagueoflegends.com/cdn/{version}/data/en_US/champion.json"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    champions = []
    for champ_id, champ_data in data["data"].items():
        champions.append({
            "id": champ_id,
            "key": champ_data["key"],  # numeric key
            "name_en": champ_data["name"],
            "name_cn": "",  # Will fill from zh_CN data
            "skins": [],  # Will fill from individual champion JSON
        })
    return champions


def fetch_champion_skins(version, champion):
    """获取单个英雄的皮肤列表"""
    url = f"https://ddragon.leagueoflegends.com/cdn/{version}/data/en_US/champion/{champion['id']}.json"
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        skins = data.get("data", {}).get(champion["id"], {}).get("skins", [])
        return [s["num"] for s in skins]
    except Exception as e:
        log.warning(f"  Failed to get skins for {champion['name_en']}: {e}")
        return [0]  # At minimum, base skin


def get_champion_cn_names(version, champions):
    """获取中文英雄名"""
    url = f"https://ddragon.leagueoflegends.com/cdn/{version}/data/zh_CN/champion.json"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    cn_map = {}
    for champ_id, champ_data in data["data"].items():
        cn_map[champ_id] = champ_data["name"]

    for c in champions:
        c["name_cn"] = cn_map.get(c["id"], c["name_en"])

    return champions


def download_loading_image(champion, skin_num, session=None):
    """下载单张 loading 图"""
    name = champion["name_en"]
    filename = f"{name}_{skin_num}.jpg"

    champ_dir = os.path.join(ASSETS_DIR, name)
    os.makedirs(champ_dir, exist_ok=True)

    filepath = os.path.join(champ_dir, filename)

    # Skip if already downloaded
    if os.path.exists(filepath) and os.path.getsize(filepath) > 1000:
        return filepath, True  # cached

    url = f"https://ddragon.leagueoflegends.com/cdn/img/champion/loading/{name}_{skin_num}.jpg"

    try:
        if session:
            resp = session.get(url, timeout=15)
        else:
            resp = requests.get(url, timeout=15)

        if resp.status_code == 200 and len(resp.content) > 1000:
            with open(filepath, "wb") as f:
                f.write(resp.content)
            return filepath, True
        else:
            return url, False
    except Exception as e:
        return str(e), False


def main():
    log.info("=" * 50)
    log.info(f"LOL Loading Asset Download started at {datetime.now()}")

    # Step 1: Get version
    log.info("\n[1] Getting latest Data Dragon version...")
    version = get_latest_version()
    log.info(f"  Latest version: {version}")

    # Save version
    with open("data/assets/ddragon_version.txt", "w") as f:
        f.write(version)

    # Step 2: Get champion list
    log.info("\n[2] Fetching champion list...")
    champions = get_champion_list(version)
    log.info(f"  Found {len(champions)} champions")

    # Step 3: Get Chinese names
    log.info("\n[3] Fetching Chinese champion names...")
    champions = get_champion_cn_names(version, champions)

    # Show Naafiri
    for c in champions:
        if c["id"] == "Naafiri":
            log.info(f"  Naafiri: {c['name_en']} / {c['name_cn']} / key={c['key']} (skins not yet fetched)")

    # Step 3.5: Fetch skins for each champion
    log.info("\n[3.5] Fetching skins for each champion...")
    for i, c in enumerate(champions):
        c["skins"] = fetch_champion_skins(version, c)
        if (i + 1) % 30 == 0:
            log.info(f"  Progress: {i+1}/{len(champions)} champions")
        time.sleep(0.15)

    # Show Naafiri skins
    for c in champions:
        if c["id"] == "Naafiri":
            log.info(f"  Naafiri skins: {c['skins']}")

    # Step 4: Download all loading images
    log.info("\n[4] Downloading loading images (stopping after 3 consecutive 404s per champion)...")
    session = requests.Session()
    total = sum(min(len(c["skins"]), 30) for c in champions)  # rough estimate
    done = 0
    errors = 0
    rows = []

    for c in champions:
        for skin_num in sorted(c["skins"]):
            filepath, ok = download_loading_image(c, skin_num, session=session)
            done += 1

            if ok:
                rows.append({
                    "image_path": f"{c['name_en']}/{c['name_en']}_{skin_num}.jpg",
                    "champion_en": c["name_en"],
                    "champion_cn": c["name_cn"],
                    "skin_num": skin_num,
                })
            else:
                errors += 1
                if errors <= 20:
                    log.warning(f"  Failed: {filepath}")

        if (len(rows) + 1) % 200 == 0:
            log.info(f"  Downloaded {len(rows)} images so far...")

    log.info(f"\n  Download complete: {len(rows)} images succeeded, {errors} failed (404s)")

    # Step 5: Write champion_map.csv
    log.info(f"\n[5] Writing {MAP_CSV}...")
    with open(MAP_CSV, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["image_path", "champion_en", "champion_cn", "skin_num"])
        writer.writeheader()
        writer.writerows(rows)

    log.info(f"  Saved {len(rows)} entries")

    # Step 6: Summary
    log.info(f"\n{'='*50}")
    log.info("✅ Asset download complete")
    log.info(f"  Version: {version}")
    log.info(f"  Champions: {len(champions)}")
    log.info(f"  Loading images: {len(rows)}")
    log.info(f"  Errors: {errors}")

    # Check Naafiri specifically
    naafiri_images = [r for r in rows if r["champion_en"] == "Naafiri"]
    log.info(f"  Naafiri loading images: {len(naafiri_images)}")
    for r in naafiri_images:
        log.info(f"    {r['image_path']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
