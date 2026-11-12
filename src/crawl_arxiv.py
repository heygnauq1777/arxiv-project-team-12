import gzip, json, os, re, sys, tarfile, time
from pathlib import Path
import arxiv, requests

CONTACT = os.environ.get("ARXIV_CONTACT", "your-email@example.com")
UA = f"hcmus-intro-ds-student-project/1.0 (mailto:{CONTACT})"
DATA = Path("data/arxiv")
PAPERS = DATA / "papers"
META, REV, SRC_LOG = DATA / "meta.jsonl", DATA / "revisions.jsonl", DATA / "sources_log.jsonl"
DATA.mkdir(parents=True, exist_ok=True)

mode = sys.argv[1] if len(sys.argv) > 1 else ""
START, END = (int(sys.argv[2]), int(sys.argv[3])) if len(sys.argv) == 4 else (3156, 8155)
IDS = [f"2601.{n:05d}" for n in range(START, END + 1)]

def read_jsonl(p):
    out = []
    if p.exists():
        with open(p, encoding="utf-8") as f:
            for line in f:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    pass          # dòng cuối bị cắt dở khi bị ngắt
    return out

def split_version(entry_id):
    short = entry_id.rsplit("/", 1)[-1]          # vd 2601.03157v2
    base, v = short.rsplit("v", 1)
    return base, int(v)

# ---------- Giai đoạn 1: metadata ----------
def crawl_meta():
    done = {r["arxiv_id"] for r in read_jsonl(META)}
    todo = [i for i in IDS if i not in done]
    client = arxiv.Client(page_size=100, delay_seconds=3.0, num_retries=5)
    with open(META, "a", encoding="utf-8") as f:
        for s in range(0, len(todo), 100):
            batch = todo[s:s + 100]
            try:
                results = list(client.results(arxiv.Search(id_list=batch, max_results=len(batch))))
            except Exception as e:
                print("Lỗi lô", batch[0], e); continue
            seen = set()
            for r in results:
                base, n = split_version(r.entry_id)
                seen.add(base)
                f.write(json.dumps({
                    "arxiv_id": base, "n_versions": n, "title": r.title,
                    "authors": [a.name for a in r.authors],
                    "submission_date": r.published.isoformat(),
                    "last_updated": r.updated.isoformat(),
                    "venue": r.journal_ref, "primary_category": r.primary_category,
                }, ensure_ascii=False) + "\n")
            for i in batch:
                if i not in seen:
                    f.write(json.dumps({"arxiv_id": i, "missing": True}) + "\n")
            f.flush()
            print(f"meta {s + len(batch)}/{len(todo)}")

def crawl_revisions():
    have = {r["version_id"] for r in read_jsonl(REV)}
    wanted = [f"{p['arxiv_id']}v{v}" for p in read_jsonl(META)
              if not p.get("missing") and p["arxiv_id"] in IDS
              for v in range(2, p["n_versions"] + 1)]
    todo = [w for w in wanted if w not in have]
    client = arxiv.Client(page_size=100, delay_seconds=3.0, num_retries=5)
    with open(REV, "a", encoding="utf-8") as f:
        for s in range(0, len(todo), 100):
            batch = todo[s:s + 100]
            try:
                for r in client.results(arxiv.Search(id_list=batch, max_results=len(batch))):
                    f.write(json.dumps({"version_id": r.entry_id.rsplit("/", 1)[-1],
                                        "date": r.updated.isoformat()}) + "\n")
            except Exception as e:
                print("Lỗi lô revisions", batch[0], e)
            f.flush()
            print(f"revisions {s + len(batch)}/{len(todo)}")

# ---------- Giai đoạn 2: tải source ----------
_last = [0.0]
def pace(gap=3.0):
    wait = gap - (time.time() - _last[0])
    if wait > 0:
        time.sleep(wait)
    _last[0] = time.time()

