import { Vector3, Scene, Mesh, MeshBuilder } from '@babylonjs/core';
import * as GUI from '@babylonjs/gui';

export interface VRFilterPanelCallbacks {
    onFilterChange: (visibleNodeIds: Set<string> | null, visibleEdgeIds: Set<string> | null) => void;
    onClose?: () => void;
}

export class VRFilterPanel {
    private panelMesh: Mesh | null = null;
    private texture: GUI.AdvancedDynamicTexture | null = null;
    private scene: Scene | null = null;

    // Data & State
    private nodes: any[] = [];
    private edges: any[] = [];
    private nodeCategories: Record<string, string[]> = {};
    private edgeCategories: Record<string, string[]> = {};

    // Active Filters
    private activeNodeFilters: Record<string, Set<string>> = {};
    private activeEdgeFilters: Record<string, Set<string>> = {};
    private activeTab: 'nodes' | 'edges' = 'nodes';

    // UI Referneces
    private contentContainer: GUI.Container | null = null;
    private callbacks: VRFilterPanelCallbacks | null = null;

    constructor() { }

    public create(
        scene: Scene,
        graphData: { nodes: any[], edges: any[] },
        callbacks?: VRFilterPanelCallbacks
    ) {
        this.dispose();
        this.scene = scene;
        this.nodes = graphData.nodes || [];
        this.edges = graphData.edges || [];
        this.callbacks = callbacks || null;

        // 1. Extract Categories (Logic from FilterPanel.tsx)
        this.nodeCategories = this.extractCategories(this.nodes, ['id', 'x', 'y', 'z', 'color', 'label', 'vx', 'vy', 'vz', 'index', 'fx', 'fy', 'fz']);
        this.edgeCategories = this.extractCategories(this.edges, ['source', 'target', 'id', 'weight', 'color', 'index']);

        console.log("VRFilterPanel: Categories Extracted", this.nodeCategories);

        // 2. Create UI
        this.createUI();
    }

    private extractCategories(items: any[], ignoreKeys: string[]) {
        const cats: Record<string, Set<string>> = {};
        const processValue = (key: string, value: any) => {
            if (ignoreKeys.includes(key)) return;
            if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
                if (!cats[key]) cats[key] = new Set();
                cats[key].add(String(value));
            }
        };

        items.forEach(item => {
            Object.entries(item).forEach(([key, value]) => {
                if (key === 'attributes' && typeof value === 'object' && value !== null) {
                    Object.entries(value).forEach(([attrKey, attrValue]) => {
                        processValue(attrKey, attrValue);
                    });
                } else {
                    processValue(key, value);
                }
            });
        });

