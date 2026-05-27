# Local Ollama planner (Atlas tool decisions)

Atlas can use a **local Ollama model** for tool selection and argument generation, while **OpenAI Realtime** still produces the final Jarvis-style spoken/text reply after tools run.

## Hardware note (RTX 3060 Laptop, 6 GB VRAM)

| Model | VRAM | Typical planner latency |
|-------|------|-------------------------|
| **`qwen2.5:3b-instruct`** (default fast) | ~2 GB, **100% GPU** | 1–3 s simple, 3–5 s complex |
| `llama3.2:3b`, `phi3:mini` | ~2 GB | similar tier |
| **`qwen2.5:7b-instruct`** (heavy fallback) | ~5.4 GB, often **39% CPU / 61% GPU** on 6 GB | 14–34 s — avoid as default |

**GPU check:**

```powershell
nvidia-smi
ollama ps
# or run tests — prints processor split
.\scripts\test_local_planner.ps1
```

If `ollama ps` shows `CPU/GPU` split, switch to a 3B model so weights fit entirely in VRAM.

## Latency optimizations (built-in)

1. **Deterministic shortcuts** (<200 ms): open transport map, switch transport mode, 3D graph, search stops near X, “what can you do?”
2. **Domain-scoped tool catalog**: transport commands only see ~13 transport tools (~1.5k chars), not all 30 (~6.4k).
3. **Slim JSON schema**: `status`, `tool`, `arguments`, `final_summary` only.
4. **Fast/heavy model tiering**: 3B for simple; 7B only for complex multi-step utterances.
5. **OpenAI fallback** on validation failure (default on) or optional slow fallback (`ATLAS_LOCAL_PLANNER_SLOW_FALLBACK=1`).

## Install Ollama

```powershell
ollama pull qwen2.5:3b-instruct
ollama pull qwen2.5:7b-instruct   # heavy fallback only
# optional benchmarks:
ollama pull llama3.2:3b
ollama pull phi3:mini
```

## Enable local planner

```env
ATLAS_PLANNER_BACKEND=auto
ATLAS_LOCAL_PLANNER_URL=http://127.0.0.1:11434
ATLAS_LOCAL_PLANNER_MODEL=qwen2.5:3b-instruct
ATLAS_LOCAL_PLANNER_MODEL_HEAVY=qwen2.5:7b-instruct
ATLAS_LOCAL_PLANNER_TIMEOUT=60
ATLAS_LOCAL_PLANNER_FAST_TIMEOUT=8
ATLAS_LOCAL_PLANNER_RETRIES=2
ATLAS_LOCAL_PLANNER_FALLBACK_OPENAI=1
ATLAS_LOCAL_PLANNER_SLOW_MS=7000
# ATLAS_LOCAL_PLANNER_SLOW_FALLBACK=0   # set 1 to discard slow local results
# ATLAS_LOCAL_PLANNER_DEBUG=0           # set 1 to include reason/topic in JSON
```

**Instant revert to OpenAI-only:** `$env:ATLAS_PLANNER_BACKEND = "openai"`

## Test & benchmark

**Unit / planner path (no Realtime session):**

```powershell
.\scripts\test_local_planner.ps1
.\scripts\test_local_planner.ps1 -Benchmark
```

**Live app flow (Atlas running on :5055 via `run_web_app.ps1`):**

```powershell
.\run_web_app.ps1
# second terminal:
.\scripts\test_live_planner_flow.ps1
.\scripts\test_live_planner_flow.ps1 -IncludeFallbackTest
```

Or simulate the agent planner path without UI:

```powershell
.\src\work\atlas\.venv\Scripts\python.exe scripts\test_live_planner_flow.py
```

Grep live logs:

```powershell
Select-String -Path logs\activity.log -Pattern '\[PlannerLive\]'
```

Each UI turn logs: `path`, `latency_ms`, `tool`, `args`, `openai_planner_used`, `final_openai_response`.

## Logs

```text
[PlannerMetrics] backend=shortcut path=shortcut latency_ms=2 tool='cspe_open_transport_map' ...
[PlannerMetrics] backend=local path=local_fast model=qwen2.5:3b-instruct domain=transport prompt_chars=1842 latency_ms=2100 ...
[PlannerMetrics] slow_local latency_ms=14200 threshold_ms=7000
```

## Code layout

| File | Role |
|------|------|
| `planner_config.py` | Env: fast/heavy models, timeouts, fallback |
| `local_planner.py` | Ollama client, tiering, metrics |
| `planner_domains.py` | Domain classify + compact catalog |
| `planner_shortcuts.py` | Regex shortcuts (no LLM) |
| `ollama_runtime.py` | GPU / `ollama ps` probes |
| `agent_planner.py` | Multi-step loop |

Tool definitions remain in `tools_registry.json`.
