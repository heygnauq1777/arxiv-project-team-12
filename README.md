# arXiv Project — Team 12

This repository contains the source code for Team 12's Introduction to Data Science arXiv project. The pipeline resolves the assigned arXiv papers, collects metadata and all available versions, downloads `.tex`/`.bib` source files, and retrieves reference metadata from Semantic Scholar.

## Project scope

- Assigned base IDs: `2601.03156` through `2601.08155` (inclusive; 5,000 IDs).
- The crawlers write working data under `data/`. That directory is intentionally excluded from Git; do not commit API keys or crawl output to this source repository.

## Requirements

- Linux or WSL with Bash
- Python 3 and `venv`
- A Semantic Scholar API key for the reference crawl
- Internet access to the arXiv and Semantic Scholar APIs

## Environment setup

Run these commands from the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r src/requirements.txt
```

For arXiv API etiquette, set `ARXIV_CONTACT` to an email address where the project team can be contacted. This value is used in the crawler's User-Agent; it is optional in the code but should be set when crawling.

```bash
export ARXIV_CONTACT="your-email@example.com"  # replace with your contact email
```

## Configure the Semantic Scholar API key

Do not put the API key in this README, a Python file, a command-line argument, or a committed `.env` file. The following Bash commands prompt for the key without displaying it, save it in a private file outside the repository, and set restrictive permissions:

```bash
install -d -m 700 "$HOME/.config/arxiv-project-team-12"
read -rsp "Semantic Scholar API key: " S2_API_KEY
printf '\n'
printf 'export S2_API_KEY=%q\n' "$S2_API_KEY" > "$HOME/.config/arxiv-project-team-12/secrets.sh"
chmod 600 "$HOME/.config/arxiv-project-team-12/secrets.sh"
unset S2_API_KEY
```

Before running the Semantic Scholar crawler in a new terminal, load the private file and verify that the variable is set without printing its value:

```bash
source "$HOME/.config/arxiv-project-team-12/secrets.sh"
test -n "$S2_API_KEY" && echo "S2_API_KEY is configured" || echo "S2_API_KEY is not configured"
```

## Run the crawlers

Run one crawler at a time from the repository root. Each command can be rerun after interruption; completed records are skipped and failed records can be retried. Use the assigned ID range explicitly:

```bash
# 1. Discover metadata and revision dates for the assigned papers
python -u src/crawl_arxiv.py meta 3156 8155

# 2. Download every version's source and extract only .tex/.bib files
python -u src/crawl_arxiv.py src 3156 8155

# 3. Fetch reference metadata (load S2_API_KEY first)
source "$HOME/.config/arxiv-project-team-12/secrets.sh"
python -u src/crawl_s2.py 3156 8155
```

The Semantic Scholar script also accepts another inclusive range, for example `python -u src/crawl_s2.py 3156 3175` for a small run. The arXiv crawler accepts `meta` or `src` followed by the inclusive start and end numeric IDs.

## Output files

- `data/arxiv/meta.jsonl` — one metadata record per base arXiv ID.
- `data/arxiv/revisions.jsonl` — revision dates for versions after `v1`.
- `data/arxiv/papers/` — extracted `.tex` and `.bib` files, organized by paper and version.
- `data/arxiv/sources_log.jsonl` — source download/extraction status and per-version measurements.
- `data/arxiv/source_inventory.csv` — tabular inventory, if generated during local auditing.
- `data/s2/references.jsonl` — Semantic Scholar response and status for each paper.

Statuses such as `pdf_only`, `not_found`, and `not_tex` are retained as records so unavailable or non-TeX sources are counted rather than silently dropped. `failed` means the attempt did not reach a terminal result; rerunning the relevant crawler retries those records.

## Monitor progress

The arXiv crawler prints metadata/revision progress and reports source progress every 25 versions. The Semantic Scholar crawler prints progress every 50 papers (or every paper for runs of at most 50). For a separate terminal, line counts show how many log attempts have been appended; retries may mean the line count is greater than the number of unique papers or versions:

```bash
watch -n 10 'wc -l data/arxiv/meta.jsonl data/arxiv/revisions.jsonl data/arxiv/sources_log.jsonl data/s2/references.jsonl'
```

Press `Ctrl-C` to stop `watch`; this does not stop a crawler running in another terminal. Let the crawler finish or stop it with `Ctrl-C`; rerun the same command to resume.

## Dependencies

The Python dependencies are listed in [`src/requirements.txt`](src/requirements.txt). Install them with `python -m pip install -r src/requirements.txt` after activating the virtual environment.
