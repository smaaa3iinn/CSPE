import { Mesh, MeshBuilder, Scene, TransformNode, Vector3 } from '@babylonjs/core';
import * as GUI from '@babylonjs/gui';

export type VRRouteLeg = {
    kind?: string;
    color?: string;
    summary?: string;
};

const PANEL_NAME = 'VR_ROUTE_PANEL';

function legColor(raw: string | undefined, kind: string | undefined): string {
    const c = (raw || '').trim();
    if (c) return c;
    return kind === 'transfer' ? '#f59e0b' : '#60a5fa';
}

function buildMetaLine(legs: VRRouteLeg[], routeMeta?: string | null): string {
    const explicit = (routeMeta || '').trim();
    if (explicit) return explicit;
    return legs.map((leg) => (leg.summary || '').trim()).filter(Boolean).join(' · ');
}

/** In-scene route breakdown panel (camera-attached HUD) for VR / 3D preview. */
export class VRRoutePanel {
    private mesh: Mesh | null = null;
    private texture: GUI.AdvancedDynamicTexture | null = null;
    private signature = '';

    dispose(): void {
        if (this.texture) {
            this.texture.dispose();
            this.texture = null;
        }
        if (this.mesh) {
            this.mesh.dispose();
            this.mesh = null;
        }
        this.signature = '';
    }

    sync(
        scene: Scene,
        anchor: TransformNode | null,
        legs: VRRouteLeg[] | null | undefined,
        routeMeta?: string | null,
    ): void {
        const rows = (legs || []).filter((leg) => (leg.summary || '').trim());
        if (!rows.length || !anchor) {
            this.dispose();
            return;
        }

        const sig = JSON.stringify({ rows, routeMeta: routeMeta || '' });
        if (sig === this.signature && this.mesh && this.mesh.parent === anchor) {
            return;
        }
        this.signature = sig;
        this.dispose();

        const legCount = rows.length;
        const planeHeight = Math.min(0.14 + legCount * 0.1 + (routeMeta ? 0.07 : 0), 0.72);
        const planeWidth = 0.62;

        this.mesh = MeshBuilder.CreatePlane(PANEL_NAME, { width: planeWidth, height: planeHeight }, scene);
        this.mesh.parent = anchor;
        this.mesh.position = new Vector3(-0.38, 0.24, 1.15);
        this.mesh.rotation.x = -Math.PI / 10;

        const texH = Math.round(160 + legCount * 108 + (routeMeta ? 72 : 0));
        this.texture = GUI.AdvancedDynamicTexture.CreateForMesh(this.mesh, 920, texH);
        this.texture.hasAlpha = true;
        this.texture.background = 'rgba(8, 12, 20, 0.88)';

        const root = new GUI.StackPanel();
        root.width = 1;
        root.height = 1;
        root.paddingTop = '18px';
        root.paddingBottom = '14px';
        root.paddingLeft = '16px';
        root.paddingRight = '16px';
        this.texture.addControl(root);

        rows.forEach((leg) => {
            const row = new GUI.StackPanel();
            row.isVertical = false;
            row.width = 1;
            row.height = '96px';
            row.paddingBottom = '10px';
            root.addControl(row);

            const bar = new GUI.Rectangle();
            bar.width = '12px';
            bar.height = '88px';
            bar.thickness = 0;
            bar.background = legColor(leg.color, leg.kind);
            bar.cornerRadius = 4;
            row.addControl(bar);

            const textWrap = new GUI.StackPanel();
            textWrap.width = '820px';
            textWrap.paddingLeft = '16px';
            row.addControl(textWrap);

            const summary = new GUI.TextBlock();
            summary.text = (leg.summary || '').trim();
            summary.color = leg.kind === 'transfer' ? 'rgba(255, 255, 255, 0.82)' : '#f4f7fb';
            summary.fontSize = 30;
            summary.textWrapping = true;
            summary.textHorizontalAlignment = GUI.Control.HORIZONTAL_ALIGNMENT_LEFT;
            summary.height = '88px';
            textWrap.addControl(summary);
        });

        const metaLine = buildMetaLine(rows, routeMeta);
        if (metaLine) {
            const meta = new GUI.TextBlock();
            meta.text = metaLine;
            meta.color = 'rgba(148, 163, 184, 0.95)';
            meta.fontSize = 24;
            meta.textWrapping = true;
            meta.paddingTop = '8px';
            meta.height = '64px';
            meta.textHorizontalAlignment = GUI.Control.HORIZONTAL_ALIGNMENT_LEFT;
            root.addControl(meta);
        }
    }
}
