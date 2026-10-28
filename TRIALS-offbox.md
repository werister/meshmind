# TRIALS — off-box disk recon + anything-llm / mem0 trial plans

Captured 2026-10-27 in worktree `wt-lab-research` (branch `research/assist`).
Read-only recon + docs only. Nothing deleted, nothing installed, nothing merged.

Machine: MacBook (M2, macOS 26.2). Internal APFS data volume **100% full, ~1.0 GB
avail** (`df` on `/System/Volumes/Data`). This is the blocker: splash (needs M3+ /
macOS 26.4), TensorSharp (needs dotnet SDK), and open-webui (needs Docker daemon +
GBs) are all out until space is freed. The two viable off-box trials — anything-llm
and mem0 — must wait for disk, then point at the Mini over the tailnet.

---

## 1. Disk recon (read-only, `du`/`df`/`readlink`) — top 10 hogs

**Key correction up front:** the 122 GB Ollama blob store is **NOT on internal disk**
— `~/.ollama` is a symlink to `/Volumes/AthenaSSD/local-models/ollama` (external SSD,
`/dev/disk5s1`). It does not count toward the 1.0 GB-free internal problem and must not
be touched for this. All ten hogs below are on the internal volume.

| # | Path | Size | Notes |
|---|---|---|---|
| 1 | ~/Library/Application Support/Claude/vm_bundles | 11 GB | Claude desktop VM bundles; largest single internal item. |
| 2 | ~/Pictures/Photos Library.photoslibrary | 25 GB | Photos library (originals); large but user data. |
| 3 | ~/.cache/uv | 4.5 GB | uv (Python) package cache; fully regenerable. |
| 4 | ~/Library/Containers/com.sigmaos.sigmaos.macos | 4.3 GB | SigmaOS browser container. |
| 5 | ~/Library/Application Support/Google | 3.9 GB | Chrome/Google app data. |
| 6 | ~/.gemini/antigravity-browser-profile | 3.6 GB | Gemini "antigravity" browser profile. |
| 7 | ~/Library/Containers/com.docker.docker | 2.8 GB | Docker Desktop data (VM disk image); open-webui would need this + more. |
| 8 | ~/.local/share/uv | 2.5 GB | uv installed-tool store; regenerable. |
| 9 | ~/Downloads | 2.2 GB | Downloads; typically safe to clear. |
| 10 | ~/.local/share/muse | 2.1 GB | "muse" data store. |

Honorable mentions (regenerable AI-CLI caches, each 0.2–1.5 GB): `~/.cache/codex-runtimes`
(1.5 GB), `~/Library/Caches/Google` (834 MB), `~/Library/Caches/token-monitor-updater`
(255 MB), `~/.claude`/`~/.codex`/`~/.gemini` runtime/log subdirs.

### Cleanup shortlist, ranked by safety (DELETE NOTHING — this is a plan)

**Tier A — safest, regenerable caches (reclaim ≈ 9–10 GB).** No user data; tools
rebuild on next run.
- `~/.cache/uv` (4.5 GB) + `~/.local/share/uv` (2.5 GB) → `uv cache clean` (reclaims ~7 GB).
- `~/.cache/codex-runtimes` (1.5 GB), `~/Library/Caches/Google` (834 MB), `~/Library/Caches/token-monitor-updater` (255 MB).

**Tier B — app caches / disposable bundles (reclaim ≈ 11–15 GB), low risk.** Re-downloaded
or rebuilt by the owning app; verify the app is idle first.
- Claude `vm_bundles` (11 GB) — reclaimed when Claude desktop rebuilds its VM; confirm no active Claude session.
- `~/Downloads` (2.2 GB) — review and clear what's already archived elsewhere.
- Docker `com.docker.docker` (2.8 GB) — only if Docker isn't needed; reclaim via Docker Desktop "clean / purge data" (also frees room open-webui would later need).

**Tier C — bigger but user-judgment (reclaim 25+ GB), NOT recommended blind.** Real
data; owner must decide.
- Photos Library (25 GB) — offload to external/iCloud, don't delete.
- Browser profiles / SigmaOS / Google app data (3–4 GB each) — losing them logs you out / drops history.

Freeing just **Tier A + the Claude vm_bundles** comfortably clears the ~15–20 GB both
trials below need, without touching any user data.

---

## 2. Trial plan — mem0 (OSS) → Mini over tailnet  [CHEAPER PLAN]

Why cheapest: mem0 is a `pip`-installed Python library (no Docker, no Electron app).
On the MacBook it needs only a venv + the package + a vector store. Point both the LLM
and the embedder at the Mini's Ollama endpoint, so **no model weights live on the
MacBook**. Disk cost is just Python deps.

### Prerequisites (verify, don't install yet)
- Mini reachable: `https://mac-mini-von-hugo-1.taild73e38.ts.net` (per AGENTS.md).
- An embedding model present on the Mini. `docs/MODEL-FIT.md` flags embeddings as a gap
  ("first embeddings lane") and lists `bge-m3` as a planned pull. **Pre-req on the Mini:**
  `ollama pull bge-m3` (or `nomic-embed-text`). If absent, the trial's embedder step fails.
- A chat model on the Mini: `qwen3:4b` (default per AGENTS.md).

### Expected disk cost (MacBook, internal)
- Python venv + mem0 + deps (chromadb or qdrant-client, numpy): **~400–700 MB**.
- Local vector store (Chroma, embedded) data: **tens of MB** for a trial corpus.
- Total: **< 1 GB** — the lightest of the two. Still needs Tier-A cleanup first.

