import os

import streamlit as st
import streamlit.components.v1 as components

from src.core.cache_bundle import load_or_build_graph_bundle
from src.core.debug_log import debug_log_path, get_debug_logger, log_event
from src.core.poi_index import load_poi_lookup
from src.core.queries import component_info, search_stops, shortest_path
from src.core.tools import top_hubs
from src.viz.plot2d import plot_graph_2d
from src.viz.plot_mapbox import load_line_geometries, load_render_graph, render_mapbox_gl_html

st.set_page_config(page_title="CSPE Transport Graph", layout="wide")

PROJECT_ROOT = "."
BUNDLE_PATH = os.path.join("data", "derived", "routing", "graph_bundle.pkl")
STOP_POPUP_INDEX_PATH = os.path.join("data", "derived", "stops", "stop_popup_index.parquet")
NETWORK_MAPS_DIR = os.path.join("data", "derived", "maps")
POI_DATA_PATH = os.path.join("data", "normalized", "poi", "poi.parquet")
POI_TREE_PATH = os.path.join("data", "derived", "indexes", "poi_balltree.pkl")
POI_NPZ_PATH = os.path.join("data", "derived", "indexes", "poi_balltree.npz")
RENDER_GRAPH_PATHS = {
    "all": os.path.join("data", "derived", "render_graphs", "all.render_graph.json"),
    "bus": os.path.join("data", "derived", "render_graphs", "bus.render_graph.json"),
    "metro": os.path.join("data", "derived", "render_graphs", "metro.render_graph.json"),
    "rail": os.path.join("data", "derived", "render_graphs", "rail.render_graph.json"),
    "tram": os.path.join("data", "derived", "render_graphs", "tram.render_graph.json"),
}
MAPBOX_ENV_VARS = ("MAPBOX_TOKEN", "MAPBOX_API_KEY", "MAPBOX_ACCESS_TOKEN")
MAPBOX_BASEMAP_STYLES = {
    "Light": "mapbox://styles/mapbox/light-v11",
    "Dark": "mapbox://styles/mapbox/dark-v11",
}
DEFAULT_MAPBOX_STYLE = MAPBOX_BASEMAP_STYLES["Dark"]
LOGGER = get_debug_logger("cspe.app")
log_event(LOGGER, "app_imported", log_file=str(debug_log_path()))


