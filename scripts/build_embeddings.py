#!/usr/bin/env python3
"""Build OpenCLIP ViT-L/14 reference embeddings for the asset library."""
import csv, os, pickle, torch, open_clip
from PIL import Image

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
ASSETS_DIR = "data/assets/lol_loading_v2"
CHAMPION_MAP = "data/assets/champion_map_v2.csv"
CACHE_PATH = "data/crops/ref_v2_vit_l14.pkl"

# Load reference paths
ref_paths, ref_champs = [], []
with open(CHAMPION_MAP, "r", encoding="utf-8-sig") as f:
    for row in csv.DictReader(f):
        p = os.path.join(ASSETS_DIR, row["image_path"])
        if os.path.exists(p):
            ref_paths.append(p)
            ref_champs.append(row["champion_en"])

print(f"References: {len(ref_paths)} images, {len(set(ref_champs))} champions")

# Load model
print("Loading OpenCLIP ViT-L/14...")
model, _, preprocess = open_clip.create_model_and_transforms(
    "ViT-L-14", pretrained="datacomp_xl_s13b_b90k"
)
model = model.to(DEVICE)
model.eval()

# Build embeddings
bs = 64
embs = []
for i in range(0, len(ref_paths), bs):
    batch = [preprocess(Image.open(p).convert("RGB")) for p in ref_paths[i : i + bs]]
    with torch.no_grad():
        e = model.encode_image(torch.stack(batch).to(DEVICE))
        e = e / e.norm(dim=-1, keepdim=True)
    embs.append(e.cpu())
    if (i + bs) % 512 == 0:
        print(f"  {min(i+bs, len(ref_paths))}/{len(ref_paths)}")

embs = torch.cat(embs, dim=0)
with open(CACHE_PATH, "wb") as f:
    pickle.dump({"embeddings": embs, "champions": ref_champs, "paths": ref_paths}, f)
print(f"Saved: {CACHE_PATH} ({embs.shape})")