        return Object.entries(cats)
            .filter(([_, values]) => values.size > 1 && values.size < 50)
            .reduce((acc, [key, values]) => {
                acc[key] = Array.from(values).sort();
                return acc;
            }, {} as Record<string, string[]>);
    }

    private createUI() {
        if (!this.scene) return;

        // Anchor to Camera (Standard VR Menu Position)
        if (this.scene.activeCamera) {
            const cam = this.scene.activeCamera;
            this.panelMesh = MeshBuilder.CreatePlane("VR_Filter_Panel", { width: 5, height: 6 }, this.scene);
            this.panelMesh.position = cam.position.add(cam.getDirection(Vector3.Forward()).scale(3));
            // Move slightly to the side to not block view completely
            this.panelMesh.position.x += 2.5;
            this.panelMesh.lookAt(cam.position);
            // Flip Y rotation because LookAt makes it face away or towards correctly? 
            // Plane faces -Z by default? LookAt makes +Z point to target. 
            // Normally LookAt works fine for Billboard behavior but here we place it once.
            this.panelMesh.rotation.y += Math.PI;
        }

        if (!this.panelMesh) return;

        // Texture
        this.texture = GUI.AdvancedDynamicTexture.CreateForMesh(this.panelMesh, 1024, 1228);
        this.texture.hasAlpha = true;

        // Main Container
        const container = new GUI.Rectangle();
        container.width = 1;
        container.height = 1;
        container.cornerRadius = 40;
        container.color = "#a855f7";
        container.thickness = 4;
        container.background = "rgba(15, 23, 42, 0.95)"; // Slate-950
        this.texture.addControl(container);

        // Header
        const header = new GUI.StackPanel();
        header.width = 1;
        header.height = "140px";
        header.verticalAlignment = GUI.Control.VERTICAL_ALIGNMENT_TOP;
        container.addControl(header);

        const title = new GUI.TextBlock();
        title.text = "FILTRES";
        title.color = "white";
        title.fontSize = 60;
        title.height = "80px";
        title.fontWeight = "bold";
        header.addControl(title);

        // Tabs
        const tabsPanel = new GUI.StackPanel();
        tabsPanel.isVertical = false;
        tabsPanel.height = "60px";
        tabsPanel.horizontalAlignment = GUI.Control.HORIZONTAL_ALIGNMENT_CENTER;
        header.addControl(tabsPanel);

        const createTab = (text: string, id: 'nodes' | 'edges') => {
            const btn = GUI.Button.CreateSimpleButton("tab_" + id, text);
            btn.width = "250px";
            btn.color = this.activeTab === id ? "#a855f7" : "gray";
            btn.background = this.activeTab === id ? "rgba(168, 85, 247, 0.2)" : "transparent";
            btn.thickness = 0;
            btn.fontSize = 30;
            btn.fontWeight = "bold";
            btn.onPointerUpObservable.add(() => {
                this.activeTab = id;
                this.refreshContent();
                // Re-create tabs to update highlight
                // (Simple way: just recreate UI or update button props if stored)
                // For now, full refresh is easier logic but expensive. 
                // Let's just update colors locally? 
                // Actually simple: createUI calls once. Need refreshContent to clear OLD content.
                // To update Tab active state visual, we need references. 
                // Re-calling createUI is too much (destroys mesh). 
                // Better: refreshContent only updates the list area. 
                // Tabs: simple toggle visual updates.
                if (id === 'nodes') {
                    nodesTab.color = "#a855f7"; nodesTab.background = "rgba(168, 85, 247, 0.2)";
                    edgesTab.color = "gray"; edgesTab.background = "transparent";
                } else {
                    edgesTab.color = "#a855f7"; edgesTab.background = "rgba(168, 85, 247, 0.2)";
                    nodesTab.color = "gray"; nodesTab.background = "transparent";
                }
            });
            return btn;
        };

        const nodesTab = createTab("NOEUDS", 'nodes');
        const edgesTab = createTab("LIENS", 'edges');
        tabsPanel.addControl(nodesTab);
        tabsPanel.addControl(edgesTab);

        // Content Area (Scrollable)
        const scrollViewer = new GUI.ScrollViewer();
        scrollViewer.width = 0.95;
        scrollViewer.height = 0.75;
        scrollViewer.top = "150px"; // Offset by header
        scrollViewer.verticalAlignment = GUI.Control.VERTICAL_ALIGNMENT_TOP;
        scrollViewer.thickness = 0;
        container.addControl(scrollViewer);

        this.contentContainer = new GUI.StackPanel();
        this.contentContainer.width = 1;
        scrollViewer.addControl(this.contentContainer);

        // Initial render
        this.refreshContent();

        // Footer / Close / Reset
        const footer = new GUI.StackPanel();
        footer.isVertical = false;
        footer.height = "100px";
        footer.verticalAlignment = GUI.Control.VERTICAL_ALIGNMENT_BOTTOM;
        container.addControl(footer);

        const resetBtn = GUI.Button.CreateSimpleButton("btn_reset", "RESET");
        resetBtn.width = "200px";
        resetBtn.height = "70px";
        resetBtn.color = "white";
        resetBtn.background = "#ef4444";
        resetBtn.cornerRadius = 20;
        resetBtn.fontSize = 30;
        resetBtn.paddingRight = "20px";
        resetBtn.onPointerUpObservable.add(() => {
            this.activeNodeFilters = {};
            this.activeEdgeFilters = {};
            this.applyFilters();
            this.refreshContent();
        });
        footer.addControl(resetBtn);

        const closeBtn = GUI.Button.CreateSimpleButton("btn_close", "FERMER");
        closeBtn.width = "200px";
        closeBtn.height = "70px";
        closeBtn.color = "white";
        closeBtn.background = "#4b5563";
        closeBtn.cornerRadius = 20;
        closeBtn.fontSize = 30;
        closeBtn.onPointerUpObservable.add(() => {
            this.dispose();
            if (this.callbacks?.onClose) this.callbacks.onClose();
        });
        footer.addControl(closeBtn);
    }

    private refreshContent() {
        if (!this.contentContainer) return;
        this.contentContainer.clearControls();

        const categories = this.activeTab === 'nodes' ? this.nodeCategories : this.edgeCategories;
        const activeFilters = this.activeTab === 'nodes' ? this.activeNodeFilters : this.activeEdgeFilters;
        const color = this.activeTab === 'nodes' ? "#3b82f6" : "#a855f7";

        Object.entries(categories).forEach(([category, values]) => {
            // Category Header
            const header = new GUI.TextBlock();
            header.text = `${category.toUpperCase()} (${values.length})`;
            header.color = color;
            header.fontSize = 32;
            header.fontWeight = "bold";
            header.height = "60px";
            header.textHorizontalAlignment = GUI.Control.HORIZONTAL_ALIGNMENT_LEFT;
            header.paddingLeft = "20px";
            this.contentContainer!.addControl(header);

            // Values (Wrap Panel / Grid?)
            // GUI doesn't have a WrapPanel easily? StackPanel is vertical or horizontal.
            // We can simulate Wrap with multiple horizontal stacks.
            // Or just use a vertical list for simplicity in VR (easier to hit).
            // Let's use a "Grid" of buttons? Or just horizontal rows of 3 buttons.

            let rowPanel = new GUI.StackPanel();
            rowPanel.isVertical = false;
            rowPanel.height = "70px";
            rowPanel.horizontalAlignment = GUI.Control.HORIZONTAL_ALIGNMENT_LEFT;
            rowPanel.paddingLeft = "20px";
            this.contentContainer!.addControl(rowPanel);

            let count = 0;
            values.forEach(value => {
                if (count >= 3) { // New row
                    rowPanel = new GUI.StackPanel();
                    rowPanel.isVertical = false;
                    rowPanel.height = "70px";
                    rowPanel.horizontalAlignment = GUI.Control.HORIZONTAL_ALIGNMENT_LEFT;
                    rowPanel.paddingLeft = "20px";
                    this.contentContainer!.addControl(rowPanel);
                    count = 0;
                }

                const isActive = activeFilters[category]?.has(value);
                const btn = GUI.Button.CreateSimpleButton("filter_" + category + "_" + value, value);
                btn.width = "280px";
                btn.height = "60px";
                btn.color = isActive ? "white" : "gray";
                btn.background = isActive ? color : "rgba(255,255,255,0.05)";
                btn.cornerRadius = 15;
                btn.fontSize = 24;
                btn.paddingRight = "10px";

                btn.onPointerUpObservable.add(() => {
                    this.toggleFilter(category, value);
                    // Update visual state (quick hack to avoid full refresh)
                    const newActive = activeFilters[category]?.has(value);
                    btn.color = newActive ? "white" : "gray";
                    btn.background = newActive ? color : "rgba(255,255,255,0.05)";
                });

                rowPanel.addControl(btn);
                count++;
            });

            // Spacer
            const spacer = new GUI.Rectangle();
            spacer.height = "20px";
            spacer.thickness = 0;
            this.contentContainer!.addControl(spacer);
        });

        // Bottom Spacer for scrolling
        const bottomSpacer = new GUI.Rectangle();
        bottomSpacer.height = "100px";
        bottomSpacer.thickness = 0;
        this.contentContainer!.addControl(bottomSpacer);
    }

    private toggleFilter(category: string, value: string) {
        const filters = this.activeTab === 'nodes' ? this.activeNodeFilters : this.activeEdgeFilters;

        if (!filters[category]) filters[category] = new Set();

        if (filters[category].has(value)) {
            filters[category].delete(value);
            if (filters[category].size === 0) delete filters[category];
        } else {
            filters[category].add(value);
        }

        this.applyFilters();
    }

    private applyFilters() {
        // Logic from FillerPanel.tsx
        const hasNodeFilters = Object.keys(this.activeNodeFilters).length > 0;
        const hasEdgeFilters = Object.keys(this.activeEdgeFilters).length > 0;

        let visibleNodes: Set<string> | null = null;
        let visibleEdges: Set<string> | null = null;

        if (hasNodeFilters) {
            visibleNodes = new Set();
            this.nodes.forEach(node => {
                let matches = true;
                for (const [key, selectedValues] of Object.entries(this.activeNodeFilters)) {
                    if (selectedValues.size > 0) {
                        const topLevelValue = node[key];
                        const nestedValue = node.attributes?.[key];
                        const value = topLevelValue !== undefined ? topLevelValue : nestedValue;
                        if (!selectedValues.has(String(value))) {
                            matches = false;
                            break;
                        }
                    }
                }
                if (matches) visibleNodes!.add(node.id);
            });
        }

        if (hasEdgeFilters) {
            visibleEdges = new Set();
            this.edges.forEach(edge => {
                let matches = true;
                for (const [key, selectedValues] of Object.entries(this.activeEdgeFilters)) {
                    if (selectedValues.size > 0 && !selectedValues.has(String(edge[key]))) {
                        matches = false; break;
                    }
                }
                if (matches) {
                    visibleEdges!.add(edge.id || `${edge.source}-${edge.target}`);
                }
            });
        }

        console.log("VR Filter Applied:", {
            nodes: visibleNodes ? visibleNodes.size : "All",
            edges: visibleEdges ? visibleEdges.size : "All"
        });

        if (this.callbacks?.onFilterChange) {
            this.callbacks.onFilterChange(visibleNodes, visibleEdges);
        }
    }

    public dispose() {
        if (this.texture) {
            this.texture.dispose();
            this.texture = null;
        }
        if (this.panelMesh) {
            this.panelMesh.dispose();
            this.panelMesh = null;
        }
        // Do NOT clear active filters here to persist state across open/close
    }
}
