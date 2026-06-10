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
        # Longer timeout for multi-part videos (each part requires a separate API call)
        result = subprocess.run(cmd, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=180)
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
    """Fetch latest video BVs from a UP主's space using mobile API (low-frequency, anti-412).

    Uses the mobile app API endpoint which does not require wbi signing.
    Paginates with 0.5s sleep between pages to avoid rate limiting.
    On 412, stops immediately and logs the page that triggered it.
    """
    cookies = {}
    if cookies_path and os.path.isfile(cookies_path):
        cookies = parse_netscape_cookies(cookies_path)

    headers = {
        "User-Agent": "Mozilla/5.0 BiliDroid/7.0.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X)",
        "Referer": "https://m.bilibili.com/",
    }

    bvs = []
    ps = min(count, 30)  # 30 per page max
    max_pages = (count + ps - 1) // ps

    for pn in range(1, max_pages + 1):
        try:
            resp = requests.get(
                "https://api.bilibili.com/x/space/arc/search",
                params={"mid": mid, "ps": ps, "pn": pn, "order": "pubdate"},
                cookies=cookies,
                headers=headers,
                timeout=30,
            )

            if resp.status_code == 412:
                print(f"[WARN] 412 风控 — 接口: space/arc/search, pn={pn}, "
                      f"返回: {resp.text[:200]}")
                break

            data = resp.json()
            if data.get("code") != 0:
                print(f"[WARN] API error: code={data.get('code')}, "
                      f"msg={data.get('message', '?')}, pn={pn}")
                break

            vlist = data.get("data", {}).get("list", {}).get("vlist", [])
            if not vlist:
                break

            for v in vlist:
                bvid = v.get("bvid", "")
                if bvid:
                    bvs.append(bvid)

            # Low frequency: sleep between pages
            if pn < max_pages:
                time.sleep(0.5)

        except Exception as e:
            print(f"[WARN] Space listing failed (pn={pn}): {e}")
            break

    return bvs[:count]


def fetch_and_filter_videos(mid, config, max_videos=200, cookies_path=None):
    """Fetch videos from UP主 space and filter by config in one pass.

    Uses mobile API which returns title+duration directly — avoids N+1
    get_video_info calls. Paginates with sleep between pages (anti-412).

    Returns list of candidate dicts matching title keyword + duration filters.
    """
    cookies = {}
    if cookies_path and os.path.isfile(cookies_path):
        cookies = parse_netscape_cookies(cookies_path)

    headers = {
        "User-Agent": "Mozilla/5.0 BiliDroid/7.0.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X)",
        "Referer": "https://m.bilibili.com/",
    }

    min_sec = config.get("filter", {}).get("min_duration_min", 10) * 60
    exclude_kw = config.get("filter", {}).get("exclude_keywords", [])
    title_kw = config.get("filter", {}).get("title_keyword", "")

    candidates = []
    ps = 30

    for pn in range(1, 999):  # paginate until empty or 412
        try:
            api_params = {"mid": mid, "ps": ps, "pn": pn, "order": "pubdate"}
            # Use server-side keyword filter when available (finds all matching videos)
            if title_kw:
                api_params["keyword"] = title_kw

            resp = requests.get(
                "https://api.bilibili.com/x/space/arc/search",
                params=api_params,
                cookies=cookies,
                headers=headers,
                timeout=30,
            )

            if resp.status_code == 412:
                print(f"[WARN] 412 风控 — 接口: space/arc/search, pn={pn}, "
                      f"返回: {resp.text[:200]}")
                break

            data = resp.json()
            if data.get("code") != 0:
                print(f"[WARN] API error: code={data.get('code')}, "
                      f"msg={data.get('message', '?')}, pn={pn}")
                break

            vlist = data.get("data", {}).get("list", {}).get("vlist", [])
            if not vlist:
                break

            for v in vlist:
                title = v.get("title", "")
                bvid = v.get("bvid", "")
                dur_str = v.get("length", "0:00")

                # Parse duration "MM:SS" or "HH:MM:SS"
                dur_parts = dur_str.split(":")
                if len(dur_parts) == 2:
                    dur_sec = int(dur_parts[0]) * 60 + int(dur_parts[1])
                elif len(dur_parts) == 3:
                    dur_sec = (int(dur_parts[0]) * 3600 +
                               int(dur_parts[1]) * 60 +
                               int(dur_parts[2]))
                else:
                    dur_sec = 0

                pubdate = v.get("created", 0)

                # Apply filters
                if dur_sec < min_sec:
                    continue
                if title_kw and title_kw not in title:
                    continue
                if any(kw.lower() in title.lower() for kw in exclude_kw):
                    continue

                candidates.append({
                    "bv_id": bvid,
                    "title": title,
                    "duration_sec": dur_sec,
                    "parts": 1,  # mobile API doesn't return parts; get_video_info needed for multi-P
                    "pubdate": pubdate,
                    "pubdate_str": time.strftime("%Y-%m-%d %H:%M", time.localtime(pubdate)) if pubdate else "?",
                })

                if len(candidates) >= max_videos:
                    break

            if len(candidates) >= max_videos:
                break

            # Low frequency between pages
            if pn < max_pages:
                time.sleep(0.5)

        except Exception as e:
            print(f"[WARN] Space listing failed (pn={pn}): {e}")
            break

    return candidates


def filter_long_recordings(bv_ids, config):
    """Filter BVs: keep only long gameplay recordings (not clips/highlights)."""
    min_sec = config.get("filter", {}).get("min_duration_min", 10) * 60
    exclude_kw = config.get("filter", {}).get("exclude_keywords", [])
    title_kw = config.get("filter", {}).get("title_keyword", "")

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
        if title_kw and title_kw not in title:
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