@st.cache_resource(show_spinner=True)
def load_bundle(project_root: str, bundle_path: str, stop_popup_index_path: str):
    log_event(LOGGER, "load_bundle_called", project_root=project_root, bundle_path=bundle_path, stop_popup_index_path=stop_popup_index_path)
    return load_or_build_graph_bundle(project_root, cache_path=bundle_path, stop_popup_index_path=stop_popup_index_path)


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
    for env_name in MAPBOX_ENV_VARS:
        value = os.getenv(env_name)
        if value:
            log_event(LOGGER, "mapbox_token_found", env_name=env_name)
            return value, env_name
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
    [data-testid="stAppViewContainer"] {
        background: #1f1f1f;
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
    div[data-testid="stVerticalBlock"]:has(#map-zone-anchor) {
        position: relative;
        min-height: 100vh;
        overflow: visible;
        gap: 0 !important;
    }
    div[data-testid="stVerticalBlock"] > div:has(> #map-zone-anchor) {
        height: 0 !important;
        margin: 0 !important;
    }
    #controls-portal {
        position: fixed !important;
        top: 2.75rem !important;
        left: calc(100vw / 29 + 0.35rem) !important;
        width: 340px !important;
        height: 200px !important;
        max-height: 200px !important;
        z-index: 30 !important;
        pointer-events: auto !important;
        margin: 0 !important;
        padding: 0.5rem 0.65rem 0.55rem !important;
        box-sizing: border-box !important;
        overflow-x: hidden !important;
        overflow-y: auto !important;
        background: #1f1f1f !important;
        border: 1px solid rgba(255, 255, 255, 0.1) !important;
        border-radius: 0.85rem !important;
        box-shadow: 0 14px 40px rgba(0, 0, 0, 0.45);
    }
    #controls-portal > div {
        width: 100%;
        pointer-events: auto;
    }
    #controls-portal * {
        color: #e2e8f0;
    }
    #controls-portal [data-testid="stVerticalBlock"] {
        gap: 0.35rem !important;
    }
    #controls-portal [data-baseweb="select"] > div {
        background: rgba(15, 23, 42, 0.35) !important;
        color: #f8fafc !important;
        border: 1px solid rgba(255, 255, 255, 0.16) !important;
    }
    section.main div[data-testid="stHorizontalBlock"] > div[data-testid="column"]:last-child {
        color: #e2e8f0;
    }
    section.main div[data-testid="stHorizontalBlock"] > div[data-testid="column"]:last-child [data-baseweb="select"] > div,
    section.main div[data-testid="stHorizontalBlock"] > div[data-testid="column"]:last-child .stTextInput input,
    section.main div[data-testid="stHorizontalBlock"] > div[data-testid="column"]:last-child .stNumberInput input,
    section.main div[data-testid="stHorizontalBlock"] > div[data-testid="column"]:last-child .stTextArea textarea {
        background: rgba(15, 23, 42, 0.35) !important;
        color: #f8fafc !important;
        border: 1px solid rgba(255, 255, 255, 0.14) !important;
    }
    section.main div[data-testid="stHorizontalBlock"] > div[data-testid="column"]:last-child .stButton button,
    section.main div[data-testid="stHorizontalBlock"] > div[data-testid="column"]:last-child .stDownloadButton button {
        background: rgba(15, 23, 42, 0.45) !important;
        color: #f8fafc !important;
        border: 1px solid rgba(255, 255, 255, 0.16) !important;
    }
    section.main div[data-testid="stHorizontalBlock"] > div[data-testid="column"]:last-child [data-testid="stExpander"] {
        background: rgba(15, 23, 42, 0.25) !important;
        border: 1px solid rgba(255, 255, 255, 0.08) !important;
        border-radius: 0.65rem !important;
    }
    #route-bar-portal {
        position: fixed !important;
        bottom: 0.65rem !important;
        left: calc(100vw / 29 + 0.55rem) !important;
        width: calc(100vw * 21 / 29 - 1.1rem) !important;
        max-width: min(1180px, calc(100vw * 21 / 29 - 1.1rem)) !important;
        z-index: 29 !important;
        pointer-events: auto !important;
        margin: 0 !important;
        padding: 0.32rem 0.65rem 0.4rem !important;
        box-sizing: border-box !important;
        background: #1f1f1f !important;
        border: 1px solid rgba(255, 255, 255, 0.1) !important;
        border-radius: 0.85rem !important;
        box-shadow: 0 10px 40px rgba(0, 0, 0, 0.45);
    }
    #route-bar-portal > div {
        width: 100%;
    }
    #route-bar-portal [data-testid="stVerticalBlock"] {
        gap: 0.25rem !important;
    }
    #route-bar-portal label,
    #route-bar-portal [data-testid="stWidgetLabel"] p {
        font-size: 0.78rem !important;
        margin-bottom: 0.15rem !important;
    }
    #route-bar-portal [data-baseweb="select"] > div,
    #route-bar-portal .stTextInput input {
        background: rgba(15, 23, 42, 0.35) !important;
        color: #f8fafc !important;
        border: 1px solid rgba(255, 255, 255, 0.14) !important;
        min-height: 2.1rem !important;
    }
    #route-bar-portal .stButton button {
        background: rgba(15, 23, 42, 0.45) !important;
        color: #f8fafc !important;
        border: 1px solid rgba(255, 255, 255, 0.16) !important;
        min-height: 2.1rem !important;
        padding-top: 0.2rem !important;
        padding-bottom: 0.2rem !important;
        padding-left: 0.65rem !important;
        padding-right: 0.65rem !important;
        font-size: 0.8rem !important;
        white-space: nowrap !important;
        min-width: 5.75rem !important;
    }
    #route-bar-portal .stAlert {
        padding: 0.35rem 0.5rem !important;
        font-size: 0.8rem !important;
    }
    .cspe-side-panel {
        position: relative;
        min-height: 100vh;
        width: 100%;
        background: #1f1f1f;
    }
    .cspe-left-rail {
        min-height: 100vh;
        width: 100%;
        background: #1f1f1f;
    }
    .cspe-orb-slot {
        display: flex;
        justify-content: center;
        align-items: flex-start;
        padding-top: 5vh;
        width: 100%;
    }
    .cspe-orb-placeholder {
        position: relative;
        width: min(300px, 88%);
        aspect-ratio: 1 / 1;
        border-radius: 50%;
        background:
            radial-gradient(circle at 50% 50%, rgba(32, 205, 255, 0.06) 0%, rgba(32, 205, 255, 0.02) 26%, rgba(2, 6, 23, 0) 56%),
            radial-gradient(circle at 30% 28%, rgba(255, 255, 255, 0.08), transparent 18%),
            radial-gradient(circle at 50% 50%, rgba(15, 23, 42, 0.18), transparent 70%);
        border: 1px solid rgba(255, 255, 255, 0.08);
        overflow: hidden;
    }
    .cspe-orb-placeholder::before,
    .cspe-orb-placeholder::after,
    .cspe-orb-placeholder__ring,
    .cspe-orb-placeholder__ring-2,
    .cspe-orb-placeholder__network,
    .cspe-orb-placeholder__node,
    .cspe-orb-placeholder__line,
    .cspe-orb-placeholder__core {
        position: absolute;
        pointer-events: none;
    }
    .cspe-orb-placeholder::before,
    .cspe-orb-placeholder::after {
        content: "";
        inset: 0;
        border-radius: 50%;
    }
    .cspe-orb-placeholder::before {
        background:
            radial-gradient(circle at center, rgba(69, 211, 255, 0.16), transparent 45%),
            radial-gradient(circle at center, transparent 58%, rgba(120, 235, 255, 0.16) 59%, transparent 63%);
        filter: blur(0.5px);
    }
    .cspe-orb-placeholder::after {
        inset: 6%;
        border: 1px solid rgba(185, 235, 255, 0.16);
        box-shadow:
            inset 0 0 40px rgba(125, 221, 255, 0.07),
            0 0 50px rgba(72, 210, 255, 0.10);
    }
    .cspe-orb-placeholder__ring {
        inset: 10%;
        border-radius: 50%;
        border: 1px solid rgba(210, 244, 255, 0.16);
        box-shadow: inset 0 0 25px rgba(129, 230, 255, 0.05);
    }
    .cspe-orb-placeholder__ring-2 {
        inset: 22%;
        border-radius: 50%;
        border: 2px solid rgba(96, 208, 255, 0.50);
        box-shadow:
            0 0 18px rgba(96, 208, 255, 0.18),
            inset 0 0 24px rgba(96, 208, 255, 0.12);
    }
    .cspe-orb-placeholder__network {
        inset: 7%;
        border-radius: 50%;
        overflow: hidden;
        opacity: 0.82;
    }
    .cspe-orb-placeholder__line {
        height: 1px;
        transform-origin: left center;
        background: linear-gradient(90deg, rgba(143, 235, 255, 0.00), rgba(66, 211, 255, 0.46), rgba(143, 235, 255, 0.00));
        box-shadow: 0 0 8px rgba(66, 211, 255, 0.16);
    }
    .cspe-orb-placeholder__line--1 {
        top: 26%;
        left: 18%;
        width: 54%;
        transform: rotate(28deg);
    }
    .cspe-orb-placeholder__line--2 {
        top: 56%;
        left: 14%;
        width: 60%;
        transform: rotate(-34deg);
    }
    .cspe-orb-placeholder__line--3 {
        top: 48%;
        left: 30%;
        width: 34%;
        transform: rotate(74deg);
    }
    .cspe-orb-placeholder__line--4 {
        top: 32%;
        left: 40%;
        width: 26%;
        transform: rotate(-68deg);
    }
    .cspe-orb-placeholder__line--5 {
        top: 66%;
        left: 28%;
        width: 38%;
        transform: rotate(18deg);
    }
    .cspe-orb-placeholder__node {
        width: 6px;
        height: 6px;
        border-radius: 50%;
        background: #76ddff;
        box-shadow: 0 0 10px rgba(118, 221, 255, 0.55);
    }
    .cspe-orb-placeholder__node--1 { top: 24%; left: 28%; }
    .cspe-orb-placeholder__node--2 { top: 34%; left: 62%; }
    .cspe-orb-placeholder__node--3 { top: 52%; left: 22%; }
    .cspe-orb-placeholder__node--4 { top: 61%; left: 55%; }
    .cspe-orb-placeholder__node--5 { top: 43%; left: 46%; }
    .cspe-orb-placeholder__node--6 { top: 71%; left: 39%; }
    .cspe-orb-placeholder__node--7 { top: 30%; left: 48%; }
    .cspe-orb-placeholder__node--8 { top: 57%; left: 70%; }
    .cspe-orb-placeholder__node--9 { top: 45%; left: 33%; }
    .cspe-orb-placeholder__node--10 { top: 38%; left: 18%; }
    .cspe-orb-placeholder__node--11 { top: 68%; left: 62%; }
    .cspe-orb-placeholder__node--12 { top: 20%; left: 54%; }
    .cspe-orb-placeholder__node--center {
        top: 50%;
        left: 50%;
        width: 9px;
        height: 9px;
        transform: translate(-50%, -50%);
        background: #9ce9ff;
        box-shadow: 0 0 16px rgba(156, 233, 255, 0.75);
    }
    .cspe-orb-placeholder__core {
        inset: 33%;
        border-radius: 50%;
        border: 1px solid rgba(202, 245, 255, 0.18);
        box-shadow:
            inset 0 0 26px rgba(81, 203, 255, 0.08),
            0 0 22px rgba(81, 203, 255, 0.08);
    }
    iframe[title="st.iframe"] {
        border: none !important;
        border-radius: 0 !important;
        display: block !important;
        height: 100vh !important;
    }
    div[data-baseweb="popover"] {
        z-index: 100010 !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

bundle = load_bundle(PROJECT_ROOT, BUNDLE_PATH, STOP_POPUP_INDEX_PATH)
pos_all = bundle["pos_all"]
pos = pos_all
graphs = bundle["graphs"]
graphs_lcc = bundle["graphs_lcc"]


def _fmt(opt):
    if not opt:
        return ""
    name = opt["stop_name"] if opt["stop_name"] else opt["stop_id"]
    if opt.get("line"):
        return f"{name} — {opt['line']}  |  {opt['stop_id']}"
    return f"{name}  |  {opt['stop_id']}"


def _route_bar_compute_ready() -> bool:
    sq = (st.session_state.get("controls_start_q") or "").strip()
    eq = (st.session_state.get("controls_end_q") or "").strip()
    if not sq or not eq:
        return False
    return st.session_state.get("controls_start_choice") is not None and st.session_state.get("controls_end_choice") is not None


viz_mode_options = ["Geographic Mapbox", "Abstract 2D graph", "3D network"]
mode_options = ["all", "metro", "rail", "tram", "bus", "other"]

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
poi_category_key = st.session_state.get("controls_poi_category_key", "All")
poi_category_key_3d = st.session_state.get("controls_poi_category_key_3d", "All")
current_path = st.session_state.get("last_path")
last_route_result = st.session_state.get("last_route_result")
last_route_error = st.session_state.get("last_route_error")

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

left_rail_col, center_col, right_col = st.columns([1, 21, 7], gap="large")

with left_rail_col:
    st.markdown('<div class="cspe-left-rail"></div>', unsafe_allow_html=True)

with right_col:
    st.markdown(
        """
        <div class="cspe-side-panel">
          <div class="cspe-orb-slot">
            <div class="cspe-orb-placeholder">
              <div class="cspe-orb-placeholder__ring"></div>
              <div class="cspe-orb-placeholder__ring-2"></div>
              <div class="cspe-orb-placeholder__network">
                <div class="cspe-orb-placeholder__line cspe-orb-placeholder__line--1"></div>
                <div class="cspe-orb-placeholder__line cspe-orb-placeholder__line--2"></div>
                <div class="cspe-orb-placeholder__line cspe-orb-placeholder__line--3"></div>
                <div class="cspe-orb-placeholder__line cspe-orb-placeholder__line--4"></div>
                <div class="cspe-orb-placeholder__line cspe-orb-placeholder__line--5"></div>
                <div class="cspe-orb-placeholder__node cspe-orb-placeholder__node--1"></div>
                <div class="cspe-orb-placeholder__node cspe-orb-placeholder__node--2"></div>
                <div class="cspe-orb-placeholder__node cspe-orb-placeholder__node--3"></div>
                <div class="cspe-orb-placeholder__node cspe-orb-placeholder__node--4"></div>
                <div class="cspe-orb-placeholder__node cspe-orb-placeholder__node--5"></div>
                <div class="cspe-orb-placeholder__node cspe-orb-placeholder__node--6"></div>
                <div class="cspe-orb-placeholder__node cspe-orb-placeholder__node--7"></div>
                <div class="cspe-orb-placeholder__node cspe-orb-placeholder__node--8"></div>
                <div class="cspe-orb-placeholder__node cspe-orb-placeholder__node--9"></div>
                <div class="cspe-orb-placeholder__node cspe-orb-placeholder__node--10"></div>
                <div class="cspe-orb-placeholder__node cspe-orb-placeholder__node--11"></div>
                <div class="cspe-orb-placeholder__node cspe-orb-placeholder__node--12"></div>
                <div class="cspe-orb-placeholder__node cspe-orb-placeholder__node--center"></div>
              </div>
              <div class="cspe-orb-placeholder__core"></div>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

with center_col:
    st.markdown('<div id="map-zone-anchor"></div>', unsafe_allow_html=True)
    if viz_mode == "Abstract 2D graph":
        log_event(LOGGER, "render_2d_graph_start", mode=mode, use_lcc=use_lcc, node_count=G.number_of_nodes(), edge_count=G.number_of_edges())
        fig = plot_graph_2d(
            G,
            pos,
            title="",
            path=current_path,
            zoom_to_path=True,
        )
        st.pyplot(fig, use_container_width=True)
    elif viz_mode == "Geographic Mapbox":
        token, _token_env = get_mapbox_token()
        if token is None:
            st.warning("Mapbox mode needs a token in `MAPBOX_TOKEN`, `MAPBOX_API_KEY`, or `MAPBOX_ACCESS_TOKEN`.")
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
            st.warning("Mapbox mode needs a token in `MAPBOX_TOKEN`, `MAPBOX_API_KEY`, or `MAPBOX_ACCESS_TOKEN`.")
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
                poi_radius_m=float(poi_radius_m),
                poi_limit=int(poi_limit),
                poi_category_key=None if poi_category_key == "All" else poi_category_key,
                pitched_view=True,
                show_3d_buildings=True,
                height_px=1100,
            )
            components.html(map_html, height=1100)

    overlay_host = st.container()
    with overlay_host:
        st.markdown('<div id="controls-overlay-anchor"></div>', unsafe_allow_html=True)
        viz_mode = st.selectbox(
            "Visualization",
            viz_mode_options,
            index=viz_mode_options.index(viz_mode) if viz_mode in viz_mode_options else 0,
            key="controls_viz_mode",
        )
        mode = st.selectbox(
            "Mode",
            mode_options,
            index=mode_options.index(mode) if mode in mode_options else 1,
            key="controls_mode",
        )
        st.markdown('<div id="controls-overlay-end"></div>', unsafe_allow_html=True)

    compute_clicked = False
    clear_clicked = False

    route_bar_host = st.container()
    with route_bar_host:
        st.markdown('<div id="route-bar-anchor"></div>', unsafe_allow_html=True)
        rb_main = st.columns([4.2, 4.2, 1.35, 1.35])
        with rb_main[0]:
            start_q = st.text_input(
                "Start stop",
                placeholder="Start stop",
                key="controls_start_q",
                label_visibility="collapsed",
            )
        with rb_main[1]:
            end_q = st.text_input(
                "End stop",
                placeholder="End stop",
                key="controls_end_q",
                label_visibility="collapsed",
            )
        with rb_main[2]:
            compute_clicked = st.button(
                "Compute",
                type="primary",
                disabled=not _route_bar_compute_ready(),
                use_container_width=True,
                key="controls_compute_path",
            )
        with rb_main[3]:
            clear_clicked = st.button("Clear", use_container_width=True, key="controls_clear_path")

    start_matches = search_stops(G, start_q, limit=40, mode=mode) if start_q else []
    end_matches = search_stops(G, end_q, limit=40, mode=mode) if end_q else []

    with route_bar_host:
        if start_q or end_q:
            rb_pick = st.columns(2)
            with rb_pick[0]:
                if start_q:
                    if start_matches:
                        st.selectbox(
                            "Select start",
                            options=start_matches,
                            format_func=_fmt,
                            index=0,
                            key="controls_start_choice",
                            label_visibility="collapsed",
                        )
                    else:
                        st.caption("No start matches")
            with rb_pick[1]:
                if end_q:
                    if end_matches:
                        st.selectbox(
                            "Select end",
                            options=end_matches,
                            format_func=_fmt,
                            index=0,
                            key="controls_end_choice",
                            label_visibility="collapsed",
                        )
                    else:
                        st.caption("No end matches")

    start_choice = st.session_state.get("controls_start_choice")
    end_choice = st.session_state.get("controls_end_choice")

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
            host.style.overflow = 'auto';
            return true;
          };

          const attachRouteBarHost = () => {
            const anchor = document.getElementById('route-bar-anchor');
            if (!anchor) {
              return false;
            }
            let host = anchor.parentElement;
            while (host) {
              const inputs = host.querySelectorAll('[data-testid="stTextInput"]');
              if (inputs.length >= 2) {
                break;
              }
              host = host.parentElement;
              if (!host || host.tagName === 'BODY') {
                return false;
              }
            }
            const stale = document.getElementById('route-bar-portal');
            if (stale && stale !== host) {
              stale.removeAttribute('id');
            }
            host.id = 'route-bar-portal';
            host.style.margin = '0';
            host.style.overflow = 'visible';
            return true;
          };

          const tryAttachOverlays = () => {
            attachOverlayHost();
            attachRouteBarHost();
          };
          tryAttachOverlays();
          requestAnimationFrame(tryAttachOverlays);
        })();
        </script>
        """,
        unsafe_allow_javascript=True,
    )

with right_col:
    use_lcc = st.checkbox("Largest connected component", value=use_lcc, key="controls_use_lcc")

    with st.expander("Network stats", expanded=True):
        st.write(f"Nodes: {G.number_of_nodes()}")
        st.write(f"Edges: {G.number_of_edges()}")

    with st.expander("Top hubs", expanded=False):
        for hub in top_hubs(G, k=10):
            name = hub["stop_name"] if hub["stop_name"] else hub["stop_id"]
            st.write(f"{name} — degree={hub['degree']}")

    st.subheader("View options")
    if viz_mode == "Abstract 2D graph":
        st.checkbox("Zoom to route", value=True, key="controls_zoom_to_path")
    elif viz_mode == "Geographic Mapbox":
        st.checkbox("Show transfer edges", value=show_transfers_map, key="controls_show_transfers_map")
        st.checkbox(
            "Show path geometry debug",
            value=show_path_match_debug,
            disabled=not current_path,
            key="controls_show_path_match_debug",
        )
        st.markdown("#### Nearby POIs")
        st.slider("POI radius (m)", min_value=100, max_value=1000, value=poi_radius_m, step=50, key="controls_poi_radius_m")
        st.slider("POIs shown per station", min_value=5, max_value=200, value=poi_limit, step=5, key="controls_poi_limit")
        st.caption("Dense areas can fill the result cap before reaching the full radius.")
        st.selectbox(
            "POI category",
            ["All", "amenity", "shop", "tourism", "leisure"],
            index=["All", "amenity", "shop", "tourism", "leisure"].index(poi_category_key)
            if poi_category_key in ["All", "amenity", "shop", "tourism", "leisure"]
            else 0,
            key="controls_poi_category_key",
        )
    else:
        st.checkbox("Show transfer edges", value=show_transfers_network_3d, key="controls_show_transfers_network_3d")
        st.checkbox(
            "Show path geometry debug",
            value=show_path_match_debug_3d,
            disabled=not current_path,
            key="controls_show_path_match_debug_3d",
        )
        st.markdown("#### Nearby POIs")
        st.slider("POI radius (m)", min_value=100, max_value=1000, value=poi_radius_m_3d, step=50, key="controls_poi_radius_m_3d")
        st.slider("POIs shown per station", min_value=5, max_value=200, value=poi_limit_3d, step=5, key="controls_poi_limit_3d")
        st.caption("Dense areas can fill the result cap before reaching the full radius.")
        st.selectbox(
            "POI category",
            ["All", "amenity", "shop", "tourism", "leisure"],
            index=["All", "amenity", "shop", "tourism", "leisure"].index(poi_category_key_3d)
            if poi_category_key_3d in ["All", "amenity", "shop", "tourism", "leisure"]
            else 0,
            key="controls_poi_category_key_3d",
        )

    if last_route_error:
        st.error(last_route_error["message"])
        for line in last_route_error.get("details", []):
            st.write(line)

    if last_route_result and current_path:
        with st.expander("Current route", expanded=True):
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

with center_col:
    if clear_clicked:
        log_event(LOGGER, "route_cleared")
        st.session_state["last_path"] = None
        st.session_state["last_route_result"] = None
        st.session_state["last_route_error"] = None
        st.rerun()

    if compute_clicked and start_choice and end_choice:
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