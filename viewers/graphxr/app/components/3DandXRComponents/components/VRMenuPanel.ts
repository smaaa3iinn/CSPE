import { Vector3, Scene, Mesh, MeshBuilder } from '@babylonjs/core';
import * as GUI from '@babylonjs/gui';

export interface VRMenuPanelCallbacks {
    onLayoutRequest: (layoutName: string) => void;
    onResetFilters?: () => void;
    onToggleLabels?: () => void;
    onOpenFilters?: () => void;
    onClose?: () => void;
}

export class VRMenuPanel {
    private panelMesh: Mesh | null = null;
    private texture: GUI.AdvancedDynamicTexture | null = null;
    private scene: Scene | null = null;
    private callbacks: VRMenuPanelCallbacks | null = null;
    private currentLayout: string = 'forceatlas2';

    constructor() { }

    public create(
        scene: Scene,
        callbacks: VRMenuPanelCallbacks,
        currentLayout: string = 'forceatlas2'
    ) {
        // Fix duplication: Ensure previous panel is destroyed before creating a new one
        this.dispose();

        this.scene = scene;
        this.callbacks = callbacks;
        this.currentLayout = currentLayout;

        this.createUI();
    }

    private createUI() {
        if (!this.scene) return;

        // Full cleanup (Mesh + Texture) to prevent duplication/leaks
        this.dispose();

        // Anchor to Camera (Standard VR Menu Position)
        if (this.scene.activeCamera) {
            const cam = this.scene.activeCamera;
            this.panelMesh = MeshBuilder.CreatePlane("VR_Main_Menu", { width: 4, height: 3 }, this.scene);
            this.panelMesh.position = cam.position.add(cam.getDirection(Vector3.Forward()).scale(2.5));
            // Move slightly down
            this.panelMesh.position.y -= 0.5;
            this.panelMesh.lookAt(cam.position);
            this.panelMesh.rotation.y += Math.PI;
        }

        if (!this.panelMesh) return;

        // Texture
        this.texture = GUI.AdvancedDynamicTexture.CreateForMesh(this.panelMesh, 1024, 768);
        this.texture.hasAlpha = true;

        // Main Container
        const container = new GUI.Rectangle();
        container.width = 1;
        container.height = 1;
        container.cornerRadius = 30;
        container.color = "#3b82f6";
        container.thickness = 4;
        container.background = "rgba(15, 23, 42, 0.95)"; // Slate-950
        this.texture.addControl(container);

        // Master Grid Layout
        // Row 0: Header (15%)
        // Row 1: Layouts Title (10%)
        // Row 2: Layouts Grid (35%)
        // Row 3: Actions Title (10%)
        // Row 4: Actions Grid (20%)
        // Row 5: Close Button (10%)
        const masterGrid = new GUI.Grid();
        masterGrid.width = 0.9;
        masterGrid.height = 0.95;
        masterGrid.addRowDefinition(0.15); // Header
        masterGrid.addRowDefinition(0.1);  // Layouts Title
        masterGrid.addRowDefinition(0.35); // Layouts
        masterGrid.addRowDefinition(0.1);  // Actions Title
        masterGrid.addRowDefinition(0.2);  // Actions
        masterGrid.addRowDefinition(0.1);  // Close
        container.addControl(masterGrid);

        // Header
        const header = new GUI.TextBlock();
        header.text = "OPTIONS GRAPHE";
        header.color = "white";
        header.fontSize = 50;
        header.fontWeight = "bold";
        masterGrid.addControl(header, 0, 0);

        // 1. Layouts Section
        this.addSectionTitle(masterGrid, "DISPOSITION", 1);

        const layouts = [
            { id: 'fruchterman_reingold', label: 'Frucht-Rein' },
            { id: 'kamada_kawai', label: 'Kamada-Kawai' },
            { id: 'drl', label: 'DrL' },
            { id: 'force_atlas', label: 'Force Atlas 2' },
            { id: 'sphere', label: 'Sphérique' },
            { id: 'grid', label: 'Grille' },
            { id: 'random', label: 'Aléatoire' }
        ];

        const layoutGrid = new GUI.Grid();
        layoutGrid.addColumnDefinition(0.33);
        layoutGrid.addColumnDefinition(0.33);
        layoutGrid.addColumnDefinition(0.33);
        layoutGrid.addRowDefinition(0.33);
        layoutGrid.addRowDefinition(0.33);
        layoutGrid.addRowDefinition(0.33);

        layouts.forEach((l, idx) => {
            const row = Math.floor(idx / 3);
            const col = idx % 3;

            const btn = GUI.Button.CreateSimpleButton("btn_" + l.id, l.label);
            btn.color = this.currentLayout === l.id ? "white" : "gray";
            btn.background = this.currentLayout === l.id ? "#3b82f6" : "rgba(255,255,255,0.05)";
            btn.cornerRadius = 15;
            btn.fontSize = 28;
            btn.thickness = this.currentLayout === l.id ? 2 : 1;
            btn.paddingTop = "5px";
            btn.paddingBottom = "5px";
            btn.paddingLeft = "5px";
            btn.paddingRight = "5px";

            btn.onPointerUpObservable.add(() => {
                if (this.callbacks?.onLayoutRequest) this.callbacks.onLayoutRequest(l.id);
                this.currentLayout = l.id;
                this.createUI(); // Rebuild for visual update
            });

            layoutGrid.addControl(btn, row, col);
        });
        masterGrid.addControl(layoutGrid, 2, 0);

        // 2. Actions Section
        this.addSectionTitle(masterGrid, "ACTIONS", 3);

        const actionGrid = new GUI.Grid();
        actionGrid.addColumnDefinition(0.5);
        actionGrid.addColumnDefinition(0.5);
        actionGrid.addRowDefinition(0.5);
        actionGrid.addRowDefinition(0.5);

        // Filters
        if (this.callbacks?.onOpenFilters) {
            const btn = this.createActionButton("FILTRES...", "#8b5cf6", () => {
                this.callbacks?.onOpenFilters!();
            });
            actionGrid.addControl(btn, 0, 0);
        }

        // Reset Filters
        if (this.callbacks?.onResetFilters) {
            const btn = this.createActionButton("RESET FILTRES", "#ef4444", () => this.callbacks?.onResetFilters!());
            actionGrid.addControl(btn, 0, 1);
        }

        // Toggle Labels
        if (this.callbacks?.onToggleLabels) {
            const btn = this.createActionButton("TOGGLE LABELS", "#eab308", () => this.callbacks?.onToggleLabels!());
            actionGrid.addControl(btn, 1, 0);
        }

        masterGrid.addControl(actionGrid, 4, 0);

        // Close Button
        const closeBtn = GUI.Button.CreateSimpleButton("btn_close_menu", "FERMER");
        closeBtn.width = "200px";
        closeBtn.height = "60px";
        closeBtn.color = "white";
        closeBtn.background = "#4b5563"; // gray-600
        closeBtn.cornerRadius = 20;
        closeBtn.fontSize = 30;

        closeBtn.onPointerUpObservable.add(() => {
            this.dispose();
            if (this.callbacks?.onClose) this.callbacks.onClose();
        });
        masterGrid.addControl(closeBtn, 5, 0);
    }

    private addSectionTitle(grid: GUI.Grid, text: string, row: number) {
        const t = new GUI.TextBlock();
        t.text = text;
        t.color = "#93c5fd"; // blue-300
        t.fontSize = 24;
        t.fontWeight = "bold";
        t.textHorizontalAlignment = GUI.Control.HORIZONTAL_ALIGNMENT_LEFT;
        t.paddingLeft = "20px";
        grid.addControl(t, row, 0);
    }

    private createActionButton(text: string, color: string, onClick: () => void) {
        const btn = GUI.Button.CreateSimpleButton("btn_" + text, text);
        btn.color = "white";
        btn.background = color;
        btn.cornerRadius = 15;
        btn.fontSize = 28;
        btn.paddingTop = "5px";
        btn.paddingBottom = "5px";
        btn.paddingLeft = "5px";
        btn.paddingRight = "5px";
        btn.onPointerUpObservable.add(onClick);
        return btn;
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
    }
}
