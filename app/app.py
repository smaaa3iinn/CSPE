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
    @import url("https://fonts.googleapis.com/css2?family=Rajdhani:wght@500;600;700&display=swap");
    [data-testid="stAppViewContainer"] {
        background: #06080a;
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
        overflow-y: hidden !important;
        background: #12161c !important;
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
        gap: 0.12rem !important;
    }
    #controls-portal p.cspe-overlay-title {
        font-family: "Rajdhani", "Segoe UI", sans-serif !important;
        font-size: 0.82rem !important;
        font-weight: 600 !important;
        line-height: 1.15 !important;
        margin: 0.15rem 0 0.08rem 0 !important;
        padding: 0 !important;
        color: #c8d0dc !important;
        opacity: 1 !important;
        letter-spacing: 0.11em !important;
        text-transform: uppercase !important;
    }
    #controls-portal div[data-testid="stHorizontalBlock"] {
        gap: 0.2rem !important;
    }
    #controls-portal .stButton > button {
        padding: 0.18rem 0.2rem !important;
        font-size: 0.68rem !important;
        line-height: 1.15 !important;
        min-height: 1.75rem !important;
        border-radius: 0.4rem !important;
    }
    #controls-portal .stButton > button[kind="primary"],
    #controls-portal .stButton > button[data-testid="baseButton-primary"] {
        background: #3a414a !important;
        background-image: none !important;
        color: #f8fafc !important;
        border: 1px solid rgba(255, 255, 255, 0.14) !important;
        box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.06) !important;
    }
    #controls-portal .stButton > button[kind="primary"]:hover,
    #controls-portal .stButton > button[kind="primary"]:focus-visible,
    #controls-portal .stButton > button[data-testid="baseButton-primary"]:hover,
    #controls-portal .stButton > button[data-testid="baseButton-primary"]:focus-visible {
        background: #484f59 !important;
        background-image: none !important;
        border-color: rgba(255, 255, 255, 0.2) !important;
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
        background: #12161c !important;
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
        color: #e2e8f0;
        font-size: 0.65rem;
        box-sizing: border-box !important;
        overflow-x: clip;
        background: #12161c !important;
    }
    section.main
        div[data-testid="stHorizontalBlock"]:has(.cspe-left-rail)
        > div[data-testid="column"]:first-child {
        background: #12161c !important;
    }
    section.main
        div[data-testid="stHorizontalBlock"]
        > div[data-testid="column"]:has(#cspe-right-settings-anchor)
        > div[data-testid="stVerticalBlock"] {
        gap: 0.18rem !important;
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
        font-size: 0.65rem !important;
        font-weight: 500 !important;
        line-height: 1.15 !important;
        letter-spacing: 0.06em !important;
        text-transform: uppercase !important;
        color: rgba(226, 232, 240, 0.48) !important;
        margin-bottom: 0.06rem !important;
    }
    div[data-testid="column"]:has(#cspe-right-settings-anchor) [data-testid="stMarkdownContainer"] p,
    div[data-testid="column"]:has(#cspe-right-settings-anchor) [data-testid="stMarkdownContainer"] li {
        font-family: "Rajdhani", "Segoe UI", sans-serif !important;
        font-size: 0.7rem !important;
        line-height: 1.25 !important;
        margin-bottom: 0.08rem !important;
        color: rgba(226, 232, 240, 0.88) !important;
    }
    div[data-testid="column"]:has(#cspe-right-settings-anchor) h3 {
        font-size: 0.68rem !important;
        margin: 0.12rem 0 0.06rem 0 !important;
        line-height: 1.15 !important;
    }
    div[data-testid="column"]:has(#cspe-right-settings-anchor) [data-testid="stMarkdownContainer"] h4 {
        font-size: 0.6rem !important;
        margin: 0.1rem 0 0.04rem 0 !important;
        line-height: 1.15 !important;
    }
    div[data-testid="column"]:has(#cspe-right-settings-anchor) [data-testid="stCaptionContainer"] p {
        font-family: "Rajdhani", "Segoe UI", sans-serif !important;
        font-size: 0.58rem !important;
        margin-top: 0 !important;
        line-height: 1.2 !important;
        letter-spacing: 0.04em !important;
        color: rgba(226, 232, 240, 0.42) !important;
    }
    div[data-testid="column"]:has(#cspe-right-settings-anchor) [data-baseweb="select"] > div {
        background: rgba(15, 23, 42, 0.35) !important;
        color: #e2e8f0 !important;
        border: 1px solid rgba(255, 255, 255, 0.12) !important;
        min-height: 1.5rem !important;
        font-family: "Rajdhani", "Segoe UI", sans-serif !important;
        font-size: 0.65rem !important;
        padding-top: 0.1rem !important;
        padding-bottom: 0.1rem !important;
    }
    div[data-testid="column"]:has(#cspe-right-settings-anchor) [data-testid="stExpander"] {
        background: transparent !important;
        border: none !important;
        border-radius: 0 !important;
        box-shadow: none !important;
    }
    div[data-testid="column"]:has(#cspe-right-settings-anchor) [data-testid="stExpander"] summary {
        padding: 0.15rem 0 !important;
        min-height: unset !important;
        background: transparent !important;
    }
    div[data-testid="column"]:has(#cspe-right-settings-anchor) [data-testid="stExpander"] summary,
    div[data-testid="column"]:has(#cspe-right-settings-anchor) [data-testid="stExpander"] summary p {
        font-family: "Rajdhani", "Segoe UI", sans-serif !important;
        font-size: 1.17rem !important;
        font-weight: 600 !important;
        line-height: 1.2 !important;
        letter-spacing: 0.1em !important;
        color: rgba(226, 232, 240, 0.72) !important;
        text-transform: uppercase !important;
    }
    div[data-testid="column"]:has(#cspe-right-settings-anchor) [data-testid="stExpander"] details {
        font-family: "Rajdhani", "Segoe UI", sans-serif !important;
        font-size: 0.68rem !important;
    }
    div[data-testid="column"]:has(#cspe-right-settings-anchor) [data-testid="stExpander"] [data-testid="stExpanderDetails"] {
        padding: 0.2rem 0 0.35rem 0 !important;
        background: transparent !important;
    }
    div[data-testid="column"]:has(#cspe-right-settings-anchor) [data-baseweb="slider"] {
        padding-top: 0.08rem !important;
        padding-bottom: 0.1rem !important;
    }
    div[data-testid="column"]:has(#cspe-right-settings-anchor) .stSlider label p {
        font-family: "Rajdhani", "Segoe UI", sans-serif !important;
        font-size: 0.62rem !important;
    }
    div[data-testid="column"]:has(#cspe-right-settings-anchor) .stCheckbox {
        padding: 0.02rem 0 !important;
        gap: 0.28rem !important;
    }
    div[data-testid="column"]:has(#cspe-right-settings-anchor) .stButton button,
    div[data-testid="column"]:has(#cspe-right-settings-anchor) .stDownloadButton button {
        background: rgba(15, 23, 42, 0.45) !important;
        color: #e2e8f0 !important;
        border: 1px solid rgba(255, 255, 255, 0.14) !important;
        font-family: "Rajdhani", "Segoe UI", sans-serif !important;
        font-size: 0.65rem !important;
        font-weight: 600 !important;
        letter-spacing: 0.08em !important;
        text-transform: uppercase !important;
        min-height: 1.55rem !important;
        padding: 0.14rem 0.4rem !important;
    }
    div[data-testid="column"]:has(#cspe-right-settings-anchor) [data-testid="stAlert"] {
        padding: 0.28rem 0.35rem !important;
        font-family: "Rajdhani", "Segoe UI", sans-serif !important;
        background: transparent !important;
        border: 1px solid rgba(255, 255, 255, 0.1) !important;
    }
    div[data-testid="column"]:has(#cspe-right-settings-anchor) [data-testid="stAlert"] p {
        font-size: 0.68rem !important;
        line-height: 1.25 !important;
    }
    div[data-testid="column"]:has(#cspe-right-settings-anchor) [data-baseweb="notification"] {
        font-family: "Rajdhani", "Segoe UI", sans-serif !important;
    }
    div[data-testid="column"]:has(#cspe-right-settings-anchor) .stSuccess,
    div[data-testid="column"]:has(#cspe-right-settings-anchor) [data-testid="stSuccess"] {
        background: transparent !important;
        border: 1px solid rgba(74, 222, 128, 0.25) !important;
    }
    div[data-testid="column"]:has(#cspe-right-settings-anchor) .stSuccess p,
    div[data-testid="column"]:has(#cspe-right-settings-anchor) [data-testid="stSuccess"] p {
        font-family: "Rajdhani", "Segoe UI", sans-serif !important;
        font-size: 0.7rem !important;
        font-weight: 600 !important;
        letter-spacing: 0.05em !important;
        color: rgba(226, 232, 240, 0.92) !important;
    }
    div[data-testid="column"]:has(#cspe-right-settings-anchor) textarea,
    div[data-testid="column"]:has(#cspe-right-settings-anchor) pre {
        font-family: "Rajdhani", "Segoe UI", monospace !important;
        font-size: 0.62rem !important;
        line-height: 1.22 !important;
        max-height: 6.5rem !important;
        overflow-y: auto !important;
        color: rgba(226, 232, 240, 0.9) !important;
        background: rgba(15, 23, 42, 0.35) !important;
        border: 1px solid rgba(255, 255, 255, 0.08) !important;
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
        background: #12161c !important;
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
    #route-bar-portal .stButton > button[kind="primary"],
    #route-bar-portal .stButton > button[data-testid="baseButton-primary"] {
        background: #3a414a !important;
        background-image: none !important;
        border: 1px solid rgba(255, 255, 255, 0.14) !important;
        box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.06) !important;
    }
    #route-bar-portal .stButton > button[kind="primary"]:hover,
    #route-bar-portal .stButton > button[kind="primary"]:focus-visible,
    #route-bar-portal .stButton > button[data-testid="baseButton-primary"]:hover,
    #route-bar-portal .stButton > button[data-testid="baseButton-primary"]:focus-visible {
        background: #484f59 !important;
        border-color: rgba(255, 255, 255, 0.2) !important;
    }
    #route-bar-portal .stAlert {
        padding: 0.35rem 0.5rem !important;
        font-size: 0.8rem !important;
    }
    .cspe-side-panel {
        position: relative;
        width: 100%;
        background: #12161c;
    }
    /* Orb row sits full-width above guttered controls (see layout in app). */
    .cspe-orb-slot--bleed {
        margin: 0 0 0.25rem 0;
        box-sizing: border-box;
    }
    .cspe-net-stats {
        margin: 0.25rem 0 0.45rem 0;
        padding: 0;
        background: transparent !important;
        border: none !important;
        box-shadow: none !important;
    }
    .cspe-rail-title {
        font-family: "Rajdhani", "Segoe UI", sans-serif;
        font-size: 1.31rem !important;
        font-weight: 600;
        letter-spacing: 0.14em;
        color: rgba(226, 232, 240, 0.72) !important;
        text-transform: uppercase;
        margin: 0 0 0.55rem 0;
        line-height: 1.2;
    }
    .cspe-rail-title--tight {
        margin-bottom: 0.35rem !important;
    }
    .cspe-rail-title--spaced {
        margin-top: 0.5rem !important;
        margin-bottom: 0.45rem !important;
    }
    .cspe-rail-subtitle {
        font-family: "Rajdhani", "Segoe UI", sans-serif;
        font-size: 0.68rem !important;
        font-weight: 600;
        letter-spacing: 0.12em;
        color: rgba(226, 232, 240, 0.52) !important;
        text-transform: uppercase;
        margin: 0.32rem 0 0.18rem 0;
        line-height: 1.2;
    }
    .cspe-net-stats__grid {
        display: grid;
        grid-template-columns: 1fr 1fr;
        column-gap: 1.5rem;
        row-gap: 0.28rem;
        align-items: start;
    }
    .cspe-net-stats__item {
        min-width: 0;
    }
    .cspe-net-stats__label {
        font-family: "Rajdhani", "Segoe UI", sans-serif;
        font-size: 0.75rem !important;
        font-weight: 500;
        color: rgba(226, 232, 240, 0.45) !important;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        margin: 0 0 0.1rem 0;
        line-height: 1.15;
    }
    .cspe-net-stats__value {
        font-family: "Rajdhani", "Segoe UI", sans-serif;
        font-size: 3.06rem !important;
        font-weight: 600;
        color: #e2e8f0 !important;
        line-height: 1.02;
        letter-spacing: 0.02em;
        font-variant-numeric: tabular-nums;
    }
    div[data-testid="column"]:has(#cspe-right-settings-anchor) [data-testid="stMarkdownContainer"]:has(.cspe-net-stats) p,
    div[data-testid="column"]:has(#cspe-right-settings-anchor) [data-testid="stMarkdownContainer"]:has(.cspe-rail-title) p,
    div[data-testid="column"]:has(#cspe-right-settings-anchor) [data-testid="stMarkdownContainer"]:has(.cspe-rail-subtitle) p {
        margin: 0 !important;
    }
    .cspe-left-rail {
        min-height: 100vh;
        width: 100%;
        background: #12161c;
    }
    .cspe-orb-slot {
        display: flex;
        justify-content: center;
        align-items: flex-start;
        padding-top: 1.25vh;
        width: 100%;
    }
    .cspe-orb-placeholder {
        position: relative;
        width: min(200px, 76%);
        aspect-ratio: 1 / 1;
        border-radius: 50%;
        background: #12161c;
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
        background: none;
        filter: none;
    }
    .cspe-orb-placeholder::after {
        inset: 6%;
        border: 1px solid rgba(185, 235, 255, 0.12);
        box-shadow: inset 0 0 28px rgba(125, 221, 255, 0.04);
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


# Sentinel option when multiple IDFM rows match the same search string.
_ROUTE_DROPDOWN_PLACEHOLDER = {"stop_id": "__route_pick__", "stop_name": "Pick line…", "line": None}


def _route_is_pick_placeholder(opt) -> bool:
    return bool(opt) and opt.get("stop_id") == "__route_pick__"


def _route_is_real_stop(opt) -> bool:
    return bool(opt) and not _route_is_pick_placeholder(opt)


def _route_dropdown_label(opt) -> str:
    if _route_is_pick_placeholder(opt):
        return "Pick line…"
    return _fmt(opt)


def _route_choice_equal(a, b) -> bool:
    if not a or not b:
        return False
    return a.get("stop_id") == b.get("stop_id") and a.get("line") == b.get("line")


def _route_choice_in_matches(choice, matches: list) -> bool:
    if not choice or not matches:
        return False
    return any(_route_choice_equal(choice, m) for m in matches)


def _route_index_for_choice(matches: list, choice) -> int:
    if not matches:
        return 0
    if not choice:
        return 0
    for i, m in enumerate(matches):
        if _route_choice_equal(choice, m):
            return i
    return 0


def _sync_start_bar_from_pick() -> None:
    ch = st.session_state.get("controls_start_choice")
    if _route_is_real_stop(ch):
        st.session_state["controls_start_q"] = _fmt(ch)


def _sync_end_bar_from_pick() -> None:
    ch = st.session_state.get("controls_end_choice")
    if _route_is_real_stop(ch):
        st.session_state["controls_end_q"] = _fmt(ch)


def _route_prune_or_reset_pick(
    matches: list,
    key: str,
) -> None:
    ch = st.session_state.get(key)
    if ch is None:
        return
    if _route_is_pick_placeholder(ch):
        if len(matches) <= 1:
            st.session_state.pop(key, None)
        return
    if not _route_choice_in_matches(ch, matches):
        st.session_state.pop(key, None)


def _route_bar_compute_ready() -> bool:
    sq = (st.session_state.get("controls_start_q") or "").strip()
    eq = (st.session_state.get("controls_end_q") or "").strip()
    if not sq or not eq:
        return False
    return _route_is_real_stop(st.session_state.get("controls_start_choice")) and _route_is_real_stop(
        st.session_state.get("controls_end_choice")
    )


viz_mode_options = ["Geographic Mapbox", "Abstract 2D graph", "3D network"]
mode_options = ["all", "metro", "rail", "tram", "bus", "other"]
OVERLAY_VIZ_LABELS = ["Geographic", "2D graph", "3D network"]
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


def _render_poi_category_rail_buttons(state_key: str) -> None:
    valid = {v for v, _ in POI_CATEGORY_CHOICES}
    cur = st.session_state.get(state_key, "All")
    if cur not in valid:
        cur = "All"
        st.session_state[state_key] = cur
    st.markdown('<div class="cspe-rail-subtitle">Category</div>', unsafe_allow_html=True)
    p1 = st.columns(3, gap="small")
    p2 = st.columns(3, gap="small")
    for idx, (val, label) in enumerate(POI_CATEGORY_CHOICES):
        row = p1 if idx < 3 else p2
        with row[idx % 3]:
            if st.button(
                label,
                key=f"{state_key}__btn__{val}",
                use_container_width=True,
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
    vcols = st.columns(3, gap="small")
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
        <div class="cspe-orb-slot cspe-orb-slot--bleed">
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
        """,
        unsafe_allow_html=True,
    )
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
        use_lcc = st.checkbox("Largest connected component", value=use_lcc, key="controls_use_lcc")

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

        st.markdown(
            '<div class="cspe-rail-title cspe-rail-title--spaced">[ VIEW OPTIONS ]</div>',
            unsafe_allow_html=True,
        )
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
            st.markdown(
                '<div class="cspe-rail-title cspe-rail-title--tight">[ NEARBY POIS ]</div>',
                unsafe_allow_html=True,
            )
            st.slider("POI radius (m)", min_value=100, max_value=1000, value=poi_radius_m, step=50, key="controls_poi_radius_m")
            st.slider("POIs shown per station", min_value=5, max_value=200, value=poi_limit, step=5, key="controls_poi_limit")
            st.caption("Dense areas can fill the result cap before reaching the full radius.")
            _render_poi_category_rail_buttons("controls_poi_category_key")
        else:
            st.checkbox("Show transfer edges", value=show_transfers_network_3d, key="controls_show_transfers_network_3d")
            st.checkbox(
                "Show path geometry debug",
                value=show_path_match_debug_3d,
                disabled=not current_path,
                key="controls_show_path_match_debug_3d",
            )
            st.markdown(
                '<div class="cspe-rail-title cspe-rail-title--tight">[ NEARBY POIS ]</div>',
                unsafe_allow_html=True,
            )
            st.slider("POI radius (m)", min_value=100, max_value=1000, value=poi_radius_m_3d, step=50, key="controls_poi_radius_m_3d")
            st.slider("POIs shown per station", min_value=5, max_value=200, value=poi_limit_3d, step=5, key="controls_poi_limit_3d")
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
        _render_map_controls_overlay()
        st.markdown('<div id="controls-overlay-end"></div>', unsafe_allow_html=True)

    compute_clicked = False
    clear_clicked = False

    route_bar_host = st.container()
    with route_bar_host:
        st.markdown('<div id="route-bar-anchor"></div>', unsafe_allow_html=True)

        sq0 = (st.session_state.get("controls_start_q") or "").strip()
        eq0 = (st.session_state.get("controls_end_q") or "").strip()
        start_matches = search_stops(G, sq0, limit=40, mode=mode) if sq0 else []
        end_matches = search_stops(G, eq0, limit=40, mode=mode) if eq0 else []

        _route_prune_or_reset_pick(start_matches, "controls_start_choice")
        _route_prune_or_reset_pick(end_matches, "controls_end_choice")

        if len(start_matches) == 1:
            only_s = start_matches[0]
            sch = st.session_state.get("controls_start_choice")
            if sch is None or not _route_choice_equal(sch, only_s):
                st.session_state["controls_start_choice"] = only_s
                st.session_state["controls_start_q"] = _fmt(only_s)
        if len(end_matches) == 1:
            only_e = end_matches[0]
            ech = st.session_state.get("controls_end_choice")
            if ech is None or not _route_choice_equal(ech, only_e):
                st.session_state["controls_end_choice"] = only_e
                st.session_state["controls_end_q"] = _fmt(only_e)

        rb_main = st.columns([4.2, 4.2, 1.35, 1.35])
        with rb_main[0]:
            s_row = st.columns([2.65, 1.55], gap="small")
            with s_row[0]:
                st.text_input(
                    "Start stop",
                    placeholder="Start stop",
                    key="controls_start_q",
                    label_visibility="collapsed",
                )
            with s_row[1]:
                if sq0 and start_matches:
                    sc_cur = st.session_state.get("controls_start_choice")
                    if len(start_matches) == 1:
                        s_opts = start_matches
                        ix_s = 0
                    else:
                        s_opts = [_ROUTE_DROPDOWN_PLACEHOLDER] + start_matches
                        if _route_is_pick_placeholder(sc_cur) or sc_cur is None:
                            ix_s = 0
                        elif _route_choice_in_matches(sc_cur, start_matches):
                            ix_s = 1 + _route_index_for_choice(start_matches, sc_cur)
                        else:
                            ix_s = 0
                    st.selectbox(
                        "Start IDFM",
                        options=s_opts,
                        format_func=_route_dropdown_label,
                        index=min(ix_s, len(s_opts) - 1),
                        key="controls_start_choice",
                        label_visibility="collapsed",
                        on_change=_sync_start_bar_from_pick,
                    )
                elif sq0:
                    st.caption("No match")
        with rb_main[1]:
            e_row = st.columns([2.65, 1.55], gap="small")
            with e_row[0]:
                st.text_input(
                    "End stop",
                    placeholder="End stop",
                    key="controls_end_q",
                    label_visibility="collapsed",
                )
            with e_row[1]:
                if eq0 and end_matches:
                    ec_cur = st.session_state.get("controls_end_choice")
                    if len(end_matches) == 1:
                        e_opts = end_matches
                        ix_e = 0
                    else:
                        e_opts = [_ROUTE_DROPDOWN_PLACEHOLDER] + end_matches
                        if _route_is_pick_placeholder(ec_cur) or ec_cur is None:
                            ix_e = 0
                        elif _route_choice_in_matches(ec_cur, end_matches):
                            ix_e = 1 + _route_index_for_choice(end_matches, ec_cur)
                        else:
                            ix_e = 0
                    st.selectbox(
                        "End IDFM",
                        options=e_opts,
                        format_func=_route_dropdown_label,
                        index=min(ix_e, len(e_opts) - 1),
                        key="controls_end_choice",
                        label_visibility="collapsed",
                        on_change=_sync_end_bar_from_pick,
                    )
                elif eq0:
                    st.caption("No match")
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
            host.style.overflow = 'hidden';
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

          const tryAttachOverlays = () => {
            attachOverlayHost();
            attachRouteBarHost();
            attachRightRailInset();
          };
          tryAttachOverlays();
          requestAnimationFrame(tryAttachOverlays);
          setTimeout(tryAttachOverlays, 120);
        })();
        </script>
        """,
        unsafe_allow_javascript=True,
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