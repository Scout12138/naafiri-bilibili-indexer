#!/usr/bin/env python3
"""Verify B站 cookies.txt login status and check 720p availability."""
import requests, sys, os

COOKIES_FILE = "cookies.txt"
BV_ID = "BV1xKVC6NEw2"

def parse_netscape_cookies(path):
    """Parse Netscape-format cookies.txt into a dict."""
    cookies = {}
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            # Handle #HttpOnly_ prefix (from "Get cookies.txt LOCALLY" extension)
            if line.startswith('#HttpOnly_'):
                line = line[len('#HttpOnly_'):]
            # Skip pure comment lines (but NOT #HttpOnly_ lines which we just stripped)
            if line.startswith('#'):
                continue
            parts = line.split('\t')
            if len(parts) >= 7:
                cookies[parts[5]] = parts[6]
    return cookies

def verify_login(cookies):
    """Check if cookies are valid for B站."""
    resp = requests.get(
        'https://api.bilibili.com/x/web-interface/nav',
        cookies=cookies,
        headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'https://www.bilibili.com/',
        }
    )
    data = resp.json()
    is_login = data.get('data', {}).get('isLogin', False)
    uname = data.get('data', {}).get('uname', '?')
    code = data.get('code', -1)
    return is_login, uname, code

def main():
    if not os.path.exists(COOKIES_FILE):
        print(f"ERROR: {COOKIES_FILE} not found")
        sys.exit(1)

    cookies = parse_netscape_cookies(COOKIES_FILE)
    print(f"Parsed {len(cookies)} cookies from {COOKIES_FILE}")

    # Step A: Verify login
    is_login, uname, code = verify_login(cookies)
    print(f"\n=== Login Check ===")
    print(f"  code: {code}")
    print(f"  isLogin: {is_login}")
    print(f"  uname: {uname}")

    if not is_login:
        print("FAIL: Cookies are not logged in or expired. Please provide fresh cookies.")
        sys.exit(1)

    print("PASS: Cookies valid, logged in as", uname)

    # Step B: Check 720p availability via yt-dlp
    print(f"\n=== 720p Check for {BV_ID} ===")
    import subprocess
    result = subprocess.run(
        ['python', '-m', 'yt_dlp', '--cookies', COOKIES_FILE, '-F',
         f'https://www.bilibili.com/video/{BV_ID}'],
        capture_output=True, text=True, encoding='utf-8', errors='replace',
        timeout=60
    )
    output = result.stdout + result.stderr
    print(output[:3000])

    has_720p = '1280x720' in output or '720p' in output
    if has_720p:
        print(f"\nPASS: {BV_ID} has 720p available")
    else:
        print(f"\nWARN: {BV_ID} - 720p not confirmed in format list")

    print("\n=== All checks complete ===")

if __name__ == '__main__':
    main()
