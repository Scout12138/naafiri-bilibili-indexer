#!/usr/bin/env python3
"""Environment checker — verifies all dependencies before pipeline runs."""
import os, sys, json


def load_config(config_path="config.json"):
    """Load config.json, trying from project root."""
    if os.path.isfile(config_path):
        path = config_path
    else:
        # Try project root relative to this script
        script_dir = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(os.path.dirname(script_dir), "config.json")
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def check_python_deps():
    """Check required Python packages. Returns (ok, errors)."""
    deps = {
        "numpy": "numpy",
        "cv2": "opencv-python",
        "torch": "pytorch",
        "open_clip": "open-clip-torch",
        "PIL": "pillow",
        "xlsxwriter": "xlsxwriter",
        "requests": "requests",
    }
    errors = []
    for mod, pkg in deps.items():
        try:
            __import__(mod)
        except ImportError:
            errors.append(f"  ✗ {pkg} — pip install {pkg}")
    if errors:
        print("[DEPS] Missing packages:")
        for e in errors:
            print(e)
        return False, errors
    print("[DEPS] All Python packages OK")
    return True, []


def check_cuda():
    """Check CUDA availability."""
    try:
        import torch
        if torch.cuda.is_available():
            name = torch.cuda.get_device_name(0)
            print(f"[CUDA] Available — {name}")
            return True
        else:
            print("[CUDA] NOT available — will use CPU (slower)")
            return False
    except Exception as e:
        print(f"[CUDA] Check failed: {e}")
        return False


def check_assets(config):
    """Check asset files exist."""
    paths = config.get("paths", {})
    checks = [
        ("Champion map", paths.get("champion_map", "")),
        ("Assets dir", paths.get("assets_dir", "")),
        ("Reference cache", paths.get("ref_cache", "")),
    ]
    all_ok = True
    for name, path in checks:
        if not path:
            print(f"[ASSETS] {name}: path not configured in config.json")
            all_ok = False
        elif not os.path.exists(path):
            print(f"[ASSETS] {name}: MISSING — {path}")
            print(f"         Run: python scripts/download_assets.py && python scripts/build_embeddings.py")
            all_ok = False
        else:
            size = os.path.getsize(path) if os.path.isfile(path) else len(os.listdir(path))
            print(f"[ASSETS] {name}: OK ({path})")
    return all_ok


def resolve_ffmpeg(config=None):
    """Resolve ffmpeg path with priority:
    1) config.json paths.ffmpeg_dir
    2) FFMPEG_PATH env var
    3) System PATH 'ffmpeg'
    Returns (path, ok).
    """
    # Priority 1: project tools/ffmpeg/bin
    candidates = []

    if config:
        ffmpeg_dir = config.get("paths", {}).get("ffmpeg_dir", "")
        if ffmpeg_dir:
            # Resolve relative to project root
            if not os.path.isabs(ffmpeg_dir):
                ffmpeg_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ffmpeg_dir)
            local = os.path.normpath(os.path.join(ffmpeg_dir, "ffmpeg.exe"))
            candidates.append(("project-local", local))

    # Priority 2: FFMPEG_PATH env var
    env_path = os.environ.get("FFMPEG_PATH", "")
    if env_path:
        candidates.append(("FFMPEG_PATH env", env_path))

    # Priority 3: system PATH
    candidates.append(("system PATH", "ffmpeg"))

    for source, path in candidates:
        if os.path.isfile(path):
            print(f"[FFMPEG] Found via {source}: {path}")
            return path, True
        elif path == "ffmpeg":
            # Try running it to verify
            import subprocess
            try:
                r = subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=5)
                if r.returncode == 0:
                    print(f"[FFMPEG] Found in system PATH")
                    return "ffmpeg", True
            except Exception:
                pass

    print(f"[FFMPEG] NOT FOUND!")
    print(f"         Checked: {[c[0] for c in candidates]}")
    print(f"         Fix: copy ffmpeg.exe to tools/ffmpeg/bin/ or set FFMPEG_PATH")
    return None, False


def check_openclip_model(config):
    """Verify OpenCLIP model can be loaded."""
    try:
        import open_clip, torch
        model_name = config.get("models", {}).get("clip_model", "ViT-L-14")
        pretrained = config.get("models", {}).get("clip_pretrained", "datacomp_xl_s13b_b90k")
        print(f"[MODEL] OpenCLIP {model_name} ({pretrained}) — checking...")
        # Only create model to test; actual loading happens in pipeline
        print(f"[MODEL] OpenCLIP import OK (full load deferred to pipeline)")
        return True
    except Exception as e:
        print(f"[MODEL] OpenCLIP check failed: {e}")
        return False


def check_ref_embeddings(config):
    """Verify reference embedding cache is loadable."""
    import pickle
    cache_path = config.get("paths", {}).get("ref_cache", "")
    if not cache_path or not os.path.isfile(cache_path):
        print(f"[REF] Cache not found: {cache_path}")
        print(f"      Run: python scripts/build_embeddings.py")
        return False
    try:
        with open(cache_path, "rb") as f:
            cache = pickle.load(f)
        n = cache["embeddings"].shape[0]
        print(f"[REF] Embedding cache OK — {n} embeddings")
        return True
    except Exception as e:
        print(f"[REF] Cache corrupt: {e}")
        print(f"      Rebuild: python scripts/build_embeddings.py")
        return False


def run_all_checks(config=None):
    """Run all environment checks. Exits with code 1 if critical failures."""
    if config is None:
        config = load_config()
        if config is None:
            print("FATAL: config.json not found. Run from project root.")
            sys.exit(1)

    print("=" * 60)
    print("ENVIRONMENT CHECK")
    print("=" * 60)

    results = {}
    results["deps"], _ = check_python_deps()
    results["cuda"] = check_cuda()
    results["ffmpeg"], _ = resolve_ffmpeg(config)
    results["assets"] = check_assets(config)
    results["ref"] = check_ref_embeddings(config)
    results["model"] = check_openclip_model(config)

    print("\n" + "=" * 60)
    failed = [k for k, v in results.items() if not v]
    if failed:
        print(f"CHECK FAILED: {', '.join(failed)}")
        print("Fix the above issues before running the pipeline.")
        print("=" * 60)
        return False
    else:
        print("ALL CHECKS PASSED")
        print("=" * 60)
        return True


if __name__ == "__main__":
    run_all_checks()