### Commands (run AFTER disk is freed)
```bash
# 1. Isolated env in the worktree's parent dev area (NOT in this git worktree)
python3 -m venv ~/dev/trial-mem0 && source ~/dev/trial-mem0/bin/activate
pip install "mem0ai" chromadb        # chroma = embedded local vector store, no server

# 2. Confirm the Mini answers before wiring mem0
curl -s https://mac-mini-von-hugo-1.taild73e38.ts.net/api/tags | python3 -m json.tool | head

# 3. Trial script: LLM + embedder both on the Mini's Ollama
cat > ~/dev/trial-mem0/run.py <<'PY'
from mem0 import Memory
cfg = {
  "llm": {"provider": "ollama", "config": {
      "model": "qwen3:4b",
      "ollama_base_url": "https://mac-mini-von-hugo-1.taild73e38.ts.net"}},
  "embedder": {"provider": "ollama", "config": {
      "model": "bge-m3",
      "ollama_base_url": "https://mac-mini-von-hugo-1.taild73e38.ts.net"}},
  "vector_store": {"provider": "chroma", "config": {"path": "/Users/hugohader/dev/trial-mem0/chroma"}},
}
m = Memory.from_config(cfg)
m.add("I prefer concise answers and I run an 8GB Intel Mac mini lab.", user_id="hugo")
print("SEARCH:", m.search("what hardware do I run?", user_id="hugo"))
PY
python ~/dev/trial-mem0/run.py
```

### Pass / fail checks
- **PASS:** step 2 lists models (Mini reachable); step 3 prints a non-empty `SEARCH`
  result whose memory text mentions the stored fact (8GB / Mac mini), proving both the
  embedder (stored + retrieved) and the LLM (fact extraction) ran on the Mini.
- **FAIL:** connection error to the tailnet URL; or embedder 404 (bge-m3 not pulled on
  Mini); or empty search result (embedding/vector path broken).
- Grounding note: mem0's fact extraction calls the LLM — if answers look generic,
  confirm the Mini actually served the request (check `/status` or feedback log).

### Rollback
```bash
deactivate 2>/dev/null
rm -rf ~/dev/trial-mem0         # removes venv + chroma data; nothing else touched
```
No system packages, no daemons, no changes on the Mini beyond an optional `ollama pull
bge-m3` (keep it — it fills the lab's embeddings gap; or `ollama rm bge-m3` to revert).

---

## 3. Trial plan — anything-llm → Mini over tailnet

Two install paths; **use Desktop, not Docker** (Docker daemon is a blocker and Docker
data already eats 2.8 GB internal). The Desktop app bundles its own LanceDB + embedder,
so RAG runs locally on the MacBook while the **chat LLM** is the Mini's Ollama.

### Expected disk cost (MacBook, internal)
- AnythingLLM Desktop .dmg + installed app: **~700 MB–1.2 GB**.
- Built-in embedder model (all-MiniLM) downloaded on first run: **~100–200 MB**.
- LanceDB index for a trial doc set: **tens to low-hundreds of MB**.
- Total: **~1–1.5 GB** — heavier than mem0, still modest. Needs Tier-A cleanup first.

### Prerequisites (verify, don't install yet)
- Mini reachable at the tailnet URL; `qwen3:4b` present (`/api/tags`).
- Note from docs: inside Docker, `localhost` points at the container — not relevant here
  because Desktop runs natively, so the tailnet URL works directly as the Ollama base.

### Commands (run AFTER disk is freed)
```bash
# 1. Download the Apple-silicon desktop build (URL from docs.anythingllm.com desktop page)
#    Prefer the official download page; then install the .dmg normally.
#    (Docs: installation-desktop/overview)

# 2. Pre-flight the Mini endpoint
curl -s https://mac-mini-von-hugo-1.taild73e38.ts.net/api/tags | python3 -m json.tool | head

# 3. In the app GUI:
#    Settings → LLM Preference → Ollama
#      Base URL:  https://mac-mini-von-hugo-1.taild73e38.ts.net
#      Model:     qwen3:4b
#      Max tokens / context: keep <= 4096 (lab envelope)
#    Embedding: leave on AnythingLLM built-in (local, free) OR point to Mini's bge-m3.
#    Vector DB: leave on built-in LanceDB.
# 4. Create a workspace, upload 2-3 small PDFs/notes, ask a grounded question.
```

### Pass / fail checks
- **PASS:** app connects to Ollama (model list populates in the dropdown from the Mini);
  a workspace chat returns an answer that **cites the uploaded document** (RAG hit), and
  the Mini's `/status` or feedback log shows the inference request.
- **FAIL:** model dropdown empty (tailnet/Ollama URL wrong); upload/embeds error
  (embedder misconfigured); answers ignore the document (retrieval/LanceDB broken).

### Rollback
- Quit AnythingLLM Desktop.
- Delete the app bundle and its data dir (`~/Library/Application Support/anythingllm-desktop`
  or similar — confirm exact path in-app before removing).
- Trash the .dmg. No daemons, no system services, nothing changed on the Mini.

---

## 4. Which to run first

**mem0 is the cheaper and lower-risk trial** (< 1 GB, pip-only, one-command rollback,
no GUI, no model weights on the MacBook). Run it first to validate the tailnet-Ollama
path end-to-end (and to justify pulling `bge-m3` on the Mini, closing the embeddings
gap). Then run the anything-llm Desktop trial for the richer RAG UI. Both are blocked
until the internal disk is freed — start with Tier-A cache cleanup (~9–10 GB) plus the
Claude vm_bundles (11 GB).
