import { ArcRotateCamera, Scene, Color3, Vector3, HemisphericLight, MeshBuilder, StandardMaterial, GlowLayer } from '@babylonjs/core';

type GraphCameraNode = { x: number; y: number; z: number };

export type GraphBounds = {
    center: Vector3;
    span: number;
    halfExtent: number;
};

const MIN_GRAPH_SPAN = 40;
const FIT_PADDING = 1.45;
const MAX_ZOOM_OUT_FACTOR = 5;

/** Compute axis-aligned bounds for graph nodes in 3D space. */
export function computeGraphBounds(
    nodes: GraphCameraNode[],
    minSpan = MIN_GRAPH_SPAN,
): GraphBounds | null {
    if (!nodes.length) {
        return null;
    }

    let minX = Infinity;
    let maxX = -Infinity;
    let minY = Infinity;
    let maxY = -Infinity;
    let minZ = Infinity;
    let maxZ = -Infinity;

    for (const node of nodes) {
        minX = Math.min(minX, node.x);
        maxX = Math.max(maxX, node.x);
        minY = Math.min(minY, node.y);
        maxY = Math.max(maxY, node.y);
        minZ = Math.min(minZ, node.z);
        maxZ = Math.max(maxZ, node.z);
    }

    const span = Math.max(maxX - minX, maxY - minY, maxZ - minZ, minSpan);
    const center = new Vector3(
        (minX + maxX) / 2,
        (minY + maxY) / 2,
        (minZ + maxZ) / 2,
    );
    const halfExtent = Math.sqrt(
        ((maxX - minX) / 2) ** 2 +
        ((maxY - minY) / 2) ** 2 +
        ((maxZ - minZ) / 2) ** 2,
    ) || span / 2;

    return { center, span, halfExtent };
}

/** Keep orbit zoom + clip planes aligned with graph size (prevents far-plane pop-out). */
export function updateArcRotateCameraClipPlanes(
    camera: ArcRotateCamera,
    nodes: GraphCameraNode[],
): GraphBounds | null {
    const bounds = computeGraphBounds(nodes);
    if (!bounds) {
        return null;
    }

    const { span, halfExtent } = bounds;
    const fitRadius = span * FIT_PADDING;
    const maxZoomOut = fitRadius * MAX_ZOOM_OUT_FACTOR;

    camera.lowerRadiusLimit = Math.max(0.5, span * 0.02);
    camera.upperRadiusLimit = maxZoomOut;
    camera.maxZ = maxZoomOut + halfExtent * 2 + span * 2;
    camera.minZ = Math.max(0.01, span * 0.001);

    if (camera.radius > maxZoomOut) {
        camera.radius = maxZoomOut;
    }
    if (camera.radius < camera.lowerRadiusLimit) {
        camera.radius = camera.lowerRadiusLimit;
    }

    return bounds;
}

/** Frame the orbit camera to the graph bounding box (desktop / embedded VR iframe). */
export function fitArcRotateCameraToGraph(
    camera: ArcRotateCamera,
    nodes: GraphCameraNode[],
    padding = FIT_PADDING,
): void {
    const bounds = updateArcRotateCameraClipPlanes(camera, nodes);
    if (!bounds) {
        return;
    }

    camera.setTarget(bounds.center);
    camera.alpha = -Math.PI / 2;
    camera.beta = Math.PI / 2.5;
    camera.radius = bounds.span * padding;
}

/** Better depth precision + route overlay rendering group (group 2). */
export function enableLargeGraphScene(scene: Scene): void {
    scene.useLogarithmicDepthBuffer = true;
    scene.setRenderingAutoClearDepthStencil(0, true, true, true);
    scene.setRenderingAutoClearDepthStencil(1, false, true, true);
    scene.setRenderingAutoClearDepthStencil(2, false, true, true);
}

export const setupCommonScene = async (scene: Scene) => {
    enableLargeGraphScene(scene);

    // Background Color
    scene.clearColor = new Color3(0.01, 0.01, 0.03).toColor4();

    // Lighting
    const light = new HemisphericLight("light", new Vector3(0, 1, 0), scene);
    light.intensity = 0.4;
    light.diffuse = new Color3(0.9, 0.9, 1);
    light.specular = new Color3(1, 1, 1);
    light.groundColor = new Color3(0.05, 0.05, 0.1);

    const { DirectionalLight } = await import('@babylonjs/core');
    const dirLight = new DirectionalLight("dirLight", new Vector3(-1, -2, -1), scene);
    dirLight.intensity = 0.2;
    dirLight.diffuse = new Color3(0.8, 0.8, 0.9);

    // Space background — large enough for wide ALL-MB graphs when zoomed out
    const spaceSphere = MeshBuilder.CreateSphere("spaceSphere", { diameter: 50000, segments: 16 }, scene);
    spaceSphere.infiniteDistance = true;
    const spaceMat = new StandardMaterial("spaceMat", scene);
    spaceMat.backFaceCulling = false;
    spaceMat.disableLighting = true;
    spaceMat.emissiveColor = new Color3(0.01, 0.02, 0.05);
    spaceSphere.material = spaceMat;
    spaceSphere.isPickable = false;

    // Stars
    const starMat = new StandardMaterial("starMat", scene);
    starMat.emissiveColor = new Color3(0.8, 0.8, 1);
    starMat.disableLighting = true;

    for (let i = 0; i < 200; i++) {
        const star = MeshBuilder.CreateSphere(`star_${i}`, { diameter: 0.3 }, scene);
        const radius = 300 + Math.random() * 400;
        const theta = Math.random() * Math.PI * 2;
        const phi = Math.random() * Math.PI;

        star.position = new Vector3(
            radius * Math.sin(phi) * Math.cos(theta),
            radius * Math.sin(phi) * Math.sin(theta),
            radius * Math.cos(phi)
        );

        const brightness = 0.3 + Math.random() * 0.7;
        const starMatClone = starMat.clone(`starMat_${i}`);
        starMatClone.emissiveColor = new Color3(brightness, brightness, brightness * 1.1);
        star.material = starMatClone;
        star.isPickable = false;
    }

    // Environment
    const envHelper = scene.createDefaultEnvironment({
        createSkybox: false,
        createGround: false,
        toneMappingEnabled: true,
    });

    // Disable GlowLayer to prevent WebGL errors and artifacts in VR
    // const gl = new GlowLayer("glow", scene);
    // gl.intensity = 0.5;

    return { light, dirLight, spaceSphere, gl: null }; // gl is now null as it's disabled
};
