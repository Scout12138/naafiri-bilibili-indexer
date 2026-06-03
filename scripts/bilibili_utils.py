#!/usr/bin/env python3
"""B站 API helpers: video discovery, cookies verification, download."""
import json, os, re, sys, time, hashlib, urllib.parse, subprocess
import requests


# ─── Netscape cookies parser ────────────────────────────────────────────
def parse_netscape_cookies(path):
    """Parse Netscape-format cookies.txt into a dict."""
    if not os.path.isfile(path):
        raise FileNotFoundError(f"cookies file not found: {path}")
    cookies = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line.startswith("#HttpOnly_"):
                line = line[len("#HttpOnly_"):]
            if line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) >= 7:
                cookies[parts[5]] = parts[6]
    return cookies


# ─── Login verification ─────────────────────────────────────────────────
def verify_bilibili_login(cookies_path):
    """Verify B站 cookies are valid. Returns (ok, uname, message)."""
    print("\n--- Verifying B站 login ---")
    try:
        cookies = parse_netscape_cookies(cookies_path)
        print(f"  Parsed {len(cookies)} cookies")
    except FileNotFoundError as e:
        return False, "", str(e)

    try:
        resp = requests.get(
            "https://api.bilibili.com/x/web-interface/nav",
            cookies=cookies,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": "https://www.bilibili.com/",
            },
            timeout=15,
        )
        data = resp.json()
        is_login = data.get("data", {}).get("isLogin", False)
        uname = data.get("data", {}).get("uname", "?")
        code = data.get("code", -1)

        if is_login:
            print(f"  ✓ Logged in as: {uname}")
            return True, uname, ""
        else:
            msg = f"Not logged in (code={code}). Cookies may be expired."
            print(f"  ✗ {msg}")
            return False, "", msg
    except Exception as e:
        msg = f"Login check failed: {e}"
        print(f"  ✗ {msg}")
        return False, "", msg


# ─── 720p format check ──────────────────────────────────────────────────
def check_720p_available(cookies_path, bv_id):
    """Verify a BV has 720p format via yt-dlp. Returns (ok, message)."""
    print(f"\n--- Checking 720p for {bv_id} ---")
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "--cookies", cookies_path,
        "-F", f"https://www.bilibili.com/video/{bv_id}",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=60)
        output = result.stdout + result.stderr
        has_720p = "1280x720" in output
        if has_720p:
            print(f"  ✓ 720p format confirmed")
            return True, ""
        else:
            msg = f"No 720p format found for {bv_id}. Check if video supports 720p."
            print(f"  ✗ {msg}")
            return False, msg
    except Exception as e:
        return False, f"yt-dlp -F failed: {e}"


# ─── Video discovery ────────────────────────────────────────────────────
def _get_wbi_keys():
    """Get wbi signing keys from B站 nav API."""
    resp = requests.get(
        "https://api.bilibili.com/x/web-interface/nav",
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
        timeout=10,
    )
    data = resp.json().get("data", {})
    img = data.get("wbi_img", {}).get("img_url", "")
    sub = data.get("wbi_img", {}).get("sub_url", "")
    if not img or not sub:
        raise RuntimeError("Failed to get wbi keys from nav API")
    return img.split("/")[-1].split(".")[0], sub.split("/")[-1].split(".")[0]


def _mixin_key(raw):
    """Build mixin key table."""
    table = []
    for c in raw[:32]:
        o = ord(c)
        if 48 <= o <= 57: table.append(c)
        elif 97 <= o <= 122: table.append(chr(o - 32))
        elif 65 <= o <= 90:
            idx = o - 65
            table.append(table[idx] if idx < len(table) else c)
    return table


def _wbi_sign(params, img_key, sub_key):
    mk = _mixin_key(img_key + sub_key)
    qs = urllib.parse.urlencode(sorted(params.items()))
    return hashlib.md5((qs + "".join(mk)).encode()).hexdigest()


def get_video_info(bv_id):
    """Get single video info via wbi-signed API."""
    img_key, sub_key = _get_wbi_keys()
    params = {"bvid": bv_id}
    params["wts"] = int(time.time())
    params["w_rid"] = _wbi_sign(params, img_key, sub_key)
    resp = requests.get(
        "https://api.bilibili.com/x/web-interface/view",
        params=params,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://www.bilibili.com/",
        },
        timeout=15,
    )
    if resp.status_code != 200:
        return None
    return resp.json().get("data") or {}


