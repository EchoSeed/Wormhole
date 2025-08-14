# singularity_scan.py
# Stream-safe scanner for exact vector clones and near-clones across many JSON files.
# Usage:
#   python singularity_scan.py file1.json [file2.json ...]
# Works with JSON array files or NDJSON (one JSON object per line).

import sys, json, math, hashlib, random, os
from pathlib import Path

# --- tuning ---
PREC = 17           # decimals/significant figs kept for exact-match hashing
NEAR_THRESH = 0.9995  # cosine threshold for near-clones
N_PROJ = 12         # random projections for cheap prefilter

def round_vec(v, p=PREC):
    # keep ~17 significant figures per element
    return tuple(float(f"{x:.{p}g}") for x in v)

def hash_vec(v):
    # stable hash of rounded vector
    h = hashlib.sha256()
    for x in v:
        h.update(("{:.17g}".format(x)).encode())
        h.update(b",")
    return h.hexdigest()

def dot(a,b): return sum(x*y for x,y in zip(a,b))
def norm(v): return math.sqrt(sum(x*x for x in v)) or 1.0
def cos(a,b): return dot(a,b)/(norm(a)*norm(b))

def gen_projections(dim, n=N_PROJ, seed=47):
    rng = random.Random(seed)
    R = []
    for _ in range(n):
        # Rademacher projection vector (+1/-1)
        R.append([1.0 if rng.random() < 0.5 else -1.0 for _ in range(dim)])
    return R

def sign_signature(v, R):
    # tuple of signs of random projections; used as an LSH-style bucket key
    sig = []
    for r in R:
        s = 0.0
        for xi, ri in zip(v, r):
            s += xi*ri
        sig.append(1 if s >= 0 else 0)
    return tuple(sig)

def stream_glyphs(path):
    # Accepts either a JSON array file or NDJSON (one JSON object per line)
    with open(path, "r", encoding="utf-8") as f:
        first = f.read(1)
        f.seek(0)
        if first == "[":
            data = json.load(f)
            for g in data:
                yield g, path
        else:
            for line in f:
                line = line.strip()
                if not line: continue
                g = json.loads(line)
                yield g, path

def main(paths):
    exact_index = {}   # hash -> [(id, file)]
    sig_buckets = {}   # signature -> [(id, file, vec_rounded, vec_raw)]
    dims = None
    R = None
    total = 0

    for p in paths:
        for g, src in stream_glyphs(p):
            gid = g.get("id")
            v = g.get("vec")
            if not gid or not isinstance(v, list): 
                continue
            if dims is None:
                dims = len(v)
                R = gen_projections(dims)
            elif len(v) != dims:
                # skip mismatched dims
                continue

            try:
                v_raw = tuple(float(x) for x in v)
            except Exception:
                continue

            v_r = round_vec(v_raw, PREC)

            # exact clone index
            h = hash_vec(v_r)
            exact_index.setdefault(h, []).append((gid, os.path.basename(src)))

            # near-clone buckets by random projections
            sig = sign_signature(v_raw, R)
            sig_buckets.setdefault(sig, []).append((gid, os.path.basename(src), v_r, v_raw))
            total += 1

    # Report exact clones (cross-file or within-file)
    print(f"Scanned {total} glyphs across {len(paths)} files.")
    print("\n=== EXACT VECTOR CLUSTERS (precision ~17 sig figs) ===")
    count_exact = 0
    for h, lst in exact_index.items():
        if len(lst) > 1:
            count_exact += 1
            print(f"- size={len(lst)} :: " + ", ".join([f\"{gid}@{src}\" for gid, src in lst]))
    if count_exact == 0:
        print("none")

    # Near-clone search inside buckets (only compare within bucket to stay fast)
    print(f"\n=== NEAR-CLONES (cos ≥ {NEAR_THRESH}) ===")
    seen_pairs = set()
    found_near = 0
    for sig, entries in sig_buckets.items():
        if len(entries) < 2: 
            continue
        # brute compare within bucket
        for i in range(len(entries)):
            gid_i, src_i, vri, vi = entries[i]
            for j in range(i+1, len(entries)):
                gid_j, src_j, vrj, vj = entries[j]
                key = (gid_i, gid_j)
                if key in seen_pairs: 
                    continue
                c = cos(vi, vj)
                if c >= NEAR_THRESH:
                    found_near += 1
                    print(f\"{gid_i}@{src_i}  <->  {gid_j}@{src_j}   cos={c:.6f}\")
                seen_pairs.add(key)
    if found_near == 0:
        print("none")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python singularity_scan.py file1.json [file2.json ...]")
        sys.exit(1)
    main(sys.argv[1:])
