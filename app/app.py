import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import os
from contextlib import contextmanager

import streamlit as st
import streamlit.components.v1 as components
from streamlit_searchbox import st_searchbox

from src.core.cache_bundle import load_or_build_graph_bundle
from src.core.debug_log import debug_log_path, get_debug_logger, log_event
from src.core.poi_index import load_poi_lookup
from src.core.queries import component_info, search_stops_autocomplete, shortest_path
from src.core.tools import top_hubs
from src.viz.plot_mapbox import (
    DEFAULT_MAPBOX_BASEMAP_STYLE,
    load_line_geometries,
    load_render_graph,
    normalize_mapbox_style_url,
    render_mapbox_gl_html,
)

import ui_shell

st.set_page_config(page_title="CSPE", layout="wide")
ui_shell.init_shell_session_state()


def _repo_rel(*parts: str) -> str:
    """Absolute path under repo root (Streamlit cwd may not be the repo root)."""
    return str(ROOT.joinpath(*parts))


PROJECT_ROOT = str(ROOT)
BUNDLE_PATH = _repo_rel("data", "derived", "routing", "graph_bundle.pkl")
STOP_POPUP_INDEX_PATH = _repo_rel("data", "derived", "stops", "stop_popup_index.parquet")
NETWORK_MAPS_DIR = _repo_rel("data", "derived", "maps")
POI_DATA_PATH = _repo_rel("data", "normalized", "poi", "poi.parquet")
POI_TREE_PATH = _repo_rel("data", "derived", "indexes", "poi_balltree.pkl")
POI_NPZ_PATH = _repo_rel("data", "derived", "indexes", "poi_balltree.npz")
RENDER_GRAPH_PATHS = {
    "all": _repo_rel("data", "derived", "render_graphs", "all.render_graph.json"),
    "bus": _repo_rel("data", "derived", "render_graphs", "bus.render_graph.json"),
    "metro": _repo_rel("data", "derived", "render_graphs", "metro.render_graph.json"),
    "rail": _repo_rel("data", "derived", "render_graphs", "rail.render_graph.json"),
    "tram": _repo_rel("data", "derived", "render_graphs", "tram.render_graph.json"),
}
MAPBOX_ENV_VARS = ("MAPBOX_TOKEN", "MAPBOX_API_KEY", "MAPBOX_ACCESS_TOKEN")

# --- Mapbox token (pick one) ---
# 1) Easiest for local dev: set your public token string here (leave None to use env only).
#    Do not commit real tokens to git; use env vars or .env for shared repos.
MAPBOX_ACCESS_TOKEN_INLINE: str | None = None
# 2) Or set an environment variable (any one of):
#    MAPBOX_TOKEN, MAPBOX_API_KEY, MAPBOX_ACCESS_TOKEN
#    On Streamlit Cloud: App settings → Secrets, e.g. MAPBOX_TOKEN = "pk...."

# Optional: MAPBOX_STYLE_URL=https://api.mapbox.com/styles/v1/USER/ID or mapbox://styles/USER/ID (overrides default).
DEFAULT_MAPBOX_STYLE = normalize_mapbox_style_url(
    os.getenv("MAPBOX_STYLE_URL", "").strip() or DEFAULT_MAPBOX_BASEMAP_STYLE
)

# Self-contained canvas orb (Streamlit markdown strips script; use components.html).
_NEURAL_ORB_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <style>
    html, body { margin: 0; padding: 0; background: transparent; overflow: hidden; }
    #orb-root {
      display: flex; justify-content: center; align-items: center;
      width: 100%;
      padding: 2.5rem 0.4rem 0.4rem 0.4rem;
      margin: 0;
      box-sizing: border-box;
      line-height: 0;
    }
    canvas { display: block; width: 320px; height: 320px; max-width: 100%; margin: 0; vertical-align: top; }
  </style>
</head>
<body>
  <div id="orb-root"><canvas id="orb-canvas" width="320" height="320" aria-hidden="true"></canvas></div>
  <script>