def fetch_latest_videos(mid, count=30, cookies_path=None):
    """Fetch latest video BVs from a UP主's space using yt-dlp flat playlist."""
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "--flat-playlist",
        "--print", "%(id)s",
        f"https://space.bilibili.com/{mid}/video",
    ]
    if cookies_path and os.path.isfile(cookies_path):
        cmd.insert(3, "--cookies")
        cmd.insert(4, cookies_path)

    try:
        result = subprocess.run(cmd, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=60)
        # Check for yt-dlp errors on stderr
        stderr = (result.stderr or "").strip()
        if stderr and "ERROR:" in stderr:
            print(f"[WARN] yt-dlp space listing error: {stderr[:200]}")
        bvs = [line.strip() for line in (result.stdout or "").splitlines() if line.strip().startswith("BV")]
        return bvs[:count]
    except Exception as e:
        print(f"[WARN] yt-dlp space listing failed: {e}")
        return []


def filter_long_recordings(bv_ids, config):
    """Filter BVs: keep only long gameplay recordings (not clips/highlights)."""
    min_sec = config.get("filter", {}).get("min_duration_min", 10) * 60
    exclude_kw = config.get("filter", {}).get("exclude_keywords", [])

    results = []
    for bv in bv_ids:
        info = get_video_info(bv)
        if not info:
            continue
        dur = info.get("duration", 0)
        title = info.get("title", "")
        parts = info.get("videos", 1)
        pubdate = info.get("pubdate", 0)

        # Apply filters
        if dur < min_sec and parts <= 1:
            continue
        if any(kw.lower() in title.lower() for kw in exclude_kw):
            continue

        results.append({
            "bv_id": bv,
            "title": title,
            "duration_sec": dur,
            "parts": parts,
            "pubdate": pubdate,
            "pubdate_str": time.strftime("%Y-%m-%d %H:%M", time.localtime(pubdate)) if pubdate else "?",
        })

    return results


# ─── Download ────────────────────────────────────────────────────────────
def download_video(cookies_path, bv_id, config):
    """Download all parts of a BV in 720p. Returns (ok, downloaded_files, message)."""
    print(f"\n--- Downloading {bv_id} (720p) ---")
    fmt = config.get("download", {}).get("format", "30064+30280")
    video_dir = config.get("paths", {}).get("video_dir", "data/videos")
    os.makedirs(video_dir, exist_ok=True)

    output_tmpl = os.path.join(video_dir, "%(upload_date>%Y%m%d)s_%(id)s_p%(playlist_index)s.%(ext)s")

    cmd = [
        sys.executable, "-m", "yt_dlp",
        "--cookies", cookies_path,
        "-f", fmt,
        "-o", output_tmpl,
        "--write-info-json",
        # Don't use --no-playlist: B站 anthology videos need playlist mode for all parts
        f"https://www.bilibili.com/video/{bv_id}",
    ]

    print(f"  Format: {fmt}")
    print(f"  Output: {output_tmpl}")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=7200)
        output = result.stdout + result.stderr

        # Check for download errors
        if result.returncode != 0:
            # Extract meaningful error
            for line in output.splitlines():
                if "ERROR" in line or "error" in line:
                    return False, [], f"Download failed: {line.strip()[:200]}"
            return False, [], f"yt-dlp exited with code {result.returncode}"

        # Verify files exist
        downloaded = sorted([
            f for f in os.listdir(video_dir)
            if bv_id in f and f.endswith(".mp4")
        ])
        if not downloaded:
            return False, [], "No mp4 files found after download"

        # Verify resolution of first downloaded file
        import cv2
        first_mp4 = os.path.join(video_dir, downloaded[0])
        cap = cv2.VideoCapture(first_mp4)
        w = int(cap.get(3))
        h = int(cap.get(4))
        cap.release()

        target = config.get("download", {}).get("target_resolution", "1280x720")
        if f"{w}x{h}" != target:
            return False, [], f"Resolution mismatch: expected {target}, got {w}x{h}"

        print(f"  ✓ Downloaded {len(downloaded)} part(s), resolution {w}x{h}")
        return True, downloaded, ""

    except subprocess.TimeoutExpired:
        return False, [], "Download timed out (>2h)"
    except Exception as e:
        return False, [], f"Download error: {e}"
