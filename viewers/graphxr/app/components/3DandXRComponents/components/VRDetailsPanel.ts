import { Vector3, Scene, Mesh, MeshBuilder } from '@babylonjs/core';
import * as GUI from '@babylonjs/gui';

export interface VRDetailsPanelCallbacks {
    onShowNeighbors?: (id: string) => void;
    onResetFilters?: () => void;
}

export class VRDetailsPanel {
    private panelMesh: Mesh | null = null;
    private texture: GUI.AdvancedDynamicTexture | null = null;
    private scene: Scene | null = null;

    constructor() { }

    public create(
        scene: Scene,
        data: any,
        type: string,
        xrHelper?: any,
        callbacks?: VRDetailsPanelCallbacks
    ) {
        // Clean up previous panel
        this.dispose();
        if (!data) return;
        this.scene = scene;

        console.log("VRDetailsPanel: Creating Panel for", type, data.id);

        // Taller panel if we have action buttons
        const hasActions = type === 'node';
        const panelHeight = hasActions ? 5.5 : 4.5;

        // 1. Create Plane (World Space + Billboard)
        this.panelMesh = MeshBuilder.CreatePlane("VR_UI_Panel", { width: 4.5, height: panelHeight }, scene);

        // Position based on target mesh
        const meshID = data.id;
        const targetMesh = scene.getMeshByName(meshID);

        if (targetMesh) {
            const worldMatrix = targetMesh.computeWorldMatrix(true);
            const worldPosition = Vector3.TransformCoordinates(Vector3.Zero(), worldMatrix);
            this.panelMesh.position = worldPosition.clone();
            // Position panel high above node to avoid label overlap (labels are at y=1.2)
            this.panelMesh.position.y += panelHeight / 2 + 2.5;
        } else {
            if (scene.activeCamera) {
                const cam = scene.activeCamera;
                this.panelMesh.position = cam.position.add(cam.getDirection(Vector3.Forward()).scale(3));
            }
        }

        this.panelMesh.billboardMode = Mesh.BILLBOARDMODE_ALL;

        // 2. Texture Creation
        const textureHeight = hasActions ? 1536 : 1280;
        this.texture = GUI.AdvancedDynamicTexture.CreateForMesh(this.panelMesh, 1024, textureHeight);
        this.texture.hasAlpha = true;

        // 3. Main Container
        const mainContainer = new GUI.Rectangle();
        mainContainer.width = 1;
        mainContainer.height = 1;
        mainContainer.cornerRadius = 30;
        mainContainer.color = type === 'node' ? "#3b82f6" : "#a855f7";
        mainContainer.thickness = 4;
        mainContainer.background = "rgba(10, 15, 30, 0.98)";
        this.texture.addControl(mainContainer);

        // Header
        const headerBg = new GUI.Rectangle();
        headerBg.width = 1;
        headerBg.height = "100px";
        headerBg.verticalAlignment = GUI.Control.VERTICAL_ALIGNMENT_TOP;
        headerBg.cornerRadius = 30;
        headerBg.thickness = 0;
        headerBg.background = type === 'node' ? "#1e40af" : "#7c3aed";
        mainContainer.addControl(headerBg);

        // Title
        const title = new GUI.TextBlock();
        title.text = type === 'node' ? "DETAILS DU NOEUD" : "DETAILS DU LIEN";
        title.color = "white";
        title.fontSize = 44;
        title.fontWeight = "bold";
        title.textVerticalAlignment = GUI.Control.VERTICAL_ALIGNMENT_TOP;
        title.top = 28;
        mainContainer.addControl(title);

        // Content Area (Scrollable)
        const scrollViewerHeight = hasActions ? 0.6 : 0.72;
        const scrollViewer = new GUI.ScrollViewer();
        scrollViewer.width = 0.95;
        scrollViewer.height = scrollViewerHeight;
        scrollViewer.top = "120px";
        scrollViewer.verticalAlignment = GUI.Control.VERTICAL_ALIGNMENT_TOP;
        scrollViewer.thickness = 0;
        scrollViewer.barColor = type === 'node' ? "#3b82f6" : "#a855f7";
        scrollViewer.barSize = 15;
        mainContainer.addControl(scrollViewer);

        const contentStack = new GUI.StackPanel();
        contentStack.width = 1;
        scrollViewer.addControl(contentStack);

        // ID Block (highlighted)
        const idBlock = new GUI.Rectangle();
        idBlock.width = 0.95;
        idBlock.height = "90px";
        idBlock.cornerRadius = 15;
        idBlock.background = type === 'node' ? "rgba(59, 130, 246, 0.2)" : "rgba(168, 85, 247, 0.2)";
        idBlock.thickness = 2;
        idBlock.color = type === 'node' ? "#3b82f6" : "#a855f7";
        idBlock.paddingTop = "8px";
        idBlock.paddingBottom = "8px";
        contentStack.addControl(idBlock);

        const idLabel = new GUI.TextBlock();
        idLabel.text = "IDENTIFIANT";
        idLabel.color = type === 'node' ? "#60a5fa" : "#c084fc";
        idLabel.fontSize = 22;
        idLabel.textVerticalAlignment = GUI.Control.VERTICAL_ALIGNMENT_TOP;
        idLabel.top = 8;
        idBlock.addControl(idLabel);

        const idValue = new GUI.TextBlock();
        idValue.text = String(data.id || 'N/A');
        idValue.color = "white";
        idValue.fontSize = 32;
        idValue.fontWeight = "bold";
        idValue.textVerticalAlignment = GUI.Control.VERTICAL_ALIGNMENT_BOTTOM;
        idValue.paddingBottom = "8px";
        idValue.textWrapping = true;
        idBlock.addControl(idValue);

        // Label (if exists)
        if (data.label) {
            this.addPropertyRow(contentStack, "Label", data.label, type);
        }

        // Edge-specific: Source and Target
        if (type === 'edge') {
            this.addPropertyRow(contentStack, "Source", data.source, type);
            this.addPropertyRow(contentStack, "Cible", data.target, type);
        }

        // Properties Title
        const propsTitle = new GUI.TextBlock();
        propsTitle.text = "PROPRIETES";
        propsTitle.color = "rgba(200, 200, 200, 0.8)";
        propsTitle.fontSize = 24;
        propsTitle.height = "40px";
        propsTitle.fontWeight = "bold";
        propsTitle.paddingTop = "10px";
        contentStack.addControl(propsTitle);

        // Properties
        const skipKeys = ['id', 'x', 'y', 'z', 'vx', 'vy', 'vz', 'index', 'source', 'target', 'label'];

        Object.entries(data).forEach(([key, value]) => {
            if (skipKeys.includes(key)) return;

            // Handle nested objects (like 'attributes')
            if (typeof value === 'object' && value !== null && !Array.isArray(value)) {
                const nestedHeader = new GUI.TextBlock();
                nestedHeader.text = key.toUpperCase();
                nestedHeader.color = type === 'node' ? "#60a5fa" : "#c084fc";
                nestedHeader.fontSize = 24;
                nestedHeader.height = "40px";
                nestedHeader.fontWeight = "bold";
                nestedHeader.textHorizontalAlignment = GUI.Control.HORIZONTAL_ALIGNMENT_LEFT;
                nestedHeader.paddingLeft = "20px";
                contentStack.addControl(nestedHeader);

                Object.entries(value as Record<string, any>).forEach(([nestedKey, nestedValue]) => {
                    this.addPropertyRow(contentStack, nestedKey, nestedValue, type, true);
                });
            } else if (Array.isArray(value)) {
                const arrayHeader = new GUI.TextBlock();
                arrayHeader.text = `${key.toUpperCase()} (${value.length})`;
                arrayHeader.color = type === 'node' ? "#34d399" : "#f472b6";
                arrayHeader.fontSize = 24;
                arrayHeader.height = "40px";
                arrayHeader.fontWeight = "bold";
                arrayHeader.textHorizontalAlignment = GUI.Control.HORIZONTAL_ALIGNMENT_LEFT;
                arrayHeader.paddingLeft = "20px";
                contentStack.addControl(arrayHeader);

                value.slice(0, 3).forEach((item, idx) => {
                    const itemStr = typeof item === 'object' ? JSON.stringify(item) : String(item);
                    this.addPropertyRow(contentStack, `[${idx}]`, itemStr, type, true);
                });
                if (value.length > 3) {
                    this.addPropertyRow(contentStack, "...", `+${value.length - 3} more`, type, true);
                }
            } else {
                this.addPropertyRow(contentStack, key, value, type);
            }
        });

        // 4. Action Buttons (Bottom)
        if (hasActions && callbacks) {
            const actionsStack = new GUI.StackPanel();
            actionsStack.width = 1;
            actionsStack.height = "250px"; // Increased space for buttons
            actionsStack.verticalAlignment = GUI.Control.VERTICAL_ALIGNMENT_BOTTOM;
            actionsStack.paddingBottom = "40px";
            mainContainer.addControl(actionsStack);

            const createActionBtn = (text: string, bg: string, callback: () => void) => {
                const btn = GUI.Button.CreateSimpleButton("btn_" + text, text);
                btn.width = 0.9;
                btn.height = "70px";
                btn.color = "white";
                btn.background = bg;
                btn.cornerRadius = 20;
                btn.paddingBottom = "5px"; // Fix potential overlap
                btn.color = "white";
                btn.fontSize = 28;
                // Spacer ? No, just margin is hard in stack panel, use empty block or container
                // Actually StackPanel elements stack tightly. We can use a container for button to add margin.
                const btnContainer = new GUI.Rectangle();
                btnContainer.height = "80px";
                btnContainer.thickness = 0;
                btnContainer.addControl(btn);
                actionsStack.addControl(btnContainer);

                btn.onPointerUpObservable.add(() => {
                    callback();
                    // this.dispose(); // Optional: close panel
                });
            };

            if (callbacks.onShowNeighbors) {
                createActionBtn("VOISINS", "#8b5cf6", () => callbacks.onShowNeighbors!(data.id));
            }

            if (callbacks.onResetFilters) {
                createActionBtn("RESET", "#6b7280", () => callbacks.onResetFilters!());
            }
        }

        // Close Button (Top Right X)
        const closeBtn = GUI.Button.CreateSimpleButton("btn_close_x", "X");
        closeBtn.width = "60px";
        closeBtn.height = "60px";
        closeBtn.color = "white";
        closeBtn.background = "#ef4444";
        closeBtn.cornerRadius = 30;
        closeBtn.horizontalAlignment = GUI.Control.HORIZONTAL_ALIGNMENT_RIGHT;
        closeBtn.verticalAlignment = GUI.Control.VERTICAL_ALIGNMENT_TOP;
        closeBtn.top = "20px";
        closeBtn.left = "-20px";
        closeBtn.onPointerUpObservable.add(() => this.dispose());
        mainContainer.addControl(closeBtn);
    }

    private addPropertyRow(container: GUI.Container, key: string, value: any, type: string, isNested: boolean = false) {
        // Use Grid for layout to avoid percentage width issues in StackPanel
        const row = new GUI.Grid();
        row.height = "50px";
        row.width = 1;

        // Define columns: Key (40%) | Value (60%)
        row.addColumnDefinition(0.4);
        row.addColumnDefinition(0.6);

        // Apply padding to the grid row itself
        row.paddingLeft = isNested ? "40px" : "20px";
        row.paddingRight = "10px";

        container.addControl(row);

        const keyBlock = new GUI.TextBlock();
        keyBlock.text = key + ": ";
        keyBlock.color = type === 'node' ? "#93c5fd" : "#e9d5ff";
        keyBlock.fontSize = 22;
        keyBlock.fontWeight = "bold";
        keyBlock.textHorizontalAlignment = GUI.Control.HORIZONTAL_ALIGNMENT_LEFT;
        row.addControl(keyBlock, 0, 0); // Add to row 0, column 0

        const valueBlock = new GUI.TextBlock();
        valueBlock.text = String(value);
        valueBlock.color = "white";
        valueBlock.fontSize = 22;
        valueBlock.textHorizontalAlignment = GUI.Control.HORIZONTAL_ALIGNMENT_LEFT;
        valueBlock.textWrapping = true; // Wrap long values
        // Allow text to overflow vertically if needed, but row height is fixed. 
        // For simple properties 50px is enough.
        row.addControl(valueBlock, 0, 1); // Add to row 0, column 1
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
