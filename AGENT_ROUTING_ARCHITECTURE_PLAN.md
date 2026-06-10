# Agent Routing Architecture Plan

This document proposes a cleaner routing architecture for the Atlas/CSPE agent system. It is based on inspection of the current codebase and describes a **target design only** — no code changes are included here.

**Related reference:** `PROJECT_TECHNICAL_DOCUMENTATION.md` (current system as implemented).

---

## Executive Summary

Today, OpenAI (or Ollama fallback) selects **concrete tool names** (`cspe_compute_route`, `cspe_lookup_place_online`, etc.) from a 38-tool registry. Deterministic Python modules then **rewrite** some of those choices (`planner_place_info.py`, `planner_exploration.py`, `planner_shortcuts.py`, `planner_validator.py`). Execution still flows through the same `tool_executor.py` → Product Shell HTTP/shell-enqueue path.

The proposed architecture **separates intent understanding from execution**:

1. **OpenAI** outputs a structured **intent object** (domain + intent + entities + UI flags).
2. A **CentralIntentRouter** validates and routes to a **domain router**.
3. Each **domain router** maps intent → execution flow (existing tools/endpoints, composed server-side).
4. **Tool executor** and **Product Shell backend** remain the execution layer, initially unchanged behind adapters.

This preserves current behavior during migration while centralizing routing logic that is today scattered across planner modules, shortcuts, and validators.

---

## 1. Current Routing Architecture (As Implemented)

### 1.1 Entry and control flow

| Step | File | Function | What happens |
|------|------|----------|--------------|
| User text in UI | `frontend/src/hooks/useAtlasTextChat.ts` | `send()` | `POST /api/chat` |
| Chat proxy | `backend/product_shell/routers/chat.py` | `post_chat()` | `atlas_http.send_text_and_wait()` |
| Atlas enqueue | `src/work/atlas/.../app/api.py` | `text()` | `enqueue_user_text()` |
| Orchestrator | `src/work/atlas/.../core/orchestrator.py` | `route_and_handle()` | Memory guardrails → planner or semantic router |
| Planner turn | `src/work/atlas/.../core/agent_planner.py` | `run_planner_turn()` | Plan → validate → execute tools → build injection |
| Tool execution | `src/work/atlas/.../router/tool_executor.py` | `execute_tool()` | HTTP to Product Shell / SerpAPI / memory |
| Answer | `orchestrator.py` | Realtime `response.create` | Model speaks from injected tool results |

**Planner enable flag:** `ATLAS_AGENT_PLANNER` (default on). When off, `core/semantic_router.py` `route_semantic()` chooses tool or direct mode in one shot.

### 1.2 Planner resolution pipeline

**File:** `src/work/atlas/src/atlas_client/router/planner_pipeline.py`  
**Function:** `resolve_planner_plan()`

**Order today:**

```
1. try_planner_shortcut()          → planner_shortcuts.py (allowlisted tools only)
2. OpenAI Chat Completions         → agent_planner._plan_next_step_openai()
3. Local Ollama fallback           → local_planner.plan_next_step_local()
```

OpenAI receives:
- Full **tools catalog** from `build_router_catalog()` (`core/tool_instructions.py` → `list_tools()` + registry descriptions)
- **Context** from `session_state.format_router_context_summary()` + agent context
- System prompt in `agent_planner._PLANNER_SYSTEM` instructing tool chains

**Output today:** JSON with `status`, `steps[{tool, arguments}]`, or `direct` / `clarify`.

### 1.3 Post-OpenAI enrichment (deterministic rewrites)

**File:** `src/work/atlas/src/atlas_client/router/local_planner.py`  
**Function:** `enrich_planner_decision()`

Applied per step in `planner_plan.validate_and_enrich_plan()`:

| Module | Function | Rewrites |
|--------|----------|----------|
| `planner_exploration.py` | `apply_exploration_routing()` | POI/stop/area requests → `cspe_nearby_pois`, `cspe_nearby_stops`, `cspe_explore_area` + `sync_ui: true` |
| `planner_place_info.py` | `apply_place_info_routing()` | Station/POI info → `cspe_lookup_place_online` with `topic`, `kind` |
| (memory) | `memory_arg_enricher` | `memory_add` due_at / tags |

