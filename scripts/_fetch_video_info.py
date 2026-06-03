#!/usr/bin/env python3
"""Fetch B站 video details using wbi-signed API (no cookies needed)."""
import requests, time, hashlib, urllib.parse

def get_wbi_keys():
    """Get wbi img and sub keys for signing."""
    resp = requests.get('https://api.bilibili.com/x/web-interface/nav',
                        headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})
    if resp.status_code != 200:
        raise RuntimeError(f"nav failed: {resp.status_code}")
    data = resp.json().get('data', {})
    img_url = data.get('wbi_img', {}).get('img_url', '')
    sub_url = data.get('wbi_img', {}).get('sub_url', '')
    if not img_url or not sub_url:
        raise RuntimeError(f"wbi keys missing from nav: {data}")
    img_key = img_url.split('/')[-1].split('.')[0]
    sub_key = sub_url.split('/')[-1].split('.')[0]
    return img_key, sub_key

def mixin_key(raw: str) -> list:
    """Build mixin key table from raw string."""
    table = []
    for c in raw[:32]:
        o = ord(c)
        if 48 <= o <= 57:
            table.append(c)
        elif 97 <= o <= 122:
            table.append(chr(o - 32))
        elif 65 <= o <= 90:
            idx = o - 65
            table.append(table[idx] if idx < len(table) else c)
    return table

def wbi_sign(params: dict, img_key: str, sub_key: str) -> str:
    """Generate wbi signature for params."""
    mk = mixin_key(img_key + sub_key)
    sorted_str = urllib.parse.urlencode(sorted(params.items()))
    return hashlib.md5((sorted_str + ''.join(mk)).encode()).hexdigest()

def get_video_info(bvid: str, img_key: str, sub_key: str) -> dict:
    """Get video info for a single BV."""
    params = {'bvid': bvid}
    params['wts'] = int(time.time())
    params['w_rid'] = wbi_sign(params, img_key, sub_key)

    resp = requests.get('https://api.bilibili.com/x/web-interface/view',
                        params=params,
                        headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                                 'Referer': 'https://www.bilibili.com/'})
    if resp.status_code != 200:
        print(f"[WARN] {bvid}: HTTP {resp.status_code}")
        return {}
    data = resp.json().get('data') or {}
    if not data:
        print(f"[WARN] {bvid}: no data in response: {resp.json().get('message', '?')}")
        return {}
    return data

def main():
    img_key, sub_key = get_wbi_keys()
    print(f"wbi keys: img={img_key[:8]}... sub={sub_key[:8]}...")

    # Latest BVs from the space listing (2026-06-03)
    bvids = [
        "BV1xKVC6NEw2",  # newest
        "BV12eVq6QEbA",  # already processed
        "BV1hgVQ6eEzh",  # processed 720p
        "BV1L1VJ6nE7n",  # processed 720p
        "BV1HsVL6EEGc",  # processed 720p
    ]

    for bv in bvids:
        info = get_video_info(bv, img_key, sub_key)
        if not info:
            continue

        dur = info.get('duration', 0)
        mins, secs = divmod(dur, 60)
        title = info.get('title', '')
        pubdate = time.strftime('%Y-%m-%d %H:%M', time.localtime(info.get('pubdate', 0)))
        parts = info.get('videos', 1)
        desc = (info.get('desc', '') or '')[:120].replace('\n', ' ')

        print(f"\n{bv} | {parts}P | {mins}m{secs:02d}s | {pubdate} | {title}")
        print(f"  Desc: {desc}")

    # Also search for unprocessed long videos from the flat list
    all_bvs = [
        "BV1xKVC6NEw2", "BV17qG16ZES7", "BV1sfVP6xEGq", "BV1EyVc6uEQr",
        "BV1CCGH6iEqJ", "BV1iDG76LEZd", "BV1cFG66UE2r", "BV1kVGq6GEhE",
        "BV1AqGb69EuQ", "BV1dbLv6PEbn",
    ]

    print("\n\n=== Scanning more recent BVs for long recordings ===")
    for bv in all_bvs[1:]:  # skip BV1xKVC6NEw2 (already checked)
        info = get_video_info(bv, img_key, sub_key)
        if not info:
            continue

        dur = info.get('duration', 0)
        mins, secs = divmod(dur, 60)
        title = info.get('title', '')
        pubdate = time.strftime('%Y-%m-%d %H:%M', time.localtime(info.get('pubdate', 0)))
        parts = info.get('videos', 1)

        # Filter: long recordings only (>= 10 min per part, or multiple parts)
        is_long = dur >= 600 or parts > 1
        marker = "<<< LONG" if is_long else ""
        print(f"{bv} | {parts}P | {mins}m{secs:02d}s | {pubdate} | {title[:80]} {marker}")

if __name__ == '__main__':
    main()
