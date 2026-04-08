"""
Shared app shell: mode navigation, Atlas overlay chat, non-transport mode placeholders.
Transport map layout stays in app.py. Call column helpers inside the appropriate `with col:` block.

Atlas realtime session + tools run via the Atlas Flask API; Streamlit talks to it through atlas_bridge.
Set ATLAS_API_BASE (default http://127.0.0.1:5055). Run Atlas API only, or full start_atlas.bat.
"""

from __future__ import annotations

import streamlit as st

import atlas_bridge

APP_MODE_TRANSPORT = "transport"
APP_MODE_KNOWLEDGE = "knowledge"
APP_MODE_VISUAL = "visual_board"
APP_MODE_MEMORY = "memory"

APP_MODES: list[tuple[str, str, str]] = [
    (APP_MODE_TRANSPORT, "🗺", "Transport"),
    (APP_MODE_KNOWLEDGE, "🔎", "Knowledge"),
    (APP_MODE_VISUAL, "▦", "Visual board"),
    (APP_MODE_MEMORY, "☰", "Memory / tasks"),
]


def init_shell_session_state() -> None:
    if "app_mode" not in st.session_state:
        st.session_state["app_mode"] = APP_MODE_TRANSPORT
    if "memory_selected_project" not in st.session_state:
        st.session_state["memory_selected_project"] = "Project ATLAS"
    st.session_state.setdefault("knowledge_messages", [])
    st.session_state.setdefault("knowledge_query_input", "")
    st.session_state.setdefault("visual_panels", [])
    st.session_state.setdefault("atlas_overlay_messages", [])
    st.session_state.setdefault("atlas_sync_assistant", "")
    st.session_state.setdefault("atlas_sync_panels", [])
    st.session_state.setdefault("atlas_sync_image_urls", [])
    st.session_state.setdefault("atlas_sync_panel_caption", "")
    st.session_state.setdefault(
        "memory_projects_tasks",
        {
            "Project ATLAS": [
                {"title": "Wire CSPE API health check", "done": True},
                {"title": "Review graph bundle version", "done": False},
            ],
            "Project University": [
                {"title": "Lecture notes — transport graphs", "done": False},
            ],
            "Personal": [
                {"title": "Buy metro tickets", "done": False},
            ],
        },
    )


def render_top_bar() -> None:
    """App title only; Atlas chat lives in a fixed bottom dock (see render_atlas_chat_dock)."""
    st.markdown(
        '<div class="cspe-top-bar-title">CSPE</div>',
        unsafe_allow_html=True,
    )