**File:** `src/work/atlas/src/atlas_client/router/planner_validator.py`  
**Function:** `validate_step_semantics()` — rejects wrong tool for intent (e.g. `web_search` for place info, `cspe_lookup_place_online` for map POI list).

### 1.4 Domain classification (local planner only)

**File:** `src/work/atlas/src/atlas_client/router/planner_domains.py`

| Function | Role |
|----------|------|
| `classify_planner_domain()` | Regex patterns → `transport`, `memory`, `music`, `visual`, `web`, `direct`, `general` |
| `filter_allowed_tools()` | Shrinks tool list for Ollama prompts |
| `build_compact_catalog()` | Shorter catalog for local planner |

**Note:** OpenAI primary path does **not** use domain filtering; it sees the full allowlist (subject to orchestrator `allowed_tools`).

### 1.5 Conversation focus (follow-ups)

**File:** `src/work/atlas/src/atlas_client/router/conversation_focus.py`  
**Function:** `resolve_conversation_focus(agent_context, router_context)`

Sources: `world.transport.last_place_lookup`, `selected_station`, `last_exploration.center`, router `last_place_focus`, last exploration tool args.

Used by: `detect_place_info_intent()`, `detect_exploration_intent()`, place lookup anchoring in `tool_executor._remember_place_focus()`.

### 1.6 Execution and data sources (current mapping)

| User need (conceptual) | Typical tool today | Backend / data |
|------------------------|-------------------|----------------|
| A→B route on map | `cspe_compute_route` | Local graph (`transport_engine.compute_route`) + shell sync |
| Stop search | `cspe_search_stops` | Local graph search |
| Station info / hours / access | `cspe_lookup_place_online` | Local resolve + IDFM enrichment (`idfm_station_enrichment`, `idfm_service_hours`) + optional SerpAPI for POI |
| Nearby POIs on map | `cspe_nearby_pois`, `cspe_explore_area` | Local POI index + shell sync |
| Nearby stops | `cspe_nearby_stops` | Local graph + shell sync |
| 3D graph | `cspe_open_graph3d` | Graph3D session + GraphXR |
| Web / hotels | `web_search` | SerpAPI |
| Memory | `memory_*`, `product_memory_*` | Atlas memory / SQLite |
| Music | `music` | Spotify via Product Shell |

### 1.7 Current pain points (observed from architecture, not a critique)

1. **Dual responsibility:** OpenAI picks tools; Python rewrites tools — logic split across registry prompts, shortcuts, place_info, exploration, validator.
2. **Overlapping domains:** `planner_domains._DOMAIN_PATTERNS` mixes transport, POI, and place-info phrases under `"transport"`.
3. **UI sync is implicit:** `sync_ui` is a tool arg default; exploration routing forces it; place lookup never syncs — behavior depends on which rewrite ran.
4. **Three parallel “routers”:** shortcuts, place_info, exploration — no single intent schema.
5. **Clarify vs guess:** Planner can return `clarify`; product preference is to guess prudently and state assumptions in the answer.

---

## 2. Proposed Target Architecture