def download(session, vid, dest):
    url = f"https://export.arxiv.org/src/{vid}"
    chunk_size = 8 << 20  # request small byte ranges to avoid truncated large responses
    errors = []
    while True:
        offset = dest.stat().st_size if dest.exists() else 0
        headers = {"Range": f"bytes={offset}-{offset + chunk_size - 1}"}
        delay = 5
        progressed = False
        for attempt in range(1, 7):
            pace(gap=15.0)
            try:
                with session.get(url, stream=True, timeout=(15, 120), headers=headers) as r:
                    if r.status_code == 416 and offset:
                        match = re.fullmatch(r"bytes \*/(\d+)", r.headers.get("Content-Range", ""))
                        if match and offset == int(match.group(1)):
                            return "downloaded", offset, None
                        reason = f"HTTP 416 at byte {offset}; Content-Range={r.headers.get('Content-Range', 'missing')}"
                        errors.append(reason)
                        print(f"{vid}: {reason}", file=sys.stderr, flush=True)
                        dest.unlink(missing_ok=True)
                        progressed = True  # restart from byte zero
                        break
                    if r.status_code == 404:
                        return "not_found", 0, None
                    if r.status_code in (429, 500, 502, 503, 504):
                        ra = r.headers.get("Retry-After", "")
                        reason = f"HTTP {r.status_code}; Retry-After={ra or 'not supplied'}"
                        errors.append(reason)
                        print(f"{vid}: attempt {attempt}/6 at byte {offset}: {reason}", file=sys.stderr, flush=True)
                        time.sleep(int(ra) if ra.isdigit() else delay)
                        delay = min(delay * 2, 300)
                        continue
                    if r.status_code not in (200, 206):
                        reason = f"HTTP {r.status_code}; Content-Type={r.headers.get('Content-Type', 'unknown')}"
                        print(f"{vid}: {reason}", file=sys.stderr, flush=True)
                        return f"error_{r.status_code}", 0, reason

                    total = None
                    if r.status_code == 206:
                        content_range = r.headers.get("Content-Range", "")
                        match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+|\*)", content_range)
                        if not match or int(match.group(1)) != offset:
                            reason = f"Unexpected Content-Range at byte {offset}: {content_range or 'missing'}"
                            print(f"{vid}: {reason}", file=sys.stderr, flush=True)
                            return "error_range_mismatch", 0, reason
                        if match.group(3) != "*":
                            total = int(match.group(3))
                        mode = "ab" if offset else "wb"
                    else:
                        # Server ignored Range; replace the partial file with the full response.
                        mode = "wb"
                        content_length = r.headers.get("Content-Length")
                        total = int(content_length) if content_length and content_length.isdigit() else None

                    before = dest.stat().st_size if dest.exists() and mode == "ab" else 0
                    with open(dest, mode) as f:
                        for chunk in r.iter_content(1 << 16):
                            if chunk:
                                f.write(chunk)
                    size = dest.stat().st_size
                    if r.status_code == 200:
                        return "downloaded", size, None
                    if total is not None and size >= total:
                        return "downloaded", size, None
                    if size > before:
                        progressed = True
                        break
                    reason = f"HTTP 206 returned no bytes at offset {offset}"
                    errors.append(reason)
                    print(f"{vid}: attempt {attempt}/6: {reason}", file=sys.stderr, flush=True)
            except requests.RequestException as e:
                size = dest.stat().st_size if dest.exists() else 0
                reason = f"{type(e).__name__}: {e}"
                errors.append(reason)
                print(f"{vid}: attempt {attempt}/6 at byte {offset}: {reason}", file=sys.stderr, flush=True)
                if size != offset:
                    progressed = True
                    break
                time.sleep(delay)
                delay = min(delay * 2, 300)
        if not progressed:
            return "failed", 0, " | ".join(errors)

def extract(path, outdir):
    kept = n = 0
    if tarfile.is_tarfile(path):
        with tarfile.open(path, "r:*") as tf:
            for m in tf:
                if not m.isfile():
                    continue
                name = os.path.normpath(m.name)
                if os.path.isabs(name) or name.startswith(".."):
                    continue
                if not name.lower().endswith((".tex", ".bib")):
                    continue
                data = tf.extractfile(m).read()
                dest = outdir / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(data); kept += len(data); n += 1
        return ("ok" if n else "no_tex"), kept, n
    raw = Path(path).read_bytes()
    if raw[:2] == b"\x1f\x8b":
        try:
            raw = gzip.decompress(raw)
        except Exception:
            return "bad_archive", 0, 0
    if raw[:4] == b"%PDF":
        return "pdf_only", 0, 0
    if b"\\documentclass" in raw or b"\\begin{document}" in raw:
        outdir.mkdir(parents=True, exist_ok=True)
        (outdir / "main.tex").write_bytes(raw)
        return "ok", len(raw), 1
    return "not_tex", 0, 0

FINAL = {"ok", "no_tex", "pdf_only", "not_tex", "not_found", "bad_archive"}

def crawl_sources():
    metas = [m for m in read_jsonl(META) if not m.get("missing") and m["arxiv_id"] in IDS]
    done = {r["version_id"] for r in read_jsonl(SRC_LOG) if r["status"] in FINAL}
    session = requests.Session(); session.headers["User-Agent"] = UA
    count = 0
    with open(SRC_LOG, "a", encoding="utf-8") as log:
        for m in metas:
            folder = PAPERS / m["arxiv_id"].replace(".", "-")
            for v in range(1, m["n_versions"] + 1):
                vid = f"{m['arxiv_id']}v{v}"
                if vid in done:
                    continue
                t0 = time.time()
                tmp = DATA / f"tmp_download_{vid}.bin"
                status, raw_bytes, error = download(session, vid, tmp)
                kept = nfiles = 0
                if status == "downloaded":
                    status, kept, nfiles = extract(tmp, folder / f"v{v}")
                    if status == "not_tex":
                        error = "Downloaded content was not a recognized TeX source, archive, or PDF"
                    elif status == "no_tex":
                        error = "Archive contained no .tex or .bib files"
                    elif status == "pdf_only":
                        error = "Source endpoint returned PDF bytes instead of TeX"
                if status != "failed": tmp.unlink(missing_ok=True)
                log.write(json.dumps({"version_id": vid, "status": status,
                                      "raw_bytes": raw_bytes, "kept_bytes": kept,
                                      "n_files": nfiles, "error": error,
                                      "seconds": round(time.time() - t0, 2)}) + "\n")
                log.flush()
                count += 1
                if count % 25 == 0:
                    print(f"{count} phiên bản đã xử lý, mới nhất: {vid} {status}")

if __name__ == "__main__":
    if mode == "meta":
        crawl_meta(); crawl_revisions()
    elif mode == "src":
        crawl_sources()
    else:
        print("Dùng: python src/crawl_arxiv.py meta|src [start end]")
