import json
import streamlit as st

from src.core.cache_bundle import load_or_build_graph_bundle
from src.core.graph_loader import to_pos_dict
from src.viz.plot2d import plot_graph_2d
from src.viz.plot3d import plot_graph_3d
from src.core.tools import top_hubs, export_graphxr
from src.core.queries import search_stops, shortest_path, component_info

st.set_page_config(page_title="CSPE Transport Graph", layout="wide")

GTFS_DIR = "data/gtfs"  # change only if needed


@st.cache_resource(show_spinner=True)
def load_bundle(gtfs_dir: str):
    return load_or_build_graph_bundle(gtfs_dir)


st.title("Transport network explorer (BASE)")

bundle = load_bundle(GTFS_DIR)
pos_all = bundle["pos_all"]
pos = to_pos_dict(pos_all)
graphs = bundle["graphs"]
graphs_lcc = bundle["graphs_lcc"]

mode = st.sidebar.selectbox("Mode", ["all", "metro", "rail", "tram", "bus", "other"], index=1)
use_lcc = st.sidebar.checkbox("Largest connected component (recommended)", value=True)

G = (graphs_lcc if use_lcc else graphs)[mode]

st.sidebar.write(f"Nodes: {G.number_of_nodes()}")
st.sidebar.write(f"Edges: {G.number_of_edges()}")

st.sidebar.subheader("Top hubs")
for hub in top_hubs(G, k=10):
    name = hub["stop_name"] if hub["stop_name"] else hub["stop_id"]
    st.sidebar.write(f"{name} — degree={hub['degree']}")

colA, colB = st.columns([1, 1], gap="large")

with colA:
    st.subheader("Search + route")

    start_q = st.text_input("Start stop (type a name)", value="")
    end_q = st.text_input("End stop (type a name)", value="")

    start_matches = search_stops(G, start_q, limit=40, mode=mode) if start_q else []
    end_matches = search_stops(G, end_q, limit=40, mode=mode) if end_q else []

    def _fmt(opt):
        if not opt:
            return ""
        name = opt["stop_name"] if opt["stop_name"] else opt["stop_id"]
        if opt.get("line"):
            return f"{name} — {opt['line']}  |  {opt['stop_id']}"
        return f"{name}  |  {opt['stop_id']}"

    start_choice = None
    end_choice = None

    if start_q:
        if start_matches:
            start_choice = st.selectbox(
                "Select start",
                options=start_matches,
                format_func=_fmt,
                index=0,
            )
        else:
            st.info("No start matches found in the current graph.")

    if end_q:
        if end_matches:
            end_choice = st.selectbox(
                "Select end",
                options=end_matches,
                format_func=_fmt,
                index=0,
            )
        else:
            st.info("No end matches found in the current graph.")

    strategy_labels = {
        "Best route (cost)": "cost",
        "Shortest distance": "distance",
        "Fewest stops": "hops",
    }
    strategy_label = st.selectbox("Route strategy", list(strategy_labels.keys()), index=0)
    strategy = strategy_labels[strategy_label]

    c1, c2 = st.columns([1, 1])
    with c1:
        compute_clicked = st.button("Compute path", type="primary", disabled=not (start_choice and end_choice))
    with c2:
        clear_clicked = st.button("Clear path")

    if clear_clicked:
        st.session_state["last_path"] = None

    if compute_clicked:
        a = start_choice["stop_id"]
        b = end_choice["stop_id"]

        a_info = component_info(G, a)
        b_info = component_info(G, b)

        res = shortest_path(G, a, b, strategy=strategy)
        st.session_state["last_path"] = res["path"] if res["ok"] else None

        if not res["ok"]:
            if res["reason"] == "not_connected":
                st.error("No path: the two stops are not connected in this graph.")
                st.write(f"Start component size: {a_info.get('component_size', 0)}")
                st.write(f"End component size: {b_info.get('component_size', 0)}")
                if not use_lcc:
                    st.caption("Tip: try enabling LCC, or switch mode, or choose closer stops.")
                else:
                    st.caption("Tip: even in LCC, some pairs can still be disconnected in a given mode.")
            elif res["reason"] == "start_not_found":
                st.error("Start stop not found in the current graph.")
            elif res["reason"] == "end_not_found":
                st.error("End stop not found in the current graph.")
            else:
                st.error("Path computation failed.")
        else:
            path = res["path"]
            st.success(f"Path found: {len(path)} stops")
            if res["distance_m"] is not None:
                if res["distance_m"] >= 1000:
                    st.write(f"Estimated distance: {res['distance_m'] / 1000:.2f} km")
                else:
                    st.write(f"Estimated distance: {res['distance_m']:.0f} m")
            if res["time_s"] is not None:
                st.write(f"Estimated time: {res['time_s'] / 60:.1f} min")
            st.write(f"Transfers: {res['transfers']}")

            pretty = []
            for sid in path[:80]:
                nm = G.nodes[sid].get("stop_name", "")
                pretty.append(f"{nm} ({sid})" if nm else sid)

            st.text("\n".join(pretty) + ("\n..." if len(path) > 80 else ""))

            st.download_button(
                "Download path (txt)",
                data=("\n".join(pretty)).encode("utf-8"),
                file_name="path.txt",
                mime="text/plain",
            )

    st.divider()

    st.subheader("Export for 3D (GraphXR / node-link JSON)")
    max_nodes = st.number_input("Max nodes (cap for big graphs)", min_value=500, max_value=200000, value=20000, step=500)

    export_obj = export_graphxr(G, max_nodes=int(max_nodes), max_edges=200000, include_lon_lat=True)
    export_bytes = json.dumps(export_obj, ensure_ascii=False).encode("utf-8")

    st.download_button(
        "Download JSON export",
        data=export_bytes,
        file_name=f"export_{mode}{'_lcc' if use_lcc else ''}.json",
        mime="application/json",
    )

    st.caption("This JSON is the bridge to the 3D stage: nodes + links with attributes.")

with colB:
    st.subheader("Network view")
    viz_mode = st.selectbox("Visualization mode", ["2D map", "3D network"], index=0)

    if viz_mode == "2D map":
        zoom_to_path = st.checkbox("Zoom to route (recommended for bus/all)", value=True)
        fig = plot_graph_2d(
            G,
            pos,
            title=f"Mode: {mode} {'(LCC)' if use_lcc else ''}",
            path=st.session_state.get("last_path"),
            zoom_to_path=zoom_to_path,
        )
        st.pyplot(fig, use_container_width=True)
    else:
        fig3d = plot_graph_3d(G, pos, path=st.session_state.get("last_path"))
        if G.number_of_nodes() > 5000:
            st.caption("3D view is focused on the selected route and nearby stops to keep Plotly responsive.")
        st.plotly_chart(fig3d, use_container_width=True)