def render_atlas_chat_dock() -> None:
    """
    Floating Atlas chat trigger above the map/iframes (high z-index).
    Call once per run, after main layout (typically last UI element before overlay).
    """
    st.markdown(
        """
        <style>
        div[data-testid="stHorizontalBlock"]:has(#cspe-atlas-dock-marker) {
            position: fixed !important;
            left: 0 !important;
            right: 0 !important;
            bottom: 0 !important;
            width: 100% !important;
            max-width: 100% !important;
            z-index: 100030 !important;
            margin: 0 !important;
            padding: 0.75rem 1rem calc(0.75rem + env(safe-area-inset-bottom, 0px)) !important;
            box-sizing: border-box !important;
            display: flex !important;
            flex-direction: row !important;
            align-items: center !important;
            background: rgba(5, 11, 24, 0.92) !important;
            border-top: 1px solid rgba(120, 140, 160, 0.35) !important;
            pointer-events: none !important;
            justify-content: flex-end !important;
            gap: 0.5rem !important;
        }
        div[data-testid="stHorizontalBlock"]:has(#cspe-atlas-dock-marker) > div[data-testid="column"] {
            pointer-events: auto !important;
            flex: 0 0 auto !important;
            width: auto !important;
            min-width: unset !important;
        }
        div[data-testid="stHorizontalBlock"]:has(#cspe-atlas-dock-marker) > div[data-testid="column"]:first-child {
            flex: 1 1 auto !important;
            min-width: 0 !important;
        }
        div[data-testid="stHorizontalBlock"]:has(#cspe-atlas-dock-marker) > div[data-testid="column"]:last-child {
            margin-left: auto !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    spacer, dock = st.columns([1, 0.11], gap="small")
    with spacer:
        st.markdown(
            '<div id="cspe-atlas-dock-marker" style="height:1px;width:1px;margin:0;padding:0;"></div>',
            unsafe_allow_html=True,
        )
    with dock:
        if st.button(
            "Atlas",
            key="cspe_atlas_chat_open_dock",
            help="Open Atlas chat",
            use_container_width=True,
            type="primary",
        ):
            st.session_state["atlas_overlay_open"] = True
            st.rerun()


def render_atlas_overlay_if_open() -> None:
    """Modal chat layer; call once per run after main layout when open."""
    if not st.session_state.get("atlas_overlay_open"):
        return

    def _atlas_on_dismiss() -> None:
        st.session_state["atlas_overlay_open"] = False

    @st.dialog("Atlas", width="stretch", dismissible=True, on_dismiss=_atlas_on_dismiss)
    def _atlas_overlay() -> None:
        st.caption(
            f"Linked to Atlas API `{atlas_bridge.atlas_base_url()}` — transport, web search, "
            "images, and memory tools run there; results also appear in Knowledge / Visual modes."
        )
        h_close, _ = st.columns([1, 4])
        with h_close:
            if st.button("Close", key="atlas_overlay_close"):
                st.session_state["atlas_overlay_open"] = False
                st.rerun()

        history = list(st.session_state.get("atlas_overlay_messages", []))
        for role, text in history[-40:]:
            with st.chat_message(role):
                st.markdown(text)

        prompt = st.chat_input("Message Atlas…", key="atlas_overlay_chat_input")
        if prompt:
            history.append(("user", prompt))
            st.session_state["atlas_overlay_messages"] = history
            with st.spinner("Waiting for Atlas…"):
                ui, err = atlas_bridge.send_text_and_wait(prompt)
            if err:
                history.append(("assistant", f"**Could not reach Atlas:** {err}"))
            else:
                reply = (ui.get("assistant") or "").strip()
                if reply:
                    history.append(("assistant", reply))
                else:
                    history.append(
                        (
                            "assistant",
                            "_No assistant text yet — if tools ran, check Knowledge / Visual for images._",
                        )
                    )
                atlas_bridge.sync_streamlit_from_ui(ui)
            st.session_state["atlas_overlay_messages"] = history
            st.rerun()

    _atlas_overlay()


def render_mode_nav_column() -> None:
    """Icon-only vertical mode switcher (left column)."""
    st.markdown('<div id="cspe-global-nav-anchor"></div>', unsafe_allow_html=True)
    current = st.session_state.get("app_mode", APP_MODE_TRANSPORT)
    for mode_key, icon, help_text in APP_MODES:
        active = mode_key == current
        btn_type = "primary" if active else "secondary"
        if st.button(
            icon,
            key=f"cspe_nav_{mode_key}",
            help=help_text,
            use_container_width=True,
            type=btn_type,
        ):
            if st.session_state.get("app_mode") != mode_key:
                st.session_state["app_mode"] = mode_key
                st.rerun()
    st.markdown('<div class="cspe-left-rail"></div>', unsafe_allow_html=True)


def render_knowledge_center() -> None:
    st.markdown("### Knowledge")
    st.caption("Ask Atlas from the **Atlas** button (bottom). Web answers and image search show here after each reply.")
    demo = st.session_state.get("knowledge_demo_results") or {}
    imgs = demo.get("images") or []
    if not imgs:
        st.info("No images from Atlas yet. Try: “show me photos of …” in Atlas chat.")
        return
    cols = st.columns(min(3, max(1, len(imgs))))
    for i, url in enumerate(imgs[:12]):
        with cols[i % len(cols)]:
            try:
                st.image(atlas_bridge.proxied_image_url(url), use_container_width=True)
            except Exception:
                try:
                    st.image(url, use_container_width=True)
                except Exception:
                    st.caption("(image load failed)")


def render_knowledge_right() -> None:
    st.markdown("### Details")
    demo = st.session_state.get("knowledge_demo_results") or {}
    body = (demo.get("summary") or st.session_state.get("atlas_sync_assistant") or "").strip()
    if body:
        st.markdown(body)
    else:
        st.info("Atlas replies and search summaries appear here after you chat.")


def render_visual_board_center() -> None:
    panels = st.session_state.get("visual_panels") or []
    st.markdown("### Visual board")
    st.caption("Same image panels Atlas pushes (image search, visual board tools). Use Atlas chat to update.")
    if not panels:
        st.info("No panels yet — ask Atlas for images or a visual board.")
        return
    for p in panels:
        if not isinstance(p, dict):
            continue
        title = p.get("title") or "Panel"
        with st.expander(title, expanded=True):
            urls = p.get("urls") or []
            if urls:
                icols = st.columns(min(4, len(urls)))
                for i, u in enumerate(urls):
                    if not u:
                        continue
                    with icols[i % len(icols)]:
                        try:
                            st.image(atlas_bridge.proxied_image_url(str(u)), use_container_width=True)
                        except Exception:
                            try:
                                st.image(str(u), use_container_width=True)
                            except Exception:
                                st.caption("(image failed)")
            else:
                st.caption("No images in this panel.")


def render_visual_board_right() -> None:
    st.markdown("### Board notes")
    cap = (st.session_state.get("atlas_sync_panel_caption") or "").strip()
    assist = (st.session_state.get("atlas_sync_assistant") or "").strip()
    if cap:
        st.markdown(cap)
    if assist:
        st.markdown(assist)
    if not cap and not assist:
        st.caption("Last assistant reply and panel titles show here after Atlas updates the board.")


def render_memory_center() -> None:
    st.caption("Local task list demo. Atlas **memory_** tools use Atlas’s own SQLite — manage them via Atlas chat.")
    data = st.session_state.get("memory_projects_tasks") or {}
    projects = list(data.keys())
    sel = st.session_state.get("memory_selected_project")
    if sel not in projects and projects:
        sel = projects[0]
        st.session_state["memory_selected_project"] = sel

    st.markdown("### Tasks")
    if not sel:
        st.caption("Select a project.")
        return
    tasks = list(data.get(sel, []))
    if not tasks:
        st.caption("No tasks in this project.")
        return
    for idx, t in enumerate(tasks):
        title = t.get("title", "")
        done = bool(t.get("done"))
        c1, c2 = st.columns([0.08, 0.92])
        with c1:
            new_done = st.checkbox("", value=done, key=f"mem_done_{sel}_{idx}")
            if new_done != done:
                t["done"] = new_done
                data[sel][idx] = t
                st.session_state["memory_projects_tasks"] = data
                st.rerun()
        with c2:
            st.markdown(f"~~{title}~~" if done else title)


def render_memory_right() -> None:
    data = st.session_state.get("memory_projects_tasks") or {}
    projects = list(data.keys())
    sel = st.session_state.get("memory_selected_project")
    if sel not in projects and projects:
        sel = projects[0]
        st.session_state["memory_selected_project"] = sel

    st.markdown("### Projects")
    for name in projects:
        is_sel = name == sel
        if st.button(
            name,
            key=f"mem_proj_{name}",
            use_container_width=True,
            type="primary" if is_sel else "secondary",
        ):
            st.session_state["memory_selected_project"] = name
            st.rerun()