(function () {
  const canvas = document.getElementById("orb-canvas");
  const ctx = canvas.getContext("2d");
  const W = 320, H = 320, cx = W / 2, cy = H / 2, R2D = 144;
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  canvas.width = W * dpr;
  canvas.height = H * dpr;
  ctx.scale(dpr, dpr);

  const N = 220;
  const GOLDEN = Math.PI * (3 - Math.sqrt(5));
  const nodes = [];
  for (let i = 0; i < N; i++) {
    const y = 1 - (i / Math.max(1, N - 1)) * 2;
    const r = Math.sqrt(Math.max(0, 1 - y * y));
    const theta = GOLDEN * i;
    nodes.push({
      bx: Math.cos(theta) * r,
      by: y,
      bz: Math.sin(theta) * r,
      ph1: (i * 1.618 + 0.2) % (Math.PI * 2),
      ph2: (i * 0.927 + 1.1) % (Math.PI * 2),
      ph3: (i * 0.513 + 2.2) % (Math.PI * 2),
    });
  }

  const wDrift = 0.00038;
  const wRotY = 0.00011;
  const wRotX = 0.000075;
  const wFloat = 0.00022;
  const wPulse = 0.0019;
  const wProx = 0.00032;
  const NEIGH_CAP = 6;

  function rotY(x, y, z, a) {
    const c = Math.cos(a), s = Math.sin(a);
    return { x: c * x + s * z, y, z: -s * x + c * z };
  }
  function rotX(x, y, z, a) {
    const c = Math.cos(a), s = Math.sin(a);
    return { x, y: c * y - s * z, z: s * y + c * z };
  }
  function proj(x, y, z, fl, oy) {
    const zz = z + fl;
    const sc = fl / Math.max(0.35, zz);
    return {
      x: cx + x * sc * R2D,
      y: cy - y * sc * R2D + oy,
      z: z,
      sc: sc,
    };
  }
  function len3(x, y, z) { return Math.sqrt(x * x + y * y + z * z); }
  function dist3(px, py, pz, i, j) {
    const dx = px[i] - px[j], dy = py[i] - py[j], dz = pz[i] - pz[j];
    return Math.sqrt(dx * dx + dy * dy + dz * dz);
  }

  const edgeAlpha = new Map();
  function edgeKey(i, j) { return i < j ? i + "," + j : j + "," + i; }
  function linkOmitted(i, j) {
    const a = i < j ? i : j, b = i < j ? j : i;
    return ((a * 48271 + b * 65521) >>> 0) % 100 < 20;
  }

  let t0 = performance.now();
  function frame(now) {
    const t = now - t0;
    const rotA = t * wRotY;
    const rotB = t * wRotX;
    const floatY = 3.52 * Math.sin(t * wFloat);
    const pulse = 0.86 + 0.14 * Math.sin(t * wPulse);
    const dCut = 0.5 + 0.12 * Math.sin(t * wProx);
    const dCutLo = dCut * 0.88;

    const px = [], py = [], pz = [];
    for (let i = 0; i < N; i++) {
      const n = nodes[i];
      let x = n.bx + 0.038 * Math.sin(t * wDrift + n.ph1);
      let y = n.by + 0.038 * Math.sin(t * wDrift * 1.07 + n.ph2);
      let z = n.bz + 0.038 * Math.sin(t * wDrift * 0.93 + n.ph3);
      const L = len3(x, y, z);
      const rad = 0.94 + 0.06 * Math.sin(t * wPulse * 0.7 + n.ph1);
      x = (x / L) * rad;
      y = (y / L) * rad;
      z = (z / L) * rad;
      let p = rotY(x, y, z, rotA);
      p = rotX(p.x, p.y, p.z, rotB);
      px[i] = p.x; py[i] = p.y; pz[i] = p.z;
    }

    const pairs = [];
    for (let i = 0; i < N; i++) {
      const near = [];
      for (let j = 0; j < N; j++) {
        if (i === j) continue;
        const d = dist3(px, py, pz, i, j);
        if (d < dCut) near.push({ j: j, d: d });
      }
      near.sort((a, b) => a.d - b.d);
      for (let k = 0; k < Math.min(NEIGH_CAP, near.length); k++) {
        const j = near[k].j;
        if (i < j) pairs.push([i, j, near[k].d]);
      }
    }

    const seen = new Set();
    const uniq = [];
    for (const [i, j, d] of pairs) {
      const k = edgeKey(i, j);
      if (seen.has(k)) continue;
      seen.add(k);
      uniq.push([i, j, d]);
    }

    const FL = 2.85;
    const P = [];
    for (let i = 0; i < N; i++) {
      P.push(proj(px[i], py[i], pz[i], FL, floatY));
    }

    ctx.clearRect(0, 0, W, H);
    ctx.save();
    ctx.beginPath();
    ctx.arc(cx, cy, R2D, 0, Math.PI * 2);
    ctx.clip();

    const lines = uniq.map(([i, j, d]) => ({
      i: i, j: j, d: d,
      zm: (P[i].z + P[j].z) * 0.5,
    })).sort((a, b) => a.zm - b.zm);

    for (const ln of lines) {
      const k = edgeKey(ln.i, ln.j);
      const on = ln.d < dCutLo ? 1 : (dCut - ln.d) / (dCut - dCutLo + 1e-6);
      const prev = edgeAlpha.get(k) || 0;
      const omit = linkOmitted(ln.i, ln.j);
      const target = omit ? 0 : Math.max(0, Math.min(1, on));
      const a = prev * 0.82 + target * 0.18;
      edgeAlpha.set(k, a);
      if (a < 0.02 || omit) continue;
      const al = a * (1 - ln.d / dCut) * 0.42 * pulse;
      ctx.strokeStyle = "rgba(255,255,255," + al.toFixed(3) + ")";
      ctx.lineWidth = 0.68;
      ctx.beginPath();
      ctx.moveTo(P[ln.i].x, P[ln.i].y);
      ctx.lineTo(P[ln.j].x, P[ln.j].y);
      ctx.stroke();
    }

    const order = P.map((p, idx) => ({ i: idx, z: p.z })).sort((a, b) => a.z - b.z);
    for (const o of order) {
      const p = P[o.i];
      const depth = (p.z + 1) * 0.5;
      const al = 0.35 + 0.65 * depth;
      const r = 1.76 + 1.6 * p.sc * 0.012;
      ctx.fillStyle = "rgba(255,255,255," + (al * pulse).toFixed(3) + ")";
      ctx.beginPath();
      ctx.arc(p.x, p.y, r, 0, Math.PI * 2);
      ctx.fill();
    }

    ctx.restore();
    ctx.beginPath();
    ctx.arc(cx, cy, R2D, 0, Math.PI * 2);
    ctx.strokeStyle = "rgba(255,255,255,0.14)";
    ctx.lineWidth = 0.8;
    ctx.stroke();

    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
})();
  </script>
</body>
</html>
"""
LOGGER = get_debug_logger("cspe.app")
log_event(LOGGER, "app_imported", log_file=str(debug_log_path()))


@st.cache_resource(show_spinner=True)
def load_bundle(project_root: str, bundle_path: str, stop_popup_index_path: str):
    log_event(LOGGER, "load_bundle_called", project_root=project_root, bundle_path=bundle_path, stop_popup_index_path=stop_popup_index_path)
    return load_or_build_graph_bundle(project_root, cache_path=bundle_path, stop_popup_index_path=stop_popup_index_path)


def _graph_data_download_url(*names: str) -> str | None:
    for name in names:
        v = os.getenv(name)
        if v and str(v).strip():
            return str(v).strip()
    try:
        for name in names:
            if name in st.secrets and st.secrets[name]:
                return str(st.secrets[name]).strip()
    except (TypeError, RuntimeError, AttributeError, FileNotFoundError):
        pass
    return None


def _download_url_to_file(url: str, dest: Path) -> None:
    from urllib.request import Request, urlopen

    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = Request(url, headers={"User-Agent": "CSPE-Streamlit/1.0"})
    with urlopen(req, timeout=600) as resp:
        body = resp.read()
    tmp.write_bytes(body)
    if dest.exists():
        dest.unlink()
    tmp.rename(dest)


def ensure_graph_bundle_inputs() -> None:
    """`data/` is gitignored; on Streamlit Cloud the pickle/parquet must exist or be downloaded."""
    bundle = Path(BUNDLE_PATH)
    popup = Path(STOP_POPUP_INDEX_PATH)
    if bundle.is_file() and popup.is_file():
        return
    bu_url = _graph_data_download_url("CSPE_GRAPH_BUNDLE_URL", "GRAPH_BUNDLE_URL")
    pop_url = _graph_data_download_url("CSPE_STOP_POPUP_INDEX_URL", "STOP_POPUP_INDEX_URL")
    try:
        if not bundle.is_file() and bu_url:
            log_event(LOGGER, "graph_bundle_download_start", dest=str(bundle))
            _download_url_to_file(bu_url, bundle)
            log_event(LOGGER, "graph_bundle_download_done", path=str(bundle))
        if not popup.is_file() and pop_url:
            log_event(LOGGER, "stop_popup_download_start", dest=str(popup))
            _download_url_to_file(pop_url, popup)
            log_event(LOGGER, "stop_popup_download_done", path=str(popup))
    except Exception as e:
        log_event(LOGGER, "graph_data_download_failed", error=str(e))
        st.error(
            f"Could not download graph data ({e}). "
            "Verify **CSPE_GRAPH_BUNDLE_URL** and **CSPE_STOP_POPUP_INDEX_URL** in Secrets (or env)."
        )
        st.stop()
    if not bundle.is_file() or not popup.is_file():
        st.error("Graph data files are missing — full setup steps are below.")
        st.markdown(
            f"""
The **`data/`** folder is not in the git repo, so Streamlit Cloud starts without these files.
The app looks for them at:

- **`graph_bundle.pkl`** → `{bundle}`
- **`stop_popup_index.parquet`** → `{popup}`

#### Streamlit Cloud

1. Upload both files to a host that serves **raw bytes over HTTPS** (e.g. S3/GCS public URL, GitHub Release asset, static file URL).  
   The URL should work in a browser or `curl` **without** an HTML login page.
2. In the Cloud UI: **Manage app** (lower right) → **Secrets** (or **Settings → Secrets**).
3. Paste **exactly** this shape (replace the URLs with yours):

```toml
CSPE_GRAPH_BUNDLE_URL = "https://example.com/path/graph_bundle.pkl"
CSPE_STOP_POPUP_INDEX_URL = "https://example.com/path/stop_popup_index.parquet"
```

4. **Save** secrets, then **Reboot** the app from the Cloud menu so the new values load.

#### Local

Create the parent folders if needed, then place the files so the paths above exist (same layout under your repo root).

---
*If secrets are set but files are still missing, the URLs may redirect to HTML — use direct file links only.*
"""
        )
        st.stop()


@st.cache_resource(show_spinner=False)
def load_line_geometries_cached(path: str):
    if not os.path.exists(path):
        log_event(LOGGER, "line_geometries_missing", path=path)
        return None
    log_event(LOGGER, "line_geometries_loading", path=path)
    return load_line_geometries(path)


@st.cache_resource(show_spinner=False)
def load_poi_lookup_cached(data_path: str, tree_path: str, npz_path: str):
    if not os.path.exists(data_path):
        log_event(LOGGER, "poi_data_missing", data_path=data_path)
        return None
    log_event(
        LOGGER,
        "poi_lookup_loading",
        data_path=data_path,
        tree_path=tree_path if os.path.exists(tree_path) else None,
        npz_path=npz_path if os.path.exists(npz_path) else None,
    )
    return load_poi_lookup(data_path, tree_path=tree_path if os.path.exists(tree_path) else None, npz_path=npz_path if os.path.exists(npz_path) else None)


@st.cache_resource(show_spinner=False)
def load_render_graph_cached(path: str):
    if not os.path.exists(path):
        log_event(LOGGER, "render_graph_missing", path=path)
        return None
    log_event(LOGGER, "render_graph_loading", path=path)
    return load_render_graph(path)


@st.cache_resource(show_spinner=False)
def load_render_graphs_cached(paths: dict[str, str]):
    graphs = {}
    for mode_name, path in paths.items():
        if os.path.exists(path):
            log_event(LOGGER, "render_graph_loading", mode=mode_name, path=path)
            graphs[mode_name] = load_render_graph(path)
        else:
            log_event(LOGGER, "render_graph_missing", mode=mode_name, path=path)
    return graphs


def get_mapbox_token():
    inline = (MAPBOX_ACCESS_TOKEN_INLINE or "").strip()
    if inline:
        log_event(LOGGER, "mapbox_token_found", env_name="MAPBOX_ACCESS_TOKEN_INLINE")
        return inline, "MAPBOX_ACCESS_TOKEN_INLINE"
    for env_name in MAPBOX_ENV_VARS:
        value = os.getenv(env_name)
        if value:
            log_event(LOGGER, "mapbox_token_found", env_name=env_name)
            return value, env_name
    try:
        for env_name in MAPBOX_ENV_VARS:
            if env_name in st.secrets:
                raw = st.secrets[env_name]
                if raw:
                    log_event(LOGGER, "mapbox_token_found", env_name=f"st.secrets.{env_name}")
                    return str(raw).strip(), f"st.secrets.{env_name}"
    except (TypeError, RuntimeError, AttributeError):
        pass
    log_event(LOGGER, "mapbox_token_missing", env_names="|".join(MAPBOX_ENV_VARS))
    return None, None


def _display_mode_name(mode: str) -> str:
    return {"metro": "Metro", "rail": "RER", "tram": "Tram", "bus": "Bus"}.get(mode, mode.title())


def _format_station_line(mode: str, label: str) -> str:
    text = str(label or "").strip()
    if mode == "metro" and text.lower().startswith("line "):
        return text[5:].strip()
    if mode == "rail":
        lowered = text.lower()
        if lowered.startswith("rer "):
            return text[4:].strip()
        if lowered.startswith("rail "):
            return text[5:].strip()
    if mode == "tram" and text.lower().startswith("tram "):
        return text[5:].strip()
    if mode == "bus" and text.lower().startswith("bus "):
        return text[4:].strip()
    return text


def station_lines_by_mode(attrs: dict) -> dict[str, list[str]]:
    lines = attrs.get("lines") or {}
    out = {}
    for transport_mode in ("metro", "rail", "tram", "bus"):
        values = []
        seen = set()
        for label in list(lines.get(transport_mode, [])):
            formatted = _format_station_line(transport_mode, label)
            if formatted and formatted not in seen:
                seen.add(formatted)
                values.append(formatted)
        if values:
            out[transport_mode] = values
    return out


def extract_selected_stop_id(selection_state):
    if selection_state is None:
        return None

    points = []
    try:
        points = selection_state.selection.points
    except Exception:
        try:
            points = selection_state.get("selection", {}).get("points", [])
        except Exception:
            points = []

    if not points:
        return None

    point = points[-1]
    customdata = point.get("customdata") if isinstance(point, dict) else getattr(point, "customdata", None)
    if isinstance(customdata, (list, tuple)) and customdata:
        return str(customdata[0])
    return None


def render_station_details(G, stop_id: str):
    if stop_id not in G:
        return

    attrs = G.nodes[stop_id]
    stop_name = attrs.get("stop_name", stop_id)
    degree = int(G.degree[stop_id])
    grouped_lines = station_lines_by_mode(attrs)
    mode_names = [_display_mode_name(mode) for mode in grouped_lines]
    all_lines = [line for mode in ("metro", "rail", "tram", "bus") for line in grouped_lines.get(mode, [])]

    with st.container(border=True):
        title_col, close_col = st.columns([6, 1])
        with title_col:
            st.markdown(f"### {stop_name}")
        with close_col:
            if st.button("Close", key=f"close_station_panel_{stop_id}", use_container_width=True):
                st.session_state["selected_map_stop"] = None
                st.rerun()

        st.write(f"**Modes:** {', '.join(mode_names) if mode_names else 'n/a'}")
        st.write(f"**Lines:** {', '.join(all_lines) if all_lines else 'n/a'}")
        st.write(f"**Connections:** {degree}")
        st.write(f"**Stop ID:** `{stop_id}`")

        for transport_mode in ("metro", "rail", "tram", "bus"):
            values = grouped_lines.get(transport_mode, [])
            if values:
                st.caption(f"{_display_mode_name(transport_mode)}: {', '.join(values)}")


st.markdown(
    """
    <style>
    @import url("https://fonts.googleapis.com/css2?family=Rajdhani:wght@500;600;700&display=swap");
    :root {
      --cspe-bg-deep: #050b18;
      --cspe-bg-surface: #070f1f;
      --cspe-bg-elevated: rgba(10, 18, 36, 0.78);
      --cspe-border: rgba(72, 210, 238, 0.22);
      --cspe-border-muted: rgba(72, 210, 238, 0.11);
      --cspe-border-hover: rgba(100, 230, 255, 0.38);
      --cspe-border-strong: rgba(100, 230, 255, 0.34);
      --cspe-text: rgba(232, 244, 255, 0.92);
      --cspe-text-muted: rgba(150, 180, 200, 0.58);
      --cspe-text-dim: rgba(130, 165, 188, 0.45);
      --cspe-accent-soft: rgba(72, 210, 238, 0.14);
      --cspe-accent-mid: rgba(72, 210, 238, 0.28);
      --cspe-radius: 4px;
      --cspe-space-xs: 0.2rem;
      --cspe-space-sm: 0.35rem;
      --cspe-space-md: 0.5rem;
      --cspe-space-lg: 0.75rem;
    }
    [data-testid="stAppViewContainer"] {
        background: var(--cspe-bg-deep) !important;
    }
    header[data-testid="stHeader"] {
        background: transparent !important;
        background-color: transparent !important;
    }
    [data-testid="stToolbar"] {
        background: transparent !important;
        background-color: transparent !important;
    }
    [data-testid="stDecoration"] {
        background: transparent !important;
        background-color: transparent !important;
    }
    .block-container {
        padding-top: 0 !important;
        padding-bottom: 0 !important;
        padding-left: 0 !important;
        padding-right: 0 !important;
        max-width: none;
    }
    section[data-testid="stSidebar"] {
        display: none !important;
    }
    div[data-testid="stHorizontalBlock"] {
        align-items: stretch;
        gap: 0 !important;
    }
    /* Map stack: overlays use position:absolute; % is relative to this box (not the viewport). */
    div[data-testid="stVerticalBlock"]:has(#map-zone-anchor) {
        position: relative !important;
        min-height: 100vh !important;
        height: 100vh !important;
        overflow: visible !important;
        gap: 0 !important;
        /* Tune overlay placement vs map panel (edit here; values are % of this block except min/max px). */
        --cspe-ctrl-top: 2.5%;
        --cspe-ctrl-left: 2%;
        /* ~30% smaller than prior 35% / 380px box → ×0.7 */
        --cspe-ctrl-width: 24.5%;
        --cspe-ctrl-min-w: 300px;
        --cspe-ctrl-max-w: 300px;
        --cspe-ctrl-min-h: 140px;
        --cspe-route-bottom: 2%;
        --cspe-route-inset: 2%;
    }
    div[data-testid="stVerticalBlock"] > div:has(> #map-zone-anchor) {
        height: 0 !important;
        margin: 0 !important;
    }
    #controls-portal {
        position: absolute !important;
        top: var(--cspe-ctrl-top) !important;
        left: var(--cspe-ctrl-left) !important;
        width: var(--cspe-ctrl-width) !important;
        min-width: var(--cspe-ctrl-min-w) !important;
        max-width: var(--cspe-ctrl-max-w) !important;
        height: auto !important;
        min-height: var(--cspe-ctrl-min-h) !important;
        max-height: none !important;
        z-index: 30 !important;
        pointer-events: auto !important;
        margin: 0 !important;
        padding: 0.35rem 0.53rem !important;
        box-sizing: border-box !important;
        overflow: visible !important;
        background: var(--cspe-bg-elevated) !important;
        border: 1px solid var(--cspe-border) !important;
        border-radius: var(--cspe-radius) !important;
        box-shadow: 0 0 0 1px var(--cspe-border-muted), 0 16px 48px rgba(0, 0, 0, 0.42) !important;
        backdrop-filter: blur(10px);
        container-type: inline-size;
        container-name: cspe-controls;
    }
    #controls-portal > div {
        width: 100%;
        pointer-events: auto;
        overflow: visible !important;
    }
    #controls-portal * {
        color: var(--cspe-text);
    }
    #controls-portal [data-testid="stVerticalBlock"] {
        gap: 0.25rem !important;
        overflow: visible !important;
        min-height: 0 !important;
    }
    #controls-portal p.cspe-overlay-title {
        font-family: "Rajdhani", "Segoe UI", sans-serif !important;
        font-size: 0.5rem !important;
        font-weight: 600 !important;
        line-height: 1.2 !important;
        margin: 0 0 0.14rem 0 !important;
        padding: 0 0 0.14rem 0 !important;
        border-bottom: 1px solid var(--cspe-border-muted) !important;
        color: var(--cspe-text-muted) !important;
        opacity: 1 !important;
        letter-spacing: 0.12em !important;
        text-transform: uppercase !important;
    }
    #controls-portal div[data-testid="stHorizontalBlock"] {
        gap: 0.25rem !important;
        flex-wrap: wrap !important;
        row-gap: 0.25rem !important;
    }
    #controls-portal [data-testid="column"] {
        min-width: 0 !important;
    }
    #controls-portal [data-testid="element-container"] {
        overflow: visible !important;
    }
    #controls-portal .stButton > button {
        padding: 0.098rem 0.175rem !important;
        font-size: 0.8rem !important;
        line-height: 1.2 !important;
        min-height: auto !important;
        height: auto !important;
        white-space: normal !important;
        word-break: break-word !important;
        border-radius: var(--cspe-radius) !important;
        font-weight: 600 !important;
        letter-spacing: 0.056em !important;
        text-transform: uppercase !important;
        background: transparent !important;
        border: 1px solid var(--cspe-border) !important;
        color: var(--cspe-text) !important;
        box-shadow: none !important;
    }
    #controls-portal .stButton > button * {
        font-size: inherit !important;
    }
    #controls-portal .stButton > button[kind="secondary"] {
        background: transparent !important;
        border-color: var(--cspe-border-muted) !important;
        color: var(--cspe-text-muted) !important;
    }
    #controls-portal .stButton > button[kind="primary"],
    #controls-portal .stButton > button[data-testid="baseButton-primary"] {
        background: var(--cspe-accent-soft) !important;
        background-image: none !important;
        color: var(--cspe-text) !important;
        border: 1px solid var(--cspe-border-strong) !important;
        box-shadow: none !important;
    }
    #controls-portal .stButton > button[kind="primary"]:hover,
    #controls-portal .stButton > button[kind="primary"]:focus-visible,
    #controls-portal .stButton > button[data-testid="baseButton-primary"]:hover,
    #controls-portal .stButton > button[data-testid="baseButton-primary"]:focus-visible {
        background: var(--cspe-accent-mid) !important;
        background-image: none !important;
        border-color: var(--cspe-border-hover) !important;
        color: #ffffff !important;
    }
    #controls-portal .stButton > button[kind="primary"] *,
    #controls-portal .stButton > button[data-testid="baseButton-primary"] * {
        color: inherit !important;
    }
    /* Right-rail chrome: only the main 3-column row's right cell (map + settings anchors
       both live under that row). Avoids nested st.columns rows that also :has(#cspe-right-settings-anchor). */
    div[data-testid="stHorizontalBlock"]:has(#map-zone-anchor):has(#cspe-right-settings-anchor)
        > div[data-testid="column"]:last-child {
        padding-left: clamp(0.315rem, 0.84vw, 0.49rem) !important;
        padding-right: clamp(0.315rem, 0.84vw, 0.49rem) !important;
        box-sizing: border-box !important;
        overflow-x: clip;
        background: var(--cspe-bg-surface) !important;
        min-height: 100vh;
    }
    div[data-testid="stHorizontalBlock"]:has(#map-zone-anchor):has(#cspe-right-settings-anchor)
        > div[data-testid="column"]:last-child
        > div[data-testid="stVerticalBlock"] {
        max-width: 100% !important;
        box-sizing: border-box !important;
    }
    div[data-testid="stAppViewContainer"]
        div[data-testid="column"]:has(#cspe-right-settings-anchor),
    section.main div[data-testid="column"]:has(#cspe-right-settings-anchor),
    section.main
        div[data-testid="stHorizontalBlock"]
        > div[data-testid="column"]:has(#cspe-right-settings-anchor) {
        color: var(--cspe-text);
        /* Settings rail body: ~40% smaller than prior chrome (orb is outside this column). */
        font-size: 0.39rem;
        box-sizing: border-box !important;
        overflow-x: clip;
        background: var(--cspe-bg-surface) !important;
    }
    section.main
        div[data-testid="stHorizontalBlock"]:has(.cspe-left-rail)
        > div[data-testid="column"]:first-child {
        background: var(--cspe-bg-surface) !important;
        border-right: 1px solid var(--cspe-border-muted) !important;
        box-sizing: border-box !important;
    }
    section.main
        div[data-testid="stHorizontalBlock"]
        > div[data-testid="column"]:has(#cspe-right-settings-anchor)
        > div[data-testid="stVerticalBlock"] {
        gap: calc(var(--cspe-space-sm) * 0.6) !important;
        box-sizing: border-box !important;
        margin-left: 0 !important;
        margin-right: 0 !important;
        max-width: 100% !important;
    }
    section.main
        div[data-testid="column"]:has(#cspe-right-settings-anchor)
        [data-testid="element-container"] {
        margin-left: 0 !important;
        margin-right: 0 !important;
        max-width: 100% !important;
    }
    div[data-testid="column"]:has(#cspe-right-settings-anchor) [data-testid="stWidgetLabel"] p {
        font-family: "Rajdhani", "Segoe UI", sans-serif !important;
        font-size: 0.372rem !important;
        font-weight: 600 !important;
        line-height: 1.2 !important;
        letter-spacing: 0.06em !important;
        text-transform: uppercase !important;
        color: var(--cspe-text-muted) !important;
        margin-bottom: calc(var(--cspe-space-xs) * 0.6) !important;
    }
    div[data-testid="column"]:has(#cspe-right-settings-anchor) [data-testid="stMarkdownContainer"] p,
    div[data-testid="column"]:has(#cspe-right-settings-anchor) [data-testid="stMarkdownContainer"] li {
        font-family: "Rajdhani", "Segoe UI", sans-serif !important;
        font-size: 0.408rem !important;
        line-height: 1.35 !important;
        margin-bottom: calc(var(--cspe-space-xs) * 0.6) !important;
        color: var(--cspe-text) !important;
    }
    div[data-testid="column"]:has(#cspe-right-settings-anchor) h3 {
        font-family: "Rajdhani", "Segoe UI", sans-serif !important;
        font-size: 0.432rem !important;
        font-weight: 600 !important;
        letter-spacing: 0.036em !important;
        color: var(--cspe-text) !important;
        margin: calc(var(--cspe-space-xs) * 0.6) 0 calc(var(--cspe-space-xs) * 0.6) 0 !important;
        line-height: 1.2 !important;
    }
    div[data-testid="column"]:has(#cspe-right-settings-anchor) [data-testid="stMarkdownContainer"] h4 {
        font-family: "Rajdhani", "Segoe UI", sans-serif !important;
        font-size: 0.372rem !important;
        font-weight: 600 !important;
        letter-spacing: 0.06em !important;
        text-transform: uppercase !important;
        color: var(--cspe-text-muted) !important;
        margin: calc(var(--cspe-space-xs) * 0.6) 0 calc(var(--cspe-space-xs) * 0.6) 0 !important;
        line-height: 1.2 !important;
    }
    div[data-testid="column"]:has(#cspe-right-settings-anchor) [data-testid="stCaptionContainer"] p {
        font-family: "Rajdhani", "Segoe UI", sans-serif !important;
        font-size: 0.348rem !important;
        margin-top: 0 !important;
        line-height: 1.25 !important;
        letter-spacing: 0.036em !important;
        color: var(--cspe-text-dim) !important;
    }
    div[data-testid="column"]:has(#cspe-right-settings-anchor) [data-baseweb="select"] > div {
        background: transparent !important;
        color: var(--cspe-text) !important;
        border: 1px solid var(--cspe-border) !important;
        border-radius: var(--cspe-radius) !important;
        min-height: 0.9rem !important;
        font-family: "Rajdhani", "Segoe UI", sans-serif !important;
        font-size: 0.372rem !important;
        padding-top: 0.06rem !important;
        padding-bottom: 0.06rem !important;
    }
    div[data-testid="column"]:has(#cspe-right-settings-anchor) [data-testid="stExpander"] {
        background: transparent !important;
        border: none !important;
        border-bottom: 1px solid var(--cspe-border-muted) !important;
        border-radius: 0 !important;
        box-shadow: none !important;
        margin-bottom: calc(var(--cspe-space-sm) * 0.6) !important;
    }
    div[data-testid="column"]:has(#cspe-right-settings-anchor) [data-testid="stExpander"] summary {
        padding: calc(var(--cspe-space-sm) * 0.6) 0 !important;
        min-height: unset !important;
        background: transparent !important;
    }
    div[data-testid="column"]:has(#cspe-right-settings-anchor) [data-testid="stExpander"] summary,
    div[data-testid="column"]:has(#cspe-right-settings-anchor) [data-testid="stExpander"] summary p {
        font-family: "Rajdhani", "Segoe UI", sans-serif !important;
        font-size: 0.432rem !important;
        font-weight: 600 !important;
        line-height: 1.2 !important;
        letter-spacing: 0.084em !important;
        color: var(--cspe-text-muted) !important;
        text-transform: uppercase !important;
    }
    div[data-testid="column"]:has(#cspe-right-settings-anchor) [data-testid="stExpander"] details {
        font-family: "Rajdhani", "Segoe UI", sans-serif !important;
        font-size: 0.408rem !important;
    }
    div[data-testid="column"]:has(#cspe-right-settings-anchor) [data-testid="stExpander"] [data-testid="stExpanderDetails"] {
        padding: 0 calc(var(--cspe-space-xs) * 0.6) calc(var(--cspe-space-md) * 0.6) 0 !important;
        background: transparent !important;
    }
    div[data-testid="column"]:has(#cspe-right-settings-anchor) p.cspe-poi-inline-label {
        font-family: "Rajdhani", "Segoe UI", sans-serif !important;
        font-size: 0.36rem !important;
        font-weight: 600 !important;
        line-height: 1.25 !important;
        letter-spacing: 0.048em !important;
        text-transform: uppercase !important;
        color: var(--cspe-text-muted) !important;
        margin: 0 !important;
        padding: 0 0.09rem 0 0 !important;
        display: flex !important;
        align-items: center !important;
        min-height: 1.23rem !important;
    }
    div[data-testid="column"]:has(#cspe-right-settings-anchor) .stNumberInput {
        width: 100% !important;
        min-width: 0 !important;
    }
    div[data-testid="column"]:has(#cspe-right-settings-anchor) .stNumberInput [data-testid="element-container"] {
        margin-bottom: 0.048rem !important;
    }
    div[data-testid="column"]:has(#cspe-right-settings-anchor) .stNumberInput [data-baseweb="input"] > div {
        background: var(--cspe-bg-elevated) !important;
        border: 1px solid var(--cspe-border-muted) !important;
        border-radius: var(--cspe-radius) !important;
        box-shadow: none !important;
        min-height: 0.852rem !important;
    }
    div[data-testid="column"]:has(#cspe-right-settings-anchor) .stNumberInput:focus-within [data-baseweb="input"] > div {
        border-color: var(--cspe-border) !important;
        box-shadow: 0 0 0 1px var(--cspe-border-muted) !important;
    }
    div[data-testid="column"]:has(#cspe-right-settings-anchor) div[data-testid="stHorizontalBlock"]:has(.stNumberInput) {
        align-items: center !important;
    }
    div[data-testid="column"]:has(#cspe-right-settings-anchor) .stNumberInput input {
        font-family: "Rajdhani", "Segoe UI", sans-serif !important;
        font-size: 0.384rem !important;
        font-weight: 600 !important;
        font-variant-numeric: tabular-nums !important;
        color: var(--cspe-text) !important;
        text-align: right !important;
        padding: 0.072rem 0.192rem !important;
        min-height: 0.852rem !important;
        line-height: 1.2 !important;
        background: transparent !important;
    }
    div[data-testid="column"]:has(#cspe-right-settings-anchor) .stNumberInput button {
        display: none !important;
    }
    /* Graph section: full-width rows aligned with expander summary language */
    div[data-testid="column"]:has(#cspe-right-settings-anchor) .stCheckbox {
        padding: 0 !important;
        margin: 0 0 calc(var(--cspe-space-xs) * 0.6) 0 !important;
        gap: 0 !important;
        width: 100% !important;
    }
    div[data-testid="column"]:has(#cspe-right-settings-anchor) .stCheckbox > label {
        position: relative !important;
        display: flex !important;
        flex-direction: row !important;
        align-items: center !important;
        justify-content: flex-start !important;
        gap: calc(var(--cspe-space-md) * 0.6) !important;
        width: 100% !important;
        min-height: 1.41rem !important;
        padding: calc(var(--cspe-space-sm) * 0.6) calc(var(--cspe-space-md) * 0.6) !important;
        margin: 0 !important;
        box-sizing: border-box !important;
        border: 1px solid var(--cspe-border-muted) !important;
        border-radius: var(--cspe-radius) !important;
        background: rgba(8, 14, 28, 0.42) !important;
        cursor: pointer !important;
    }
    div[data-testid="column"]:has(#cspe-right-settings-anchor) .stCheckbox:has([aria-checked="true"]) > label {
        border-color: var(--cspe-border) !important;
        background: var(--cspe-accent-soft) !important;
        box-shadow:
            0 0 18px rgba(72, 210, 238, 0.12),
            inset 0 1px 0 rgba(255, 255, 255, 0.05) !important;
    }
    div[data-testid="column"]:has(#cspe-right-settings-anchor) .stCheckbox:has(input:disabled) > label {
        opacity: 0.4 !important;
        cursor: not-allowed !important;
        box-shadow: none !important;
    }
    div[data-testid="column"]:has(#cspe-right-settings-anchor) .stCheckbox [role="checkbox"] {
        position: absolute !important;
        width: 1px !important;
        height: 1px !important;
        padding: 0 !important;
        margin: -1px !important;
        overflow: hidden !important;
        clip: rect(0, 0, 0, 0) !important;
        white-space: nowrap !important;
        border: 0 !important;
    }
    div[data-testid="column"]:has(#cspe-right-settings-anchor) .stCheckbox label p,
    div[data-testid="column"]:has(#cspe-right-settings-anchor) .stCheckbox label [data-testid="stMarkdownContainer"] p {
        font-family: "Rajdhani", "Segoe UI", sans-serif !important;
        font-size: 0.372rem !important;
        font-weight: 600 !important;
        letter-spacing: 0.072em !important;
        text-transform: uppercase !important;
        color: var(--cspe-text-muted) !important;
        margin: 0 !important;
        flex: 1 1 auto !important;
        line-height: 1.25 !important;
    }
    div[data-testid="column"]:has(#cspe-right-settings-anchor) .stCheckbox:has([aria-checked="true"]) label p,
    div[data-testid="column"]:has(#cspe-right-settings-anchor)
        .stCheckbox:has([aria-checked="true"])
        label
        [data-testid="stMarkdownContainer"]
        p {
        color: var(--cspe-text) !important;
    }
    div[data-testid="column"]:has(#cspe-right-settings-anchor) .stCheckbox label::after {
        content: "" !important;
        flex: 0 0 0.99rem !important;
        height: 0.192rem !important;
        border-radius: 1px !important;
        border: 1px solid var(--cspe-border-muted) !important;
        background: rgba(0, 0, 0, 0.2) !important;
        margin-left: auto !important;
        box-sizing: border-box !important;
    }
    div[data-testid="column"]:has(#cspe-right-settings-anchor) .stCheckbox:has([aria-checked="true"]) label::after {
        border-color: var(--cspe-border-hover) !important;
        background: rgba(72, 210, 238, 0.35) !important;
        box-shadow: 0 0 10px rgba(72, 210, 238, 0.25) !important;
    }
    div[data-testid="column"]:has(#cspe-right-settings-anchor) .stCheckbox:has(input:disabled) label::after {
        opacity: 0.35 !important;
        box-shadow: none !important;
    }
    /* GRAPH toggles: equal cells in one row (anchor ec + next ec’s horizontal block). */
    div[data-testid="column"]:has(#cspe-right-settings-anchor)
        [data-testid="element-container"]:has(.cspe-rail-compact-strip-anchor) {
        margin: 0 !important;
        padding: 0 !important;
        min-height: 0 !important;
    }
    div[data-testid="column"]:has(#cspe-right-settings-anchor)
        [data-testid="element-container"]:has(.cspe-rail-compact-strip-anchor)
        + [data-testid="element-container"]
        [data-testid="stHorizontalBlock"] {
        display: flex !important;
        flex-direction: row !important;
        flex-wrap: nowrap !important;
        justify-content: flex-start !important;
        align-items: stretch !important;
        gap: calc(var(--cspe-space-sm) * 0.65) !important;
        width: 100% !important;
        max-width: 100% !important;
        margin: 0 0 calc(var(--cspe-space-xs) * 0.55) 0 !important;
        box-sizing: border-box !important;
    }
    div[data-testid="column"]:has(#cspe-right-settings-anchor)
        [data-testid="element-container"]:has(.cspe-rail-compact-strip-anchor)
        + [data-testid="element-container"]
        [data-testid="stHorizontalBlock"]
        > div[data-testid="column"] {
        flex: 1 1 0 !important;
        min-width: 0 !important;
        width: auto !important;
        max-width: none !important;
        display: flex !important;
        flex-direction: column !important;
        align-items: stretch !important;
        justify-content: stretch !important;
        padding-left: 0 !important;
        padding-right: 0 !important;
        margin: 0 !important;
    }
    div[data-testid="column"]:has(#cspe-right-settings-anchor)
        [data-testid="element-container"]:has(.cspe-rail-compact-strip-anchor)
        + [data-testid="element-container"]
        [data-testid="stHorizontalBlock"]
        > div[data-testid="column"]
        > [data-testid="element-container"] {
        flex: 1 1 auto !important;
        width: 100% !important;
        max-width: 100% !important;
        margin: 0 !important;
        margin-bottom: 0 !important;
        min-height: 0 !important;
        display: flex !important;
        flex-direction: column !important;
        align-items: stretch !important;
    }
    div[data-testid="column"]:has(#cspe-right-settings-anchor)
        [data-testid="element-container"]:has(.cspe-rail-compact-strip-anchor)
        + [data-testid="element-container"]
        [data-testid="stHorizontalBlock"]
        .stButton {
        flex: 1 1 auto !important;
        width: 100% !important;
        min-width: 0 !important;
        max-width: 100% !important;
        margin: 0 !important;
        display: flex !important;
        flex-direction: column !important;
        align-items: stretch !important;
    }
    div[data-testid="column"]:has(#cspe-right-settings-anchor)
        [data-testid="element-container"]:has(.cspe-rail-compact-strip-anchor)
        + [data-testid="element-container"]
        [data-testid="stHorizontalBlock"]
        .stButton > button {
        flex: 1 1 auto !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        width: 100% !important;
        min-width: 0 !important;
        max-width: 100% !important;
        min-height: 0.76rem !important;
        height: 100% !important;
        box-sizing: border-box !important;
        padding: 0.048rem 0.1rem !important;
        font-size: 0.288rem !important;
        line-height: 1.1 !important;
        letter-spacing: 0.036em !important;
        white-space: nowrap !important;
        overflow: hidden !important;
        text-overflow: ellipsis !important;
        text-align: center !important;
    }
    div[data-testid="column"]:has(#cspe-right-settings-anchor)
        [data-testid="element-container"]:has(.cspe-rail-compact-strip-anchor)
        + [data-testid="element-container"]
        [data-testid="stHorizontalBlock"]
        .stButton > button p,
    div[data-testid="column"]:has(#cspe-right-settings-anchor)
        [data-testid="element-container"]:has(.cspe-rail-compact-strip-anchor)
        + [data-testid="element-container"]
        [data-testid="stHorizontalBlock"]
        .stButton > button [data-testid="stMarkdownContainer"] p {
        margin: 0 !important;
        padding: 0 !important;
        text-align: center !important;
        width: 100% !important;
        max-width: 100% !important;
        overflow: hidden !important;
        text-overflow: ellipsis !important;
        white-space: nowrap !important;
        line-height: inherit !important;
    }
    div[data-testid="column"]:has(#cspe-right-settings-anchor)
        [data-testid="element-container"]:has(.cspe-rail-compact-strip-anchor)
        + [data-testid="element-container"]
        [data-testid="stHorizontalBlock"]
        .stButton > button[kind="secondary"] {
        background: rgba(8, 14, 28, 0.42) !important;
        border-color: var(--cspe-border-muted) !important;
        color: var(--cspe-text-muted) !important;
    }
    div[data-testid="column"]:has(#cspe-right-settings-anchor)
        [data-testid="element-container"]:has(.cspe-rail-compact-strip-anchor)
        + [data-testid="element-container"]
        [data-testid="stHorizontalBlock"]
        .stButton > button:disabled {
        opacity: 0.38 !important;
        cursor: not-allowed !important;
    }
    /* POI category: chip row — width from label, nowrap, wrap whole buttons to next row if needed. */
    div[data-testid="column"]:has(#cspe-right-settings-anchor)
        [data-testid="element-container"]:has(.cspe-rail-category-chip-row) {
        margin: 0 !important;
        padding: 0 !important;
        min-height: 0 !important;
    }
    div[data-testid="column"]:has(#cspe-right-settings-anchor)
        [data-testid="element-container"]:has(.cspe-rail-category-chip-row)
        + [data-testid="element-container"]
        [data-testid="stHorizontalBlock"] {
        display: flex !important;
        flex-direction: row !important;
        flex-wrap: wrap !important;
        justify-content: flex-start !important;
        align-items: center !important;
        align-content: flex-start !important;
        gap: calc(var(--cspe-space-sm) * 0.65) !important;
        row-gap: calc(var(--cspe-space-sm) * 0.6) !important;
        column-gap: calc(var(--cspe-space-sm) * 0.65) !important;
        width: 100% !important;
        max-width: 100% !important;
        margin: 0 0 calc(var(--cspe-space-xs) * 0.55) 0 !important;
        box-sizing: border-box !important;
    }
    div[data-testid="column"]:has(#cspe-right-settings-anchor)
        [data-testid="element-container"]:has(.cspe-rail-category-chip-row)
        + [data-testid="element-container"]
        [data-testid="stHorizontalBlock"]
        > div[data-testid="column"] {
        flex: 0 0 auto !important;
        width: max-content !important;
        min-width: min-content !important;
        max-width: 100% !important;
        display: flex !important;
        flex-direction: column !important;
        align-items: stretch !important;
        padding-left: 0 !important;
        padding-right: 0 !important;
        margin: 0 !important;
    }
    div[data-testid="column"]:has(#cspe-right-settings-anchor)
        [data-testid="element-container"]:has(.cspe-rail-category-chip-row)
        + [data-testid="element-container"]
        [data-testid="stHorizontalBlock"]
        > div[data-testid="column"]
        > [data-testid="element-container"] {
        flex: 0 0 auto !important;
        width: max-content !important;
        max-width: 100% !important;
        margin: 0 !important;
        margin-bottom: 0 !important;
        min-height: 0 !important;
        display: flex !important;
        flex-direction: column !important;
        align-items: stretch !important;
    }
    div[data-testid="column"]:has(#cspe-right-settings-anchor)
        [data-testid="element-container"]:has(.cspe-rail-category-chip-row)
        + [data-testid="element-container"]
        [data-testid="stHorizontalBlock"]
        .stButton {
        flex: 0 0 auto !important;
        width: max-content !important;
        max-width: 100% !important;
        min-width: 0 !important;
        margin: 0 !important;
        display: flex !important;
        flex-direction: column !important;
        align-items: stretch !important;
    }
    div[data-testid="column"]:has(#cspe-right-settings-anchor)
        [data-testid="element-container"]:has(.cspe-rail-category-chip-row)
        + [data-testid="element-container"]
        [data-testid="stHorizontalBlock"]
        .stButton > button {
        flex: 0 0 auto !important;
        flex-shrink: 0 !important;
        display: inline-flex !important;
        align-items: center !important;
        justify-content: center !important;
        width: auto !important;
        min-width: min-content !important;
        max-width: none !important;
        min-height: 0.76rem !important;
        height: auto !important;
        box-sizing: border-box !important;
        padding: 0.048rem 0.22rem !important;
        font-size: 0.288rem !important;
        line-height: 1.1 !important;
        letter-spacing: 0.036em !important;
        white-space: nowrap !important;
        overflow: visible !important;
        text-overflow: clip !important;
        word-break: normal !important;
        overflow-wrap: normal !important;
        text-align: center !important;
    }
    div[data-testid="column"]:has(#cspe-right-settings-anchor)
        [data-testid="element-container"]:has(.cspe-rail-category-chip-row)
        + [data-testid="element-container"]
        [data-testid="stHorizontalBlock"]
        .stButton > button p,
    div[data-testid="column"]:has(#cspe-right-settings-anchor)
        [data-testid="element-container"]:has(.cspe-rail-category-chip-row)
        + [data-testid="element-container"]
        [data-testid="stHorizontalBlock"]
        .stButton > button [data-testid="stMarkdownContainer"] p {
        margin: 0 !important;
        padding: 0 !important;
        text-align: center !important;
        width: auto !important;
        max-width: none !important;
        white-space: nowrap !important;
        overflow: visible !important;
        text-overflow: clip !important;
        word-break: normal !important;
        overflow-wrap: normal !important;
        line-height: inherit !important;
    }
    div[data-testid="column"]:has(#cspe-right-settings-anchor)
        [data-testid="element-container"]:has(.cspe-rail-category-chip-row)
        + [data-testid="element-container"]
        [data-testid="stHorizontalBlock"]
        .stButton > button[kind="secondary"] {
        background: rgba(8, 14, 28, 0.42) !important;
        border-color: var(--cspe-border-muted) !important;
        color: var(--cspe-text-muted) !important;
    }
    div[data-testid="column"]:has(#cspe-right-settings-anchor)
        [data-testid="element-container"]:has(.cspe-rail-category-chip-row)
        + [data-testid="element-container"]
        [data-testid="stHorizontalBlock"]
        .stButton > button:disabled {
        opacity: 0.38 !important;
        cursor: not-allowed !important;
    }
    div[data-testid="column"]:has(#cspe-right-settings-anchor) .stButton button,
    div[data-testid="column"]:has(#cspe-right-settings-anchor) .stDownloadButton button {
        background: transparent !important;
        color: var(--cspe-text) !important;
        border: 1px solid var(--cspe-border) !important;
        border-radius: var(--cspe-radius) !important;
        font-family: "Rajdhani", "Segoe UI", sans-serif !important;
        font-size: 0.372rem !important;
        font-weight: 600 !important;
        letter-spacing: 0.06em !important;
        text-transform: uppercase !important;
        min-height: 0.9rem !important;
        padding: 0.108rem 0.24rem !important;
        box-shadow: none !important;
    }
    div[data-testid="column"]:has(#cspe-right-settings-anchor) .stButton button *,
    div[data-testid="column"]:has(#cspe-right-settings-anchor) .stDownloadButton button * {
        font-size: inherit !important;
    }
    div[data-testid="column"]:has(#cspe-right-settings-anchor) .stButton > button[kind="primary"],
    div[data-testid="column"]:has(#cspe-right-settings-anchor) .stDownloadButton > button[kind="primary"],
    div[data-testid="column"]:has(#cspe-right-settings-anchor)
        .stButton > button[data-testid="baseButton-primary"],
    div[data-testid="column"]:has(#cspe-right-settings-anchor)
        .stDownloadButton > button[data-testid="baseButton-primary"] {
        background: var(--cspe-accent-soft) !important;
        background-image: none !important;
        border-color: var(--cspe-border-strong) !important;
    }
    div[data-testid="column"]:has(#cspe-right-settings-anchor) .stButton > button[kind="primary"]:hover,
    div[data-testid="column"]:has(#cspe-right-settings-anchor) .stButton > button[kind="primary"]:focus-visible,
    div[data-testid="column"]:has(#cspe-right-settings-anchor) .stDownloadButton > button[kind="primary"]:hover,
    div[data-testid="column"]:has(#cspe-right-settings-anchor) .stDownloadButton > button[kind="primary"]:focus-visible,
    div[data-testid="column"]:has(#cspe-right-settings-anchor)
        .stButton > button[data-testid="baseButton-primary"]:hover,
    div[data-testid="column"]:has(#cspe-right-settings-anchor)
        .stButton > button[data-testid="baseButton-primary"]:focus-visible,
    div[data-testid="column"]:has(#cspe-right-settings-anchor)
        .stDownloadButton > button[data-testid="baseButton-primary"]:hover,
    div[data-testid="column"]:has(#cspe-right-settings-anchor)
        .stDownloadButton > button[data-testid="baseButton-primary"]:focus-visible {
        background: var(--cspe-accent-mid) !important;
        border-color: var(--cspe-border-hover) !important;
        color: #ffffff !important;
    }
    div[data-testid="column"]:has(#cspe-right-settings-anchor) [data-testid="stAlert"] {
        padding: calc(var(--cspe-space-sm) * 0.6) calc(var(--cspe-space-md) * 0.6) !important;
        font-family: "Rajdhani", "Segoe UI", sans-serif !important;
        background: var(--cspe-bg-elevated) !important;
        border: 1px solid var(--cspe-border) !important;
        border-radius: var(--cspe-radius) !important;
    }
    div[data-testid="column"]:has(#cspe-right-settings-anchor) [data-testid="stAlert"] p {
        font-size: 0.372rem !important;
        line-height: 1.35 !important;
        color: var(--cspe-text) !important;
    }
    div[data-testid="column"]:has(#cspe-right-settings-anchor) [data-baseweb="notification"] {
        font-family: "Rajdhani", "Segoe UI", sans-serif !important;
    }
    div[data-testid="column"]:has(#cspe-right-settings-anchor) .stSuccess,
    div[data-testid="column"]:has(#cspe-right-settings-anchor) [data-testid="stSuccess"] {
        background: rgba(34, 197, 94, 0.06) !important;
        border: 1px solid rgba(74, 222, 128, 0.28) !important;
        border-radius: var(--cspe-radius) !important;
    }
    div[data-testid="column"]:has(#cspe-right-settings-anchor) .stSuccess p,
    div[data-testid="column"]:has(#cspe-right-settings-anchor) [data-testid="stSuccess"] p {
        font-family: "Rajdhani", "Segoe UI", sans-serif !important;
        font-size: 0.384rem !important;
        font-weight: 600 !important;
        letter-spacing: 0.048em !important;
        color: var(--cspe-text) !important;
    }
    div[data-testid="column"]:has(#cspe-right-settings-anchor) textarea,
    div[data-testid="column"]:has(#cspe-right-settings-anchor) pre {
        font-family: ui-monospace, "Cascadia Code", "Segoe UI Mono", monospace !important;
        font-size: 0.348rem !important;
        line-height: 1.35 !important;
        max-height: 3.9rem !important;
        overflow-y: auto !important;
        color: var(--cspe-text) !important;
        background: var(--cspe-bg-elevated) !important;
        border: 1px solid var(--cspe-border) !important;
        border-radius: var(--cspe-radius) !important;
    }
    #route-bar-portal {
        position: absolute !important;
        left: var(--cspe-route-inset) !important;
        right: var(--cspe-route-inset) !important;
        width: auto !important;
        max-width: none !important;
        bottom: var(--cspe-route-bottom) !important;
        z-index: 80 !important;
        pointer-events: auto !important;
        margin: 0 !important;
        /* Equal top/bottom inset (was space-sm top + space-md bottom → looked bottom-heavy). */
        padding: var(--cspe-space-md) var(--cspe-space-md) !important;
        box-sizing: border-box !important;
        background: var(--cspe-bg-elevated) !important;
        border: 1px solid var(--cspe-border) !important;
        border-radius: var(--cspe-radius) !important;
        box-shadow: 0 0 0 1px var(--cspe-border-muted), 0 12px 40px rgba(0, 0, 0, 0.42) !important;
        backdrop-filter: blur(10px);
        overflow: visible !important;
    }
    #route-bar-portal > div {
        width: 100%;
    }
    #route-bar-portal [data-testid="stVerticalBlock"] {
        gap: var(--cspe-space-sm) !important;
    }
    /* Bottom-align columns: search slots are shorter than button columns; center would float inputs upward. */
    #route-bar-portal[data-testid="stHorizontalBlock"],
    #route-bar-portal [data-testid="stHorizontalBlock"] {
        align-items: flex-end !important;
        gap: var(--cspe-space-sm) !important;
        flex-wrap: nowrap !important;
    }
    #route-bar-portal [data-testid="element-container"] {
        margin-top: 0 !important;
        margin-bottom: 0 !important;
        overflow: visible !important;
    }
    #route-bar-portal [data-testid="element-container"]:has(#route-bar-portal-root) {
        margin: 0 !important;
        padding: 0 !important;
        min-height: 0 !important;
    }
    #route-bar-portal [data-testid="column"] {
        overflow: visible !important;
    }
    /* Search columns: fixed layout slot; iframe is absolutely positioned tall so it opens menu upward without resizing the row. */
    #route-bar-portal [data-testid="column"]:has(iframe[title="streamlit_searchbox.searchbox"]) {
        position: relative !important;
        min-height: 2.5rem !important;
        height: 2.5rem !important;
        max-height: 2.5rem !important;
        overflow: visible !important;
        align-self: flex-end !important;
        padding-top: 0 !important;
    }
    #route-bar-portal [data-testid="element-container"]:has(iframe[title="streamlit_searchbox.searchbox"]) {
        overflow: visible !important;
        margin-bottom: 0 !important;
    }
    #route-bar-portal .stTextInput,
    #route-bar-portal .stButton {
        margin: 0 !important;
    }
    #route-bar-portal [data-testid="column"]:has(.stButton) {
        align-self: flex-end !important;
        display: flex !important;
        flex-direction: column !important;
        justify-content: flex-end !important;
    }
    #route-bar-portal [data-testid="column"]:has(.stButton) [data-testid="element-container"] {
        margin-top: 0 !important;
        margin-bottom: 0 !important;
    }
    #route-bar-portal iframe[title="streamlit_searchbox.searchbox"] {
        position: absolute !important;
        left: 0 !important;
        right: 0 !important;
        bottom: 0 !important;
        width: 100% !important;
        height: 300px !important;
        min-height: 300px !important;
        max-height: 300px !important;
        margin: 0 !important;
        z-index: 90 !important;
        border: none !important;
        pointer-events: auto !important;
    }
    #route-bar-portal label,
    #route-bar-portal [data-testid="stWidgetLabel"] p {
        font-family: "Rajdhani", "Segoe UI", sans-serif !important;
        font-size: 0.62rem !important;
        font-weight: 600 !important;
        letter-spacing: 0.1em !important;
        text-transform: uppercase !important;
        color: var(--cspe-text-muted) !important;
        margin-bottom: var(--cspe-space-xs) !important;
    }
    #route-bar-portal [data-baseweb="select"] > div,
    #route-bar-portal .stTextInput input {
        background: transparent !important;
        color: var(--cspe-text) !important;
        border: 1px solid var(--cspe-border) !important;
        border-radius: var(--cspe-radius) !important;
        min-height: 2.1rem !important;
        font-family: "Rajdhani", "Segoe UI", sans-serif !important;
        font-size: 0.68rem !important;
    }
    #route-bar-portal .stButton button {
        background: transparent !important;
        color: var(--cspe-text) !important;
        border: 1px solid var(--cspe-border) !important;
        border-radius: var(--cspe-radius) !important;
        min-height: 2.1rem !important;
        padding-top: 0.2rem !important;
        padding-bottom: 0.2rem !important;
        padding-left: 0.65rem !important;
        padding-right: 0.65rem !important;
        font-family: "Rajdhani", "Segoe UI", sans-serif !important;
        font-size: 0.68rem !important;
        font-weight: 600 !important;
        letter-spacing: 0.1em !important;
        text-transform: uppercase !important;
        white-space: nowrap !important;
        min-width: 5.75rem !important;
        box-shadow: none !important;
    }
    #route-bar-portal .stButton > button[kind="primary"],
    #route-bar-portal .stButton > button[data-testid="baseButton-primary"] {
        background: var(--cspe-accent-soft) !important;
        background-image: none !important;
        border: 1px solid var(--cspe-border-strong) !important;
        box-shadow: none !important;
    }
    #route-bar-portal .stButton > button[kind="primary"]:hover,
    #route-bar-portal .stButton > button[kind="primary"]:focus-visible,
    #route-bar-portal .stButton > button[data-testid="baseButton-primary"]:hover,
    #route-bar-portal .stButton > button[data-testid="baseButton-primary"]:focus-visible {
        background: var(--cspe-accent-mid) !important;
        border-color: var(--cspe-border-hover) !important;
        color: #ffffff !important;
    }
    #route-bar-portal .stAlert {
        padding: var(--cspe-space-sm) var(--cspe-space-md) !important;
        font-size: 0.64rem !important;
        background: var(--cspe-bg-elevated) !important;
        border: 1px solid var(--cspe-border) !important;
        border-radius: var(--cspe-radius) !important;
    }
    .cspe-side-panel {
        position: relative;
        width: 100%;
        background: var(--cspe-bg-elevated);
        border: 1px solid var(--cspe-border-muted);
        border-radius: var(--cspe-radius);
        padding: var(--cspe-space-md) var(--cspe-space-md);
        margin-bottom: var(--cspe-space-md);
        box-sizing: border-box;
    }
    .cspe-net-stats {
        margin: var(--cspe-space-sm) 0 var(--cspe-space-md) 0;
        padding: 0;
        background: transparent !important;
        border: none !important;
        box-shadow: none !important;
    }
    .cspe-rail-title {
        font-family: "Rajdhani", "Segoe UI", sans-serif;
        font-size: 0.75rem !important;
        font-weight: 600;
        letter-spacing: 0.14em;
        color: var(--cspe-text-muted) !important;
        text-transform: uppercase;
        margin: 0 0 var(--cspe-space-sm) 0;
        padding: 0 0 var(--cspe-space-sm) 0;
        line-height: 1.2;
        border-bottom: 1px solid var(--cspe-border-muted);
    }
    .cspe-rail-title--tight {
        margin-bottom: var(--cspe-space-xs) !important;
    }
    .cspe-rail-title--spaced {
        margin-top: var(--cspe-space-md) !important;
        margin-bottom: var(--cspe-space-md) !important;
    }
    .cspe-rail-subtitle {
        font-family: "Rajdhani", "Segoe UI", sans-serif;
        font-size: 0.62rem !important;
        font-weight: 600;
        letter-spacing: 0.12em;
        color: var(--cspe-text-dim) !important;
        text-transform: uppercase;
        margin: var(--cspe-space-sm) 0 var(--cspe-space-xs) 0;
        line-height: 1.25;
    }
    .cspe-net-stats__grid {
        display: grid;
        grid-template-columns: 1fr 1fr;
        column-gap: var(--cspe-space-lg);
        row-gap: var(--cspe-space-sm);
        align-items: start;
    }
    .cspe-net-stats__item {
        min-width: 0;
    }
    .cspe-net-stats__label {
        font-family: "Rajdhani", "Segoe UI", sans-serif;
        font-size: 0.58rem !important;
        font-weight: 600;
        color: var(--cspe-text-dim) !important;
        letter-spacing: 0.1em;
        text-transform: uppercase;
        margin: 0 0 var(--cspe-space-xs) 0;
        line-height: 1.2;
    }
    .cspe-net-stats__value {
        font-family: "Rajdhani", "Segoe UI", sans-serif;
        font-size: 3.06rem !important;
        font-weight: 600;
        color: var(--cspe-text) !important;
        line-height: 1.02;
        letter-spacing: 0.02em;
        font-variant-numeric: tabular-nums;
    }
    /* Markdown chrome inside settings rail only (orb sits in sibling column stack). */
    div[data-testid="column"]:has(#cspe-right-settings-anchor) .cspe-rail-title {
        font-size: 0.45rem !important;
        margin: 0 0 calc(var(--cspe-space-sm) * 0.6) 0 !important;
        padding: 0 0 calc(var(--cspe-space-sm) * 0.6) 0 !important;
        letter-spacing: 0.084em !important;
    }
    div[data-testid="column"]:has(#cspe-right-settings-anchor) .cspe-rail-title--tight {
        margin-bottom: calc(var(--cspe-space-xs) * 0.6) !important;
    }
    div[data-testid="column"]:has(#cspe-right-settings-anchor) .cspe-rail-title--spaced {
        margin-top: calc(var(--cspe-space-md) * 0.6) !important;
        margin-bottom: calc(var(--cspe-space-md) * 0.6) !important;
    }
    div[data-testid="column"]:has(#cspe-right-settings-anchor) .cspe-rail-subtitle {
        font-size: 0.372rem !important;
        margin: calc(var(--cspe-space-sm) * 0.6) 0 calc(var(--cspe-space-xs) * 0.6) 0 !important;
        letter-spacing: 0.072em !important;
    }
    div[data-testid="column"]:has(#cspe-right-settings-anchor) .cspe-net-stats {
        margin: calc(var(--cspe-space-sm) * 0.6) 0 calc(var(--cspe-space-md) * 0.6) 0 !important;
    }
    div[data-testid="column"]:has(#cspe-right-settings-anchor) .cspe-net-stats__grid {
        column-gap: calc(var(--cspe-space-lg) * 0.6) !important;
        row-gap: calc(var(--cspe-space-sm) * 0.6) !important;
    }
    div[data-testid="column"]:has(#cspe-right-settings-anchor) .cspe-net-stats__label {
        font-size: 0.348rem !important;
        margin: 0 0 calc(var(--cspe-space-xs) * 0.6) 0 !important;
        letter-spacing: 0.06em !important;
    }
    div[data-testid="column"]:has(#cspe-right-settings-anchor) .cspe-net-stats__value {
        font-size: 1.836rem !important;
    }
    div[data-testid="column"]:has(#cspe-right-settings-anchor) [data-testid="stMarkdownContainer"]:has(.cspe-net-stats) p,
    div[data-testid="column"]:has(#cspe-right-settings-anchor) [data-testid="stMarkdownContainer"]:has(.cspe-rail-title) p,
    div[data-testid="column"]:has(#cspe-right-settings-anchor) [data-testid="stMarkdownContainer"]:has(.cspe-rail-subtitle) p {
        margin: 0 !important;
    }
    .cspe-left-rail {
        min-height: 100vh;
        width: 100%;
        background: var(--cspe-bg-surface);
    }
    /* Bordered containers (e.g. station detail card): match dashboard chrome */
    [data-testid="stAppViewContainer"] div[data-testid="stVerticalBlockBorderWrapper"] {
        background: var(--cspe-bg-elevated) !important;
        border: 1px solid var(--cspe-border) !important;
        border-radius: var(--cspe-radius) !important;
        box-shadow: none !important;
    }
    /* Map only: neural orb uses components.html iframe too — do not force 100vh there. */
    div[data-testid="stVerticalBlock"]:has(#map-zone-anchor) iframe[title="st.iframe"] {
        border: none !important;
        border-radius: 0 !important;
        display: block !important;
        height: 100vh !important;
        position: relative !important;
        z-index: 0 !important;
    }
    div[data-baseweb="popover"] {
        z-index: 100010 !important;
    }
    .cspe-top-bar-title {
        font-family: ui-sans-serif, system-ui, "Segoe UI", sans-serif;
        font-size: 1.05rem;
        font-weight: 600;
        color: var(--cspe-text);
        padding: 0.15rem 0 0.35rem 0;
        letter-spacing: 0.02em;
    }
    div[data-testid="column"]:has(#cspe-global-nav-anchor) button[kind="primary"],
    div[data-testid="column"]:has(#cspe-global-nav-anchor) button[kind="secondary"] {
        min-height: 2.65rem;
        font-size: 1.2rem !important;
        padding-left: 0.25rem !important;
        padding-right: 0.25rem !important;
    }
    /* Atlas chat modal: usable size above map/iframes */
    div[data-testid="stDialog"] [role="dialog"],
    div[data-testid="stModal"] [role="dialog"] {
        width: min(96vw, 720px) !important;
        max-width: 96vw !important;
        max-height: min(85vh, 820px) !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

ensure_graph_bundle_inputs()
bundle = load_bundle(PROJECT_ROOT, BUNDLE_PATH, STOP_POPUP_INDEX_PATH)
graphs = bundle["graphs"]
graphs_lcc = bundle["graphs_lcc"]


def _fmt(opt):
    if not opt:
        return ""
    name = opt["stop_name"] if opt["stop_name"] else opt["stop_id"]
    if opt.get("line"):
        return f"{name} — {opt['line']}  |  {opt['stop_id']}"
    return f"{name}  |  {opt['stop_id']}"


def _route_is_real_stop(opt) -> bool:
    return bool(opt) and isinstance(opt, dict) and bool(str(opt.get("stop_id", "")).strip())


def _route_bar_compute_ready() -> bool:
    return _route_is_real_stop(st.session_state.get("controls_start_choice")) and _route_is_real_stop(
        st.session_state.get("controls_end_choice")
    )


@st.fragment
def _route_bar_fragment(g, graph_mode: str) -> None:
    """Debounced live search (streamlit-searchbox); fragment reruns keep the map iframe stable."""

    def _search_opts(term: str):
        t = (term or "").strip()
        if not t:
            return []
        matches = search_stops_autocomplete(g, t, limit=40, mode=graph_mode)
        return [(_fmt(m), m) for m in matches]

    rb_main = st.columns([4.2, 4.2, 1.35, 1.35])
    with rb_main[0]:
        st.markdown(
            '<div id="route-bar-portal-root" aria-hidden="true" '
            'style="height:0;margin:0;padding:0;line-height:0;font-size:0;overflow:hidden;"></div>',
            unsafe_allow_html=True,
        )
        s_pick = st_searchbox(
            _search_opts,
            placeholder="Type to search start…",
            label=None,
            key="route_sb_s",
            rerun_on_update=True,
            rerun_scope="fragment",
            debounce=100,
            min_execution_time=0,
            clear_on_submit=False,
            edit_after_submit="option",
        )
    with rb_main[1]:
        e_pick = st_searchbox(
            _search_opts,
            placeholder="Type to search end…",
            label=None,
            key="route_sb_e",
            rerun_on_update=True,
            rerun_scope="fragment",
            debounce=100,
            min_execution_time=0,
            clear_on_submit=False,
            edit_after_submit="option",
        )

    st.session_state["controls_start_choice"] = s_pick
    st.session_state["controls_end_choice"] = e_pick
    st.session_state["controls_start_q"] = _fmt(s_pick) if _route_is_real_stop(s_pick) else ""
    st.session_state["controls_end_q"] = _fmt(e_pick) if _route_is_real_stop(e_pick) else ""

    with rb_main[2]:
        if st.button(
            "Compute",
            type="primary",
            disabled=not _route_bar_compute_ready(),
            use_container_width=True,
            key="controls_compute_path",
        ):
            st.session_state["_route_bar_action"] = "compute"
            st.rerun()
    with rb_main[3]:
        if st.button("Clear", use_container_width=True, key="controls_clear_path"):
            st.session_state["_route_bar_action"] = "clear"
            st.rerun()


viz_mode_options = ["Geographic Mapbox", "3D network"]
mode_options = ["all", "metro", "rail", "tram", "bus", "other"]
OVERLAY_VIZ_LABELS = ["Geographic", "3D network"]
OVERLAY_MODE_CHOICES: list[tuple[str, str]] = [
    ("all", "All"),
    ("metro", "Metro"),
    ("rail", "Rail"),
    ("tram", "Tram"),
    ("bus", "Bus"),
    ("other", "Other"),
]

POI_CATEGORY_CHOICES: list[tuple[str, str]] = [
    ("All", "All"),
    ("amenity", "Amenity"),
    ("shop", "Shop"),
    ("tourism", "Tourism"),
    ("leisure", "Leisure"),
]

# Side / middle column ratios for inset button groups (gutters = horizontal breathing room from panel edges).
_RAIL_COMPACT_STRIP_GUTTER = 2
_RAIL_COMPACT_STRIP_BODY = 12


@contextmanager
def _rail_compact_button_strip():
    """Inset strip: empty gutter columns + middle body so controls do not touch panel edges."""
    pl, mid, pr = st.columns(
        [_RAIL_COMPACT_STRIP_GUTTER, _RAIL_COMPACT_STRIP_BODY, _RAIL_COMPACT_STRIP_GUTTER],
        gap="small",
    )
    with pl:
        st.empty()
    with pr:
        st.empty()
    with mid:
        yield


def _rail_compact_row_anchor() -> None:
    st.markdown(
        '<div class="cspe-rail-compact-strip-anchor" aria-hidden="true" '
        'style="height:0;margin:0;padding:0;line-height:0;font-size:0;overflow:hidden"></div>',
        unsafe_allow_html=True,
    )


def _rail_category_chip_row_anchor() -> None:
    st.markdown(
        '<div class="cspe-rail-category-chip-row" aria-hidden="true" '
        'style="height:0;margin:0;padding:0;line-height:0;font-size:0;overflow:hidden"></div>',
        unsafe_allow_html=True,
    )


def _render_poi_numeric_row(
    label: str,
    state_key: str,
    *,
    min_value: int,
    max_value: int,
    step: int,
    current: int,
) -> None:
    """Single-line POI control: label left, compact number field right (Streamlit commits on Enter/blur)."""
    lc, rc = st.columns([1, 0.36], gap="small")
    with lc:
        st.markdown(
            f'<p class="cspe-poi-inline-label">{label}</p>',
            unsafe_allow_html=True,
        )
    with rc:
        st.number_input(
            label,
            min_value=min_value,
            max_value=max_value,
            value=int(current),
            step=step,
            key=state_key,
            label_visibility="collapsed",
            format="%d",
        )


def _render_graph_settings_toggle_row(viz_mode: str, *, has_path: bool) -> None:
    """Graph toggles: inset strip; equal-width / equal-height control row via compact-strip CSS."""
    use_lcc = bool(st.session_state.get("controls_use_lcc", True))
    if viz_mode == "Geographic Mapbox":
        transfers_key = "controls_show_transfers_map"
        debug_key = "controls_show_path_match_debug"
    else:
        transfers_key = "controls_show_transfers_network_3d"
        debug_key = "controls_show_path_match_debug_3d"
    transfers_on = bool(st.session_state.get(transfers_key, False))
    debug_on = bool(st.session_state.get(debug_key, False))

    with _rail_compact_button_strip():
        _rail_compact_row_anchor()
        gcols = st.columns([1, 1, 1], gap="small")
        with gcols[0]:
            if st.button(
                "LCC",
                key="graph_toggle_lcc",
                use_container_width=True,
                type="primary" if use_lcc else "secondary",
                help="Largest connected component",
            ):
                st.session_state["controls_use_lcc"] = not use_lcc
                st.rerun()

        with gcols[1]:
            if st.button(
                "Transfers",
                key=f"graph_toggle_{transfers_key}",
                use_container_width=True,
                type="primary" if transfers_on else "secondary",
                help="Show transfer edges",
            ):
                st.session_state[transfers_key] = not transfers_on
                st.rerun()

        with gcols[2]:
            if st.button(
                "Geom",
                key=f"graph_toggle_{debug_key}",
                use_container_width=True,
                type="primary" if debug_on else "secondary",
                disabled=not has_path,
                help="Show path geometry debug (needs a computed route)",
            ):
                if has_path:
                    st.session_state[debug_key] = not debug_on
                    st.rerun()


def _render_poi_category_rail_buttons(state_key: str) -> None:
    valid = {v for v, _ in POI_CATEGORY_CHOICES}
    cur = st.session_state.get(state_key, "All")
    if cur not in valid:
        cur = "All"
        st.session_state[state_key] = cur
    st.markdown('<div class="cspe-rail-subtitle">Category</div>', unsafe_allow_html=True)
    with _rail_compact_button_strip():
        _rail_category_chip_row_anchor()
        cat_cols = st.columns([1] * len(POI_CATEGORY_CHOICES), gap="small")
        for i, (val, label) in enumerate(POI_CATEGORY_CHOICES):
            with cat_cols[i]:
                if st.button(
                    label,
                    key=f"{state_key}__btn__{val}",
                    use_container_width=False,
                    type="primary" if cur == val else "secondary",
                ):
                    st.session_state[state_key] = val
                    st.rerun()


def _render_map_controls_overlay() -> None:
    cur_viz = st.session_state.get("controls_viz_mode", "Geographic Mapbox")
    if cur_viz not in viz_mode_options:
        cur_viz = viz_mode_options[0]
        st.session_state["controls_viz_mode"] = cur_viz

    st.markdown('<p class="cspe-overlay-title">Visualization</p>', unsafe_allow_html=True)
    vcols = st.columns(2, gap="small")
    for i, opt in enumerate(viz_mode_options):
        with vcols[i]:
            if st.button(
                OVERLAY_VIZ_LABELS[i],
                key=f"overlay_viz_{i}",
                use_container_width=True,
                type="primary" if cur_viz == opt else "secondary",
            ):
                st.session_state["controls_viz_mode"] = opt
                st.rerun()

    cur_mode = st.session_state.get("controls_mode", "metro")
    if cur_mode not in mode_options:
        cur_mode = "metro"
        st.session_state["controls_mode"] = cur_mode

    st.markdown('<p class="cspe-overlay-title">Mode</p>', unsafe_allow_html=True)
    m1 = st.columns(3, gap="small")
    m2 = st.columns(3, gap="small")
    for idx, (opt, label) in enumerate(OVERLAY_MODE_CHOICES):
        row = m1 if idx < 3 else m2
        with row[idx % 3]:
            if st.button(
                label,
                key=f"overlay_mode_{opt}",
                use_container_width=True,
                type="primary" if cur_mode == opt else "secondary",
            ):
                st.session_state["controls_mode"] = opt
                st.rerun()

viz_mode = st.session_state.get("controls_viz_mode", "Geographic Mapbox")
mode = st.session_state.get("controls_mode", "metro")
use_lcc = bool(st.session_state.get("controls_use_lcc", True))
show_transfers_map = bool(st.session_state.get("controls_show_transfers_map", False))
show_transfers_network_3d = bool(st.session_state.get("controls_show_transfers_network_3d", False))
show_path_match_debug = bool(st.session_state.get("controls_show_path_match_debug", False))
show_path_match_debug_3d = bool(st.session_state.get("controls_show_path_match_debug_3d", False))
poi_radius_m = int(st.session_state.get("controls_poi_radius_m", 300))
poi_limit = int(st.session_state.get("controls_poi_limit", 25))
poi_radius_m_3d = int(st.session_state.get("controls_poi_radius_m_3d", 300))
poi_limit_3d = int(st.session_state.get("controls_poi_limit_3d", 25))
_poi_cat_valid = {v for v, _ in POI_CATEGORY_CHOICES}
poi_category_key = st.session_state.get("controls_poi_category_key", "All")
if poi_category_key not in _poi_cat_valid:
    poi_category_key = "All"
    st.session_state["controls_poi_category_key"] = "All"
poi_category_key_3d = st.session_state.get("controls_poi_category_key_3d", "All")
if poi_category_key_3d not in _poi_cat_valid:
    poi_category_key_3d = "All"
    st.session_state["controls_poi_category_key_3d"] = "All"
current_path = st.session_state.get("last_path")
last_route_result = st.session_state.get("last_route_result")
last_route_error = st.session_state.get("last_route_error")

app_mode_ui = st.session_state.get("app_mode", "transport")

if app_mode_ui == ui_shell.APP_MODE_TRANSPORT:
    G = (graphs_lcc if use_lcc else graphs)[mode]
    log_event(
        LOGGER,
        "ui_state",
        viz_mode=viz_mode,
        mode=mode,
        use_lcc=use_lcc,
        current_path_length=len(current_path) if current_path else 0,
        poi_radius_m=poi_radius_m,
        poi_limit=poi_limit,
    )
else:
    G = None

ui_shell.render_top_bar()

left_rail_col, center_col, right_col = st.columns([6, 62, 32], gap="large")

with left_rail_col:
    ui_shell.render_mode_nav_column()

with right_col:
    if app_mode_ui == ui_shell.APP_MODE_TRANSPORT:
        components.html(_NEURAL_ORB_HTML, height=360, scrolling=False)
        _cspe_rgl, _cspe_rail_main, _cspe_rgr = st.columns([0.656, 9, 0.656], gap="small")
        with _cspe_rgl:
            st.empty()
        with _cspe_rgr:
            st.empty()
        with _cspe_rail_main:
            st.markdown(
                '<div id="cspe-right-settings-anchor" style="height:0;margin:0;padding:0;line-height:0;font-size:0;"></div>',
                unsafe_allow_html=True,
            )

            st.markdown('<div class="cspe-rail-title cspe-rail-title--tight">[ GRAPH ]</div>', unsafe_allow_html=True)
            _render_graph_settings_toggle_row(viz_mode, has_path=bool(current_path))

            _nn = G.number_of_nodes()
            _ne = G.number_of_edges()
            st.markdown(
                f"""
                <div class="cspe-net-stats">
                  <div class="cspe-rail-title cspe-rail-title--tight">[ NETWORK STATS ]</div>
                  <div class="cspe-net-stats__grid">
                    <div class="cspe-net-stats__item">
                      <div class="cspe-net-stats__label">Nodes</div>
                      <div class="cspe-net-stats__value">{_nn}</div>
                    </div>
                    <div class="cspe-net-stats__item">
                      <div class="cspe-net-stats__label">Edges</div>
                      <div class="cspe-net-stats__value">{_ne}</div>
                    </div>
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            with st.expander("[ TOP HUBS ]", expanded=False):
                for hub in top_hubs(G, k=10):
                    name = hub["stop_name"] if hub["stop_name"] else hub["stop_id"]
                    st.write(f"{name} — degree={hub['degree']}")

            if viz_mode == "Geographic Mapbox":
                st.markdown(
                    '<div class="cspe-rail-title cspe-rail-title--spaced">[ NEARBY POIS ]</div>',
                    unsafe_allow_html=True,
                )
                _render_poi_numeric_row(
                    "POI radius (m)",
                    "controls_poi_radius_m",
                    min_value=100,
                    max_value=1000,
                    step=50,
                    current=poi_radius_m,
                )
                _render_poi_numeric_row(
                    "POIs shown / station",
                    "controls_poi_limit",
                    min_value=5,
                    max_value=200,
                    step=5,
                    current=poi_limit,
                )
                st.caption("Dense areas can fill the result cap before reaching the full radius.")
                _render_poi_category_rail_buttons("controls_poi_category_key")
            else:
                st.markdown(
                    '<div class="cspe-rail-title cspe-rail-title--spaced">[ NEARBY POIS ]</div>',
                    unsafe_allow_html=True,
                )
                _render_poi_numeric_row(
                    "POI radius (m)",
                    "controls_poi_radius_m_3d",
                    min_value=100,
                    max_value=1000,
                    step=50,
                    current=poi_radius_m_3d,
                )
                _render_poi_numeric_row(
                    "POIs shown / station",
                    "controls_poi_limit_3d",
                    min_value=5,
                    max_value=200,
                    step=5,
                    current=poi_limit_3d,
                )
                st.caption("Dense areas can fill the result cap before reaching the full radius.")
                _render_poi_category_rail_buttons("controls_poi_category_key_3d")

            if last_route_error:
                st.markdown(
                    '<div class="cspe-rail-title cspe-rail-title--spaced">[ ROUTE STATUS ]</div>',
                    unsafe_allow_html=True,
                )
                st.error(last_route_error["message"])
                for line in last_route_error.get("details", []):
                    st.write(line)

            if last_route_result and current_path:
                with st.expander("[ CURRENT ROUTE ]", expanded=True):
                    st.success(f"Path found: {len(current_path)} stops")
                    if last_route_result.get("distance_m") is not None:
                        if last_route_result["distance_m"] >= 1000:
                            st.write(f"Estimated distance: {last_route_result['distance_m'] / 1000:.2f} km")
                        else:
                            st.write(f"Estimated distance: {last_route_result['distance_m']:.0f} m")
                    if last_route_result.get("time_s") is not None:
                        st.write(f"Estimated time: {last_route_result['time_s'] / 60:.1f} min")
                    st.write(f"Transfers: {last_route_result.get('transfers', 0)}")

                    pretty = []
                    for sid in current_path[:80]:
                        nm = G.nodes[sid].get("stop_name", "")
                        pretty.append(f"{nm} ({sid})" if nm else sid)

                    st.text("\n".join(pretty) + ("\n..." if len(current_path) > 80 else ""))
                    st.download_button(
                        "Download path (txt)",
                        data=("\n".join(pretty)).encode("utf-8"),
                        file_name="path.txt",
                        mime="text/plain",
                        use_container_width=True,
                    )

    elif app_mode_ui == ui_shell.APP_MODE_KNOWLEDGE:
        ui_shell.render_knowledge_right()
    elif app_mode_ui == ui_shell.APP_MODE_VISUAL:
        ui_shell.render_visual_board_right()
    elif app_mode_ui == ui_shell.APP_MODE_MEMORY:
        ui_shell.render_memory_right()

with center_col:
    if app_mode_ui == ui_shell.APP_MODE_TRANSPORT:
        st.markdown('<div id="map-zone-anchor"></div>', unsafe_allow_html=True)
        if viz_mode == "Geographic Mapbox":
            token, _token_env = get_mapbox_token()
            if token is None:
                st.warning(
                    "Mapbox mode needs a token: set `MAPBOX_ACCESS_TOKEN_INLINE` in `app/app.py`, "
                    "or `MAPBOX_TOKEN` / `MAPBOX_API_KEY` / `MAPBOX_ACCESS_TOKEN` in the environment "
                    "or Streamlit Cloud Secrets."
                )
                log_event(LOGGER, "render_mapbox_skipped_missing_token", viz_mode=viz_mode, mode=mode)
            else:
                line_geometries = load_line_geometries_cached(NETWORK_MAPS_DIR)
                render_graphs = load_render_graphs_cached(RENDER_GRAPH_PATHS)
                poi_lookup = load_poi_lookup_cached(POI_DATA_PATH, POI_TREE_PATH, POI_NPZ_PATH)
                log_event(
                    LOGGER,
                    "render_mapbox_start",
                    viz_mode=viz_mode,
                    mode=mode,
                    use_lcc=use_lcc,
                    node_count=G.number_of_nodes(),
                    edge_count=G.number_of_edges(),
                    has_line_geometries=line_geometries is not None,
                    render_graph_modes="|".join(sorted(render_graphs.keys())) if render_graphs else "",
                    poi_lookup_loaded=poi_lookup is not None,
                )
                map_html, _path_debug = render_mapbox_gl_html(
                    G,
                    mapbox_token=token,
                    mode=mode,
                    path=current_path,
                    show_transfers=show_transfers_map,
                title=f"Mode: {mode} {'(LCC)' if use_lcc else ''}",
                    basemap_style=DEFAULT_MAPBOX_STYLE,
                    line_geometries=line_geometries,
                    render_graphs_by_mode=render_graphs or None,
                    poi_lookup=poi_lookup,
                    poi_radius_m=float(poi_radius_m),
                    poi_limit=int(poi_limit),
                    poi_category_key=None if poi_category_key == "All" else poi_category_key,
                    pitched_view=False,
                    show_3d_buildings=False,
                    height_px=1100,
                )
                components.html(map_html, height=1100)
        else:
            token, _token_env = get_mapbox_token()
            if token is None:
                st.warning(
                    "Mapbox mode needs a token: set `MAPBOX_ACCESS_TOKEN_INLINE` in `app/app.py`, "
                    "or `MAPBOX_TOKEN` / `MAPBOX_API_KEY` / `MAPBOX_ACCESS_TOKEN` in the environment "
                    "or Streamlit Cloud Secrets."
                )
                log_event(LOGGER, "render_3d_skipped_missing_token", viz_mode=viz_mode, mode=mode)
            else:
                line_geometries = load_line_geometries_cached(NETWORK_MAPS_DIR)
                render_graphs = load_render_graphs_cached(RENDER_GRAPH_PATHS)
                poi_lookup = load_poi_lookup_cached(POI_DATA_PATH, POI_TREE_PATH, POI_NPZ_PATH)
                log_event(
                    LOGGER,
                    "render_3d_start",
                    viz_mode=viz_mode,
                    mode=mode,
                    use_lcc=use_lcc,
                    node_count=G.number_of_nodes(),
                    edge_count=G.number_of_edges(),
                    has_line_geometries=line_geometries is not None,
                    render_graph_modes="|".join(sorted(render_graphs.keys())) if render_graphs else "",
                    poi_lookup_loaded=poi_lookup is not None,
                )
                map_html, _path_debug = render_mapbox_gl_html(
                    G,
                    mapbox_token=token,
                    mode=mode,
                    path=current_path,
                    show_transfers=show_transfers_network_3d,
                    title=f"Mode: {mode} {'(LCC)' if use_lcc else ''}",
                    basemap_style=DEFAULT_MAPBOX_STYLE,
                    line_geometries=line_geometries,
                    render_graphs_by_mode=render_graphs or None,
                    poi_lookup=poi_lookup,
                    poi_radius_m=float(poi_radius_m_3d),
                    poi_limit=int(poi_limit_3d),
                    poi_category_key=None if poi_category_key_3d == "All" else poi_category_key_3d,
                    pitched_view=True,
                    show_3d_buildings=True,
                    height_px=1100,
                )
                components.html(map_html, height=1100)

        overlay_host = st.container()
        with overlay_host:
            st.markdown('<div id="controls-overlay-anchor"></div>', unsafe_allow_html=True)
            _render_map_controls_overlay()
            st.markdown('<div id="controls-overlay-end"></div>', unsafe_allow_html=True)

        route_bar_host = st.container()
        with route_bar_host:
            st.markdown('<div id="route-bar-anchor"></div>', unsafe_allow_html=True)
            _route_bar_fragment(G, mode)

        st.html(
            """
            <script>
            (() => {
              const attachOverlayHost = () => {
                const anchor = document.getElementById('controls-overlay-anchor');
                const end = document.getElementById('controls-overlay-end');
                if (!anchor || !end) {
                  return false;
                }
                const chain = [];
                let x = anchor;
                while (x) {
                  chain.push(x);
                  x = x.parentElement;
                }
                let host = null;
                let y = end;
                while (y) {
                  if (chain.includes(y)) {
                    host = y;
                    break;
                  }
                  y = y.parentElement;
                }
                if (!host || host.tagName === 'BODY') {
                  return false;
                }
                const stalePortal = document.body.querySelector('#controls-portal');
                if (stalePortal && stalePortal !== host) {
                  stalePortal.removeAttribute('id');
                }
                host.id = 'controls-portal';
                host.style.margin = '0';
                host.style.overflow = 'visible';
                return true;
              };

              const attachRouteBarHost = () => {
                const rowMarker = document.getElementById('route-bar-portal-root');
                let host = rowMarker ? rowMarker.closest('[data-testid="stHorizontalBlock"]') : null;
                if (!host) {
                  const anchor = document.getElementById('route-bar-anchor');
                  if (!anchor) {
                    return false;
                  }
                  let h = anchor.parentElement;
                  while (h) {
                    const inputs = h.querySelectorAll('[data-testid="stTextInput"]');
                    if (inputs.length >= 2) {
                      host = h;
                      break;
                    }
                    h = h.parentElement;
                    if (!h || h.tagName === 'BODY') {
                      return false;
                    }
                  }
                  const tis = host.querySelectorAll('[data-testid="stTextInput"]');
                  if (tis.length >= 2) {
                    let a = tis[0];
                    while (a && host.contains(a)) {
                      if (
                        a.getAttribute &&
                        a.getAttribute('data-testid') === 'stHorizontalBlock' &&
                        a.contains(tis[1])
                      ) {
                        host = a;
                        break;
                      }
                      a = a.parentElement;
                    }
                  }
                }
                if (!host) {
                  return false;
                }
                const stale = document.getElementById('route-bar-portal');
                if (stale && stale !== host) {
                  stale.removeAttribute('id');
                }
                host.id = 'route-bar-portal';
                host.style.margin = '0';
                host.style.overflow = 'visible';
                host.style.setProperty('z-index', '80', 'important');
                return true;
              };

              /* streamlit-searchbox iframe height is driven by React; that grows the route row. Pin columns + use a tall
                 absolutely positioned iframe so the control stays anchored and the menu opens upward inside the iframe. */
              const applyRouteSearchOverlayLayout = () => {
                const portal = document.getElementById('route-bar-portal');
                if (!portal) {
                  return;
                }
                portal.style.setProperty('overflow', 'visible', 'important');
                portal.style.setProperty('z-index', '80', 'important');
                portal.querySelectorAll('iframe[title="streamlit_searchbox.searchbox"]').forEach((ifr) => {
                  const col = ifr.closest('[data-testid="column"]');
                  if (col) {
                    col.style.setProperty('position', 'relative', 'important');
                    col.style.setProperty('min-height', '2.5rem', 'important');
                    col.style.setProperty('height', '2.5rem', 'important');
                    col.style.setProperty('max-height', '2.5rem', 'important');
                    col.style.setProperty('overflow', 'visible', 'important');
                  }
                  let p = ifr.parentElement;
                  while (p && p !== portal) {
                    p.style.setProperty('overflow', 'visible', 'important');
                    p = p.parentElement;
                  }
                  ifr.style.setProperty('position', 'absolute', 'important');
                  ifr.style.setProperty('left', '0', 'important');
                  ifr.style.setProperty('right', '0', 'important');
                  ifr.style.setProperty('bottom', '0', 'important');
                  ifr.style.setProperty('width', '100%', 'important');
                  ifr.style.setProperty('height', '300px', 'important');
                  ifr.style.setProperty('min-height', '300px', 'important');
                  ifr.style.setProperty('max-height', '300px', 'important');
                  ifr.style.setProperty('z-index', '90', 'important');
                  ifr.style.setProperty('margin', '0', 'important');
                  try {
                    const doc = ifr.contentDocument;
                    if (!doc || !doc.head) {
                      return;
                    }
                    let st = doc.getElementById('cspe-route-search-inner');
                    if (!st) {
                      st = doc.createElement('style');
                      st.id = 'cspe-route-search-inner';
                      st.textContent = `
                        html, body {
                          height: 100% !important;
                          margin: 0 !important;
                          overflow: visible !important;
                          background: transparent !important;
                        }
                        #root {
                          height: 100% !important;
                          min-height: 100% !important;
                          display: flex !important;
                          flex-direction: column !important;
                          justify-content: flex-end !important;
                          align-items: stretch !important;
                          overflow: visible !important;
                          box-sizing: border-box !important;
                        }
                        #root > div {
                          width: 100% !important;
                          max-width: 100% !important;
                        }
                        div[class*="menu" i]:not([class*="MenuList" i]) {
                          top: auto !important;
                          bottom: 100% !important;
                          margin-bottom: 6px !important;
                          margin-top: 0 !important;
                        }
                        div[class*="MenuList" i] {
                          max-height: min(42vh, 220px) !important;
                        }
                      `;
                      doc.head.appendChild(st);
                    }
                  } catch (e) {
                    /* not same-origin yet */
                  }
                });
              };

              const attachRightRailInset = () => {
                const mapA = document.getElementById('map-zone-anchor');
                const railA = document.getElementById('cspe-right-settings-anchor');
                if (!mapA || !railA) {
                  return false;
                }
                let el = railA;
                while (el) {
                  const hb = el.closest('[data-testid="stHorizontalBlock"]');
                  if (!hb) {
                    break;
                  }
                  const cols = [...hb.querySelectorAll(':scope > div[data-testid="column"]')];
                  if (
                    cols.length === 3 &&
                    cols.some((c) => c.contains(mapA)) &&
                    cols.some((c) => c.contains(railA))
                  ) {
                    const rc = cols[2];
                    const pad = 'clamp(5px, 0.84vw, 8px)';
                    rc.style.setProperty('padding-left', pad, 'important');
                    rc.style.setProperty('padding-right', pad, 'important');
                    rc.style.setProperty('box-sizing', 'border-box', 'important');
                    const vb = rc.querySelector(':scope > div[data-testid="stVerticalBlock"]');
                    if (vb) {
                      vb.style.setProperty('max-width', '100%', 'important');
                      vb.style.setProperty('box-sizing', 'border-box', 'important');
                    }
                    return true;
                  }
                  el = hb.parentElement;
                }
                return false;
              };

              const ensureMapStackRoot = () => {
                const mapAnchor = document.getElementById('map-zone-anchor');
                if (!mapAnchor) {
                  return false;
                }
                const root = mapAnchor.closest('div[data-testid="stVerticalBlock"]');
                if (!root) {
                  return false;
                }
                root.classList.add('cspe-map-stack-root');
                root.style.setProperty('position', 'relative', 'important');
                root.style.setProperty('min-height', '100vh', 'important');
                root.style.setProperty('height', '100vh', 'important');
                root.style.setProperty('overflow', 'visible', 'important');
                return true;
              };

              const tryAttachOverlays = () => {
                ensureMapStackRoot();
                attachOverlayHost();
                attachRouteBarHost();
                attachRightRailInset();
                applyRouteSearchOverlayLayout();
              };
              tryAttachOverlays();
              requestAnimationFrame(tryAttachOverlays);
              setTimeout(tryAttachOverlays, 120);
              setInterval(applyRouteSearchOverlayLayout, 350);
            })();
            </script>
            """,
            unsafe_allow_javascript=True,
        )

        _route_bar_action = st.session_state.pop("_route_bar_action", None)
        if _route_bar_action == "clear":
            log_event(LOGGER, "route_cleared")
            for k in ("route_sb_s", "route_sb_e"):
                st.session_state.pop(k, None)
            st.session_state["controls_start_choice"] = None
            st.session_state["controls_end_choice"] = None
            st.session_state["controls_start_q"] = ""
            st.session_state["controls_end_q"] = ""
            st.session_state["last_path"] = None
            st.session_state["last_route_result"] = None
            st.session_state["last_route_error"] = None
            st.rerun()

        if _route_bar_action == "compute":
            start_choice = st.session_state.get("controls_start_choice")
            end_choice = st.session_state.get("controls_end_choice")
            if start_choice and end_choice:
                a = start_choice["stop_id"]
                b = end_choice["stop_id"]
                log_event(LOGGER, "route_compute_clicked", start_stop_id=a, end_stop_id=b, mode=mode, use_lcc=use_lcc)
                a_info = component_info(G, a)
                b_info = component_info(G, b)
                res = shortest_path(G, a, b)
                if res["ok"]:
                    log_event(
                        LOGGER,
                        "route_compute_success",
                        start_stop_id=a,
                        end_stop_id=b,
                        path_length=len(res.get("path") or []),
                        distance_m=res.get("distance_m"),
                        time_s=res.get("time_s"),
                        transfers=res.get("transfers"),
                    )
                    st.session_state["last_path"] = res["path"]
                    st.session_state["last_route_result"] = res
                    st.session_state["last_route_error"] = None
                else:
                    details: list[str] = []
                    message = "Path computation failed."
                    if res["reason"] == "not_connected":
                        message = "No path: the two stops are not connected in this graph."
                        details = [
                            f"Start component size: {a_info.get('component_size', 0)}",
                            f"End component size: {b_info.get('component_size', 0)}",
                        ]
                    elif res["reason"] == "start_not_found":
                        message = "Start stop not found in the current graph."
                    elif res["reason"] == "end_not_found":
                        message = "End stop not found in the current graph."
                    log_event(
                        LOGGER,
                        "route_compute_failed",
                        start_stop_id=a,
                        end_stop_id=b,
                        reason=res.get("reason"),
                        start_component_size=a_info.get("component_size", 0),
                        end_component_size=b_info.get("component_size", 0),
                    )
                    st.session_state["last_route_error"] = {"message": message, "details": details}
                    st.session_state["last_route_result"] = None
                st.rerun()

    elif app_mode_ui == ui_shell.APP_MODE_KNOWLEDGE:
        ui_shell.render_knowledge_center()
    elif app_mode_ui == ui_shell.APP_MODE_VISUAL:
        ui_shell.render_visual_board_center()
    elif app_mode_ui == ui_shell.APP_MODE_MEMORY:
        ui_shell.render_memory_center()

ui_shell.render_atlas_chat_dock()
ui_shell.render_atlas_overlay_if_open()