### 2.1 High-level diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         User utterance + context                       │
│   (text/voice, agent_store world, router_context, conversation_focus)  │
└───────────────────────────────────┬─────────────────────────────────────┘
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│              OpenAI Intent Extractor (Chat Completions)                  │
│   Output: StructuredIntent JSON ONLY — no tool names                     │
│   { domain, intent, entities, ui_action, response_type, confidence? }  │
└───────────────────────────────────┬─────────────────────────────────────┘
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                    CentralIntentRouter (deterministic)                   │
│   • Validate schema + enum values                                        │
│   • Merge conversation_focus into entities                               │
│   • Apply global rules (POI≠station, IDFM≠routing, ui_action gates)    │
│   • Select domain router                                                 │
│   • Log: intent_raw → intent_normalized                                │
└───────────────────────────────────┬─────────────────────────────────────┘
                                    ▼
        ┌───────────┬───────────┬───────────┬───────────┬───────────┐
        ▼           ▼           ▼           ▼           ▼           ▼
   Transport    POI        MapUI      Visual3D    Memory      Web/General
   Router       Router     Router     Router      Router      Router
        │           │           │           │           │           │
        └───────────┴───────────┴───────────┴───────────┴───────────┘
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│              ExecutionPlan (internal, not exposed to OpenAI)             │
│   steps: [{ handler, tool?, endpoint?, args, data_sources[], ui? }]   │
└───────────────────────────────────┬─────────────────────────────────────┘
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│   Existing layers (initially via adapters):                              │
│   tool_executor.execute_tool()  OR  direct backend service calls         │
│   Product Shell: transport_engine, transport_exploration, agent_tools,   │
│                   idfm_*, shell enqueue                                   │
└───────────────────────────────────┬─────────────────────────────────────┘
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│   ResponseComposer → injection_block for Realtime + structured metadata  │
│   (text, optional ui_applied flag, data_sources_used)                    │
└─────────────────────────────────────────────────────────────────────────┘
```

### 2.2 Design principles

| Principle | Implication |
|-----------|-------------|
| OpenAI understands intent | Rich entities, topic, implicit follow-ups; uses context block |
| OpenAI does not choose tools | Prompt forbids `cspe_*`, `memory_*`, tool registry |
| Strict mapping by default | Each `(domain, intent)` → one primary execution template |
| Small adaptations same domain | e.g. `station_hours` vs `station_departures` share transport router, different IDFM calls |
| Progressive migration | Adapters map ExecutionPlan → existing tools; registry stays until Phase 3 |
| Ambiguity → best guess | Central router picks highest-probability intent; ResponseComposer adds explicit caveat |
| POI ≠ station | Separate domains and routers; never route POI questions to IDFM station enrichment |
| Local graph = topology truth | Routes, stops, paths, map structure always from bundle/POI index |
| IDFM = station enrichment only | Accessibility, disruptions, departures, service times for **resolved local stops** |
| SerpAPI = web POI + general web | Not for metro station existence or graph routing |

### 2.3 Structured intent target format

This is the **contract** between OpenAI and the CentralIntentRouter:

```json
{
  "domain": "transport | poi | map_ui | visual_3d | music | memory | web | general_chat",
  "intent": "route | station_info | station_accessibility | station_departures | station_hours | station_search | nearby_stops | poi_search | explore_area | map_action | visual_action | music_action | memory_action | web_search | general_chat",
  "entities": {
    "station": null,
    "origin": null,
    "destination": null,
    "line": null,
    "mode": null,
    "poi_category": null,
    "place": null
  },
  "ui_action": false,
  "response_type": "text | ui | text_and_ui"
}
```

**Optional extensions (same migration, additive):**

| Field | Purpose |
|-------|---------|
| `confidence` | 0–1; central router threshold for tie-breaking |
| `assumptions` | string[] — OpenAI states what it inferred (“assuming République metro station”) |
| `follow_up` | boolean — entity inheritance from focus expected |
| `radius_m` | number — exploration radius when stated |

**Validation:** CentralIntentRouter rejects invalid enums and applies defaults (e.g. missing `response_type` → infer from `ui_action`).

---

## 3. Layer Responsibilities

### 3.1 OpenAI intent extraction

**Location (proposed):** new module e.g. `src/work/atlas/src/atlas_client/router/intent_extractor.py`  
**Called from:** `agent_planner.run_planner_turn()` **instead of** `_plan_next_step_openai()` returning tool steps (Phase 2+).

| Responsibility | Detail |
|----------------|--------|
| Input | User text, `format_router_context_summary()`, `resolve_conversation_focus()` summary, last turn topic |
| Output | Single `StructuredIntent` JSON object |
| Must NOT | Emit tool names, registry args, or shell command specs |
| Must | Fill entities from explicit text or inherit from focus when follow-up |
| Must | Set `ui_action` from visual verbs (see §6) |
| Must | Set `domain=p poi` for restaurants/shops near a station; `domain=transport` for station attributes |
| Model | Same as today: `ATLAS_PLANNER_MODEL` / `gpt-4o`; temperature 0; JSON mode |

**Fallback:** If JSON invalid after retry, CentralIntentRouter uses regex classifiers migrated from `planner_place_info`, `planner_exploration`, `planner_domains` (deterministic shadow).

### 3.2 CentralIntentRouter

**Location (proposed):** `src/work/atlas/src/atlas_client/router/central_intent_router.py`

| Responsibility | Detail |
|----------------|--------|
| Validate | Schema, required entities per intent |
| Enrich entities | Merge `conversation_focus` when `follow_up` or entity null |
| Global rules | Data-source rules (§5), UI rules (§6), POI/station separation |
| Disambiguation | If ambiguous, pick most probable; attach `assumptions` to plan metadata |
| Route | `domain` → domain router function |
| Output | `RoutingDecision { normalized_intent, execution_plan, clarify?: never default }` |

**Does NOT:** Call HTTP, enqueue shell, or speak to user.

### 3.3 Domain routers

Each router is **deterministic** Python: `(StructuredIntent, agent_context) → ExecutionPlan`.

| Router | File (proposed) | Intents handled |
|--------|-----------------|-----------------|
| **TransportRouter** | `domain_routers/transport.py` | `route`, `station_info`, `station_accessibility`, `station_departures`, `station_hours`, `station_search`, `nearby_stops` |
| **PoiRouter** | `domain_routers/poi.py` | `poi_search`, `explore_area` |
| **MapUiRouter** | `domain_routers/map_ui.py` | `map_action` (refresh, clear, highlight, set mode, transport options) |
| **Visual3dRouter** | `domain_routers/visual_3d.py` | `visual_action` (open 3D, GraphXR sync) |
| **MemoryRouter** | `domain_routers/memory.py` | `memory_action` (add/search/update/delete — maps to existing memory tools) |
| **MusicRouter** | `domain_routers/music.py` | `music_action` |
| **WebRouter** | `domain_routers/web.py` | `web_search` |
| **GeneralChatRouter** | `domain_routers/general_chat.py` | `general_chat` — no tools; direct Realtime answer |

**Adaptation within domain:** Allowed. Example: TransportRouter chooses IDFM departures vs hours API based on `intent` sub-type without changing domain.

### 3.4 Tool executor (execution layer)

**Existing file:** `tool_executor.py` — **keep** during migration.

| Responsibility | Detail |
|----------------|--------|
| Phase 1–2 | Receives same tool names from ExecutionPlan adapter |
| Phase 3+ | Optional: thin handlers callable directly; tools become internal |
| Unchanged | Product Shell HTTP, shell enqueue, SerpAPI, memory clients |
| Side effects | `_remember_place_focus`, `_patch_shell_transport` — called from domain routers or executor consistently |

### 3.5 Backend services (Product Shell)

**Existing paths — remain source of execution:**

| Service | File | Used by intents |
|---------|------|-----------------|
| Route compute | `transport_engine.compute_route`, `agent_tools.compute_route_from_queries` | `route` |
| Stop search | `transport_engine.search_stops` | `station_search` |
| Exploration | `transport_exploration.nearby_*`, `explore_area` | `nearby_stops`, `poi_search`, `explore_area` |
| Place lookup | `agent_tools.lookup_place_for_chat` | `station_*` info intents (text) |
| IDFM | `idfm_station_enrichment`, `idfm_service_hours`, `idfm_client` | `station_accessibility`, `station_departures`, `station_hours`, disruptions |
| Shell sync | `agent_tools.shell_commands_for_route/exploration`, `shell.enqueue_commands` | `ui_action` / `response_type` with UI |
| Graph3D | `transport_engine.create_graph3d_session` | `visual_action` |
| Memory / Spotify | `routers/memory.py`, `routers/spotify.py` | `memory_action`, `music_action` |

Domain routers **select** which service chain runs; they do not duplicate graph/IDFM logic.

### 3.6 Final response generation

**Existing:** `agent_planner` builds `injection_block`; orchestrator sends to Realtime; `normalize_atlas_ui()` for chat UI.

**Proposed addition — ResponseComposer:**

| Input | Execution results + `normalized_intent` + `data_sources_used[]` |
| Output | `injection_block` text + optional structured footer (“Shown on map”, “Based on local timetable data…”) |
| Policy | Info-only intents: lead with facts, no UI mention unless `ui_action` |
| Policy | Ambiguous resolution: one sentence stating assumption |

Realtime model remains **answer-only** (no tool calls from model) — same as today.

---

## 4. Proposed Intent Catalog and Execution Triggers

### 4.1 Intent → execution mapping

| Intent | Domain | Primary execution | `ui_action` default | `response_type` default |
|--------|--------|-------------------|---------------------|-------------------------|
| `route` | transport | Resolve origin/destination → `compute_route_from_queries` → shell if UI | true if visual verbs else false | `text_and_ui` or `text` |
| `station_search` | transport | `search_stops` → optional map focus if UI | true if “show/find on map” | per UI rule |
| `station_info` | transport | `lookup_place_for_chat` topic=about/history | false | `text` |
| `station_accessibility` | transport | `lookup_place_for_chat` topic=accessibility → IDFM referential | false | `text` |
| `station_departures` | transport | Local resolve station → IDFM departures / stop_schedules | false | `text` |
| `station_hours` | transport | Local resolve station → IDFM service hours (not POI SerpAPI) | false | `text` |
| `nearby_stops` | transport | `nearby_stops` API; shell if UI | from `ui_action` | `text_and_ui` or `text` |
| `poi_search` | poi | `nearby_pois` with category; shell if UI | from `ui_action` | `text_and_ui` or `text` |
| `explore_area` | poi | `explore_area` (stops+POIs or POI-only variant); shell if UI | true if explore/show map | `text_and_ui` |
| `map_action` | map_ui | `cspe_transport_action` / shell kinds (refresh, clear, mode) | true | `ui` |
| `visual_action` | visual_3d | `cspe_open_graph3d` or session + GraphXR | true | `ui` or `text_and_ui` |
| `memory_action` | memory | `memory_*` / `product_memory_*` per sub-action | false | `text` |
| `music_action` | music | `music` tool | false | `text` |
| `web_search` | web | `web_search` (SerpAPI) | false | `text` |
| `general_chat` | general_chat | No execution; Realtime direct | false | `text` |

### 4.2 Sub-action inference (within `memory_action`, `map_action`, etc.)

Central router or domain router maps entity cues to existing tool args:

| Cue in entities / text | Sub-action |
|------------------------|------------|
| `memory_action` + “remind” | `memory_add` tags=reminder |
| `memory_action` + “what do I have saved” | `memory_search` |
| `map_action` + “clear route” | shell `run: reset_route` |
| `visual_action` + “3d” | `cspe_open_graph3d` |

Strict mapping tables live in domain routers (config or Python dict), not in OpenAI prompt.

### 4.3 Legacy tool mapping (migration adapter)

For Phase 1–2, ExecutionPlan steps can emit today’s tools:

| Intent | Adapter tool(s) |
|--------|-----------------|
| `route` | `cspe_compute_route` |
| `station_search` | `cspe_search_stops` (+ optional `cspe_transport_action` search_map) |
| `station_*` info | `cspe_lookup_place_online` with topic/kind |
| `nearby_stops` | `cspe_nearby_stops` |
| `poi_search` | `cspe_nearby_pois` |
| `explore_area` | `cspe_explore_area` |
| `map_action` | `cspe_transport_action` / `cspe_update_map` |
| `visual_action` | `cspe_open_graph3d` |
| `memory_action` | existing memory tools |
| `music_action` | `music` |
| `web_search` | `web_search` |

---

## 5. Data Source Selection Rules per Intent

| Intent | Local graph | Local POI index | IDFM/PRIM | SerpAPI/web |
|--------|-------------|-----------------|-----------|-------------|
| `route` | **Yes** — path, legs, topology | No | No | No |
| `station_search` | **Yes** — stop/station match | No | No | No |
| `station_info` | **Yes** — resolve station | No | Optional — lines, basic enrichment | No for stations |
| `station_accessibility` | **Yes** — resolve stop ID | No | **Yes** — referential + Navitia | No |
| `station_departures` | **Yes** — resolve stop area | No | **Yes** — departures, stop_schedules | No |
| `station_hours` | **Yes** — resolve station | No | **Yes** — service operating hours | **No** — not POI hours |
| `nearby_stops` | **Yes** — stops in radius | No | No | No |
| `poi_search` | **Yes** — center resolve only | **Yes** — POI rows | No | No |
| `explore_area` | **Yes** — stops if included | **Yes** — POIs | No | No |
| `map_action` | Indirect — map state | No | No | No |
| `visual_action` | **Yes** — session graph payload | No | No | No |
| `web_search` | No | No | No | **Yes** |
| POI hours/reviews (entity `place` + category) | Center anchor only | Resolve POI name | No | **Yes** — via lookup_place POI path |
| `general_chat` | No | No | No | No |

**Hard rules for CentralIntentRouter:**

1. Never call IDFM to **create** a route or prove a stop exists — only enrich after local `resolve_stop_query` / `resolve_exploration_center` success.
2. Never use SerpAPI for “is République accessible” or “route to Nation”.
3. `station_hours` with a **named metro station** → transport domain + IDFM; “hours of restaurant near X” → poi domain + web (existing `kind=poi` behavior in `lookup_place_for_chat`).
4. If local resolve fails, execution returns structured “not found in local graph” — do not fall through to web for station names.

---

## 6. UI Action Rules

### 6.1 When `ui_action` should be true

Set by intent extractor when user text contains **visual/map verbs** (non-exhaustive list aligned with current `planner_exploration` patterns):

- show, display, open, zoom, highlight, visualize, explore (on map), map, plot, pin, center on

**Examples:** “**show** POIs around République” → `ui_action: true`, `response_type: text_and_ui`.  
“**list** restaurants near République” (no map verb) → default `ui_action: false` unless user habitually expects map — central router may still set UI for `explore_area` when `response_type` explicitly `text_and_ui` from OpenAI.

### 6.2 When `ui_action` must be false

- Pure info: accessibility, departures, hours, about, history, disruptions, reviews (unless user also says “show on map”)
- Memory, music, web search without map mention
- `general_chat`

### 6.3 `response_type` derivation

| Condition | `response_type` |
|-----------|-----------------|
| `ui_action` false | `text` |
| `ui_action` true, user wants explanation too | `text_and_ui` |
| Pure UI command (“clear the map”, “open 3D view”) | `ui` (composer may still add brief confirmation text) |

### 6.4 Shell sync flag

ExecutionPlan sets `sync_ui: true` on Product Shell calls **only when** `response_type` is `ui` or `text_and_ui`. Matches current `shell_commands_for_exploration` / `shell_commands_for_route` behavior.

### 6.5 View constraints (existing frontend behavior)

Document for router metadata: geographic/network_3d map overlays require `transportViz` in map mode; Graph3D uses separate iframe. MapUiRouter should not assume POI markers appear in graph3d viz — rail list may still update.

---

## 7. Routing Examples (Target Behavior)

### 7.1 “route from République to Nation”

```json
{
  "domain": "transport",
  "intent": "route",
  "entities": { "origin": "République", "destination": "Nation", "mode": "metro" },
  "ui_action": true,
  "response_type": "text_and_ui"
}
```

**Flow:** TransportRouter → `compute_route_from_queries` → local graph path → shell route view. **Data:** local graph only.

### 7.2 “is République accessible?”

```json
{
  "domain": "transport",
  "intent": "station_accessibility",
  "entities": { "station": "République" },
  "ui_action": false,
  "response_type": "text"
}
```

**Flow:** TransportRouter → `lookup_place_for_chat` topic=accessibility → IDFM referential. **No shell enqueue.**

### 7.3 “next departures for République line 11”

```json
{
  "domain": "transport",
  "intent": "station_departures",
  "entities": { "station": "République", "line": "11" },
  "ui_action": false,
  "response_type": "text"
}
```

**Flow:** Local resolve → IDFM departures filtered by line context. **Not** SerpAPI.

### 7.4 “working hours of République”

```json
{
  "domain": "transport",
  "intent": "station_hours",
  "entities": { "station": "République" },
  "ui_action": false,
  "response_type": "text"
}
```

**Flow:** Local resolve → `idfm_service_hours` (service operating hours). Explicit answer if station building hours unavailable vs service times.

### 7.5 “show me POIs around République”

```json
{
  "domain": "poi",
  "intent": "poi_search",
  "entities": { "station": "République", "poi_category": "all" },
  "ui_action": true,
  "response_type": "text_and_ui"
}
```

**Flow:** PoiRouter → `nearby_pois` + shell exploration commands. **Data:** local POI index; center from local graph.

### 7.6 “restaurants near République”

```json
{
  "domain": "poi",
  "intent": "poi_search",
  "entities": { "station": "République", "poi_category": "restaurant" },
  "ui_action": false,
  "response_type": "text"
}
```

**Flow:** Same as 7.5 but **no shell** unless user asked to show on map. Returns POI list in text; optional prudent note: “I can show these on the map if you’d like.”

### 7.7 “open 3D graph”

```json
{
  "domain": "visual_3d",
  "intent": "visual_action",
  "entities": { "mode": "metro" },
  "ui_action": true,
  "response_type": "ui"
}
```

**Flow:** Visual3dRouter → `cspe_open_graph3d` → GraphXR session + shell sync.

### 7.8 “search the web for nearby hotels”

```json
{
  "domain": "web",
  "intent": "web_search",
  "entities": { "place": "near current area or stated place" },
  "ui_action": false,
  "response_type": "text"
}
```

**Flow:** WebRouter → SerpAPI. **Not** local POI index (user explicitly asked web). If no place anchor, inherit from exploration focus or state assumption in answer.

---

## 8. Progressive Migration Plan

### Phase 0 — Foundation (low risk, no behavior change)

| Action | Detail |
|--------|--------|
| **Keep** | All 38 registry tools, `tool_executor`, Product Shell endpoints, shell command protocol |
| **Add** | Structured intent schema types, logging structs, shadow mode |
| **Centralize** | Document intent mapping table (this plan) as code-adjacent spec |
| **Implement** | `IntentExtractor` called **in parallel** with existing planner; log diff only |

**Success criteria:** Shadow intent matches executed tool ≥90% on existing test suites (`test_planner_place_info`, `test_planner_exploration`, `test_transport_exploration`).

### Phase 1 — Central router behind adapter (medium risk)

| Action | Detail |
|--------|--------|
| **Keep** | `run_planner_turn` loop, `execute_tool`, injection pipeline |
| **Replace** | OpenAI tool-plan output → intent JSON → CentralIntentRouter → **ToolPlanAdapter** → same `PlanStepSpec` list |
| **Centralize** | Merge `planner_place_info`, `planner_exploration`, `planner_shortcuts` logic into domain routers + central rules |
| **Keep as fallback** | `try_planner_shortcut` for session_sleep, shutdown, reset map (deterministic, no LLM) |
| **Deprecate later** | Direct tool selection in `_PLANNER_SYSTEM` prompt |

**Feature flag:** `ATLAS_INTENT_ROUTER=1` (default off initially).

**Avoid breaks:** Adapter produces identical tool+args as current enrichers for golden tests.

### Phase 2 — Domain routers own data-source and UI flags (medium risk)

| Action | Detail |
|--------|--------|
| **Move** | `sync_ui` decisions from validator/exploration modules into PoiRouter/TransportRouter from `ui_action` |
| **Move** | IDFM topic selection from `planner_place_info._resolve_place_kind` into TransportRouter |
| **Keep** | `cspe_lookup_place_online` as executor entry for station text intents |
| **Reduce** | `validate_step_semantics` to schema-only; domain rules live in routers |
| **Clarify policy** | Default to guess + explicit assumption; remove `clarify` except missing **critical** entity (e.g. route with no destination) |

### Phase 3 — Optional executor slimming (higher risk, later)

| Action | Detail |
|--------|--------|
| **Deprecate** | OpenAI-facing tool catalog in planner (`build_router_catalog` for planning) |
| **Keep** | Registry for documentation / stress tests until removed |
| **Optional** | Domain routers call Product Shell Python services directly from Atlas (duplicate HTTP removal) — **only if** Product Shell exposes stable internal API |
| **Keep** | Shell enqueue protocol unchanged for frontend |

### Phase 4 — Cleanup (low urgency)

| Deprecate | Replacement |
|-----------|---------------|
| `planner_place_info.py` routing | TransportRouter + PoiRouter |
| `planner_exploration.py` routing | PoiRouter |
| Tool-based OpenAI planner prompt | Intent extractor prompt |
| `semantic_router` tool mode | Intent extractor + central router (when `ATLAS_AGENT_PLANNER=0`, use local intent classifier) |

### What to keep indefinitely (stable contracts)

- `tools_registry.json` until Phase 3 completes (executor contract)
- Product Shell `/api/agent/context`, `/api/shell/enqueue`, transport exploration endpoints
- `conversation_focus` concept (fed into CentralIntentRouter entity merge)
- Realtime answer-only orchestrator pattern
- Frontend `ShellCommandListener` command kinds

---

## 9. Logging and Debugging Plan

### 9.1 Log events (structured, one line per turn in compact log)

| Event | Fields | File hook |
|-------|--------|-----------|
| `intent.raw` | user_text, correlation_id, model | intent_extractor |
| `intent.parsed` | full StructuredIntent JSON | central_intent_router |
| `intent.normalized` | after focus merge + rules | central_intent_router |
| `router.domain` | domain, intent, router_name | central_intent_router |
| `router.assumptions` | string[] | central_intent_router |
| `plan.execution` | steps summary, tools[], sync_ui | domain router → adapter |
| `plan.data_sources` | `["local_graph","idfm","poi_index","serpapi","shell_ui"]` | per step |
| `plan.ui` | ui_action, response_type, shell_enqueued_count | after executor |
| `plan.result` | ok, error, summary_len | tool_executor receipt |

Use existing `log_compact_line`, `log_turn_planner`, `log_turn_tool` in `src/core/project_logs.py` with new category e.g. `CAT_INTENT`.

### 9.2 Correlation ID propagation

Continue `split_correlation_id` / `correlation_id` through intent → plan → executor → Product Shell compact logs (`[PlaceLookup]`, `[Chat] shell_enqueued_delta`).

### 9.3 Debug surfaces

| Surface | Purpose |
|---------|---------|
| `GET /api/agent/events` | Browser/agent events (extend with `intent.normalized`) |
| Planner live logs | `[Planner]` lines include `intent=` not only `tool=` |
| Shadow diff metric | `intent_shadow_mismatch` when Phase 0 compares to legacy tool |
| Test fixtures | JSON files: utterance → expected intent → expected data_sources |

### 9.4 Answering “which backend was used?”

Every turn log line should end with:

```
sources=local_graph,idfm,shell_ui intent=station_accessibility domain=transport
```

**Derivation:**

| Source | Set when |
|--------|----------|
| `local_graph` | Any call to transport_engine, queries, exploration center resolve |
| `poi_index` | nearby_pois / explore_area POI leg |
| `idfm` | idfm_client or enrichment modules invoked |
| `serpapi` | web_search or POI lookup web merge |
| `shell_ui` | enqueue_commands count > 0 |
| `graph3d` | graph3d session created |
| `memory_sqlite` | product_memory_* |
| `atlas_memory` | memory_* tools |

Expose aggregated `data_sources_used` in agent context patch after turn (optional, for UI debug panel later).

### 9.5 Regression strategy

1. Extend `tests/test_planner_*.py` with intent-level assertions (domain, intent, ui_action).
2. Keep tool-level integration tests until Phase 3.
3. Record golden logs from `scripts/test_live_planner_stress.py` comparing intent shadow vs legacy.

---

## 10. Module Placement Summary (Proposed)

| New / moved module | Path under `src/work/atlas/src/atlas_client/router/` |
|--------------------|------------------------------------------------------|
| Intent schema | `intent_schema.py` |
| OpenAI extractor | `intent_extractor.py` |
| Central router | `central_intent_router.py` |
| Response composer | `response_composer.py` |
| Tool plan adapter | `tool_plan_adapter.py` |
| Transport domain | `domain_routers/transport.py` |
| POI domain | `domain_routers/poi.py` |
| Map UI domain | `domain_routers/map_ui.py` |
| Visual 3D domain | `domain_routers/visual_3d.py` |
| Memory domain | `domain_routers/memory.py` |
| Music domain | `domain_routers/music.py` |
| Web domain | `domain_routers/web.py` |
| General chat | `domain_routers/general_chat.py` |

**Orchestrator integration point:** `agent_planner.run_planner_turn()` — replace `resolve_planner_plan()` tool path with intent path when flag enabled.

**Product Shell:** No required changes for Phase 0–2; optional `POST /api/agent/routing/log` only if centralized server-side logging is desired later.

---

## 11. Open Questions (Mark for implementation time)

| Item | Status |
|------|--------|
| Azure TTS / voice-specific intent cues | Not inspected; treat same as text intent |
| Multi-step composite utterances (“route X→Y then show POIs”) | Central router may emit **ordered** ExecutionPlan steps; same as current multi-step planner |
| `cspe_show_station_or_line_info` | Map to `station_info` or deprecate in favor of lookup |
| Local planner (Ollama) without OpenAI | Phase 2: smaller model for intent JSON or rule-only fallback |

---

*Plan based on codebase inspection as of repository state including: `planner_pipeline.py`, `agent_planner.py`, `local_planner.py`, `planner_place_info.py`, `planner_exploration.py`, `planner_shortcuts.py`, `planner_validator.py`, `planner_domains.py`, `conversation_focus.py`, `tool_executor.py`, `orchestrator.py`, `agent_tools.py`, `transport_exploration.py`, and IDFM service modules.*
