import json, os, sys, time
from pathlib import Path
import requests

API_KEY = os.environ["S2_API_KEY"]
URL = "https://api.semanticscholar.org/graph/v1/paper/arXiv:{}"
FIELDS = ("title,references.title,references.authors,references.year,"
          "references.publicationDate,references.venue,references.externalIds")
OUT = Path("data/s2/references.jsonl")
OUT.parent.mkdir(parents=True, exist_ok=True)

# Dùng: python src/crawl_s2.py            -> cả 5000 bài
#       python src/crawl_s2.py 3156 3175  -> chạy thử một đoạn
START, END = (int(sys.argv[1]), int(sys.argv[2])) if len(sys.argv) == 3 else (3156, 8155)
IDS = [f"2601.{n:05d}" for n in range(START, END + 1)]

def fetch(session, arxiv_id, max_retries=6):
    delay = 1.0
    last = None
    for _ in range(max_retries):
        try:
            r = session.get(URL.format(arxiv_id), params={"fields": FIELDS},
                            headers={"x-api-key": API_KEY}, timeout=30)
        except requests.RequestException:
            time.sleep(delay); delay *= 2; last = "network"; continue
        last = r.status_code
        if r.status_code == 200:
            return "ok", r.json()
        if r.status_code == 404:
            return "not_found", None
        if r.status_code in (429, 500, 502, 503, 504):
            time.sleep(delay); delay *= 2
            continue
        return f"error_{r.status_code}", None
    return f"failed_{last}", None

def load_done():
    done = set()
    if OUT.exists():
        with open(OUT, encoding="utf-8") as f:
            for line in f:
                rec = json.loads(line)
                if rec["status"] in ("ok", "not_found"):   # bài failed sẽ được thử lại
                    done.add(rec["arxiv_id"])
    return done

if __name__ == "__main__":
    done = load_done()
    todo = [i for i in IDS if i not in done]
    print(f"Đã xong {len(done)}, còn {len(todo)} bài trong đoạn này")
    session = requests.Session()
    with open(OUT, "a", encoding="utf-8") as f:
        for k, aid in enumerate(todo, 1):
            t0 = time.time()
            status, data = fetch(session, aid)
            refs = (data or {}).get("references") or []
            f.write(json.dumps({"arxiv_id": aid, "status": status,
                                "n_refs": len(refs), "data": data},
                               ensure_ascii=False) + "\n")
            f.flush()
            if k % 50 == 0 or len(todo) <= 50:
                print(f"{k}/{len(todo)}  {aid}  status={status}  refs={len(refs)}")
            time.sleep(max(0, 1.05 - (time.time() - t0)))   # giữ ~1 request/giây
