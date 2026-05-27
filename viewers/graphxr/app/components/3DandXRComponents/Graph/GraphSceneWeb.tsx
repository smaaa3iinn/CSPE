'use client';

import { useRef, useCallback, useEffect, useState, forwardRef, useImperativeHandle } from 'react';
import {
    Vector3,
    Color3,
    Scene,
    ArcRotateCamera,
    Mesh,
    InstancedMesh
} from '@babylonjs/core';
import SceneComponent from '@/app/components/3DandXRComponents/Scene/SceneComponent';
import { GraphRenderer } from '../utils/GraphRenderer';
import { setupCommonScene } from '../utils/SceneSetup';

interface GraphData {
    nodes: Array<{
        id: string;
        x: number;
        y: number;
        z: number;
        label?: string;
        color?: string;
        [key: string]: any;
    }>;
    edges: Array<{
        source: string;
        target: string;
        weight?: number;
        [key: string]: any;
    }>;
}

interface GraphSceneProps {
    data: GraphData;
    onSelect?: (data: any, type: 'node' | 'edge' | null) => void;
    visibleNodeIds?: Set<string> | null;
    visibleEdgeIds?: Set<string> | null;
    showLabels?: boolean;
}

export interface GraphSceneRef {
    resetCamera: () => void;
    getCameraState: () => any;
}

const GraphSceneWeb = forwardRef<GraphSceneRef, GraphSceneProps>(({ data, onSelect, visibleNodeIds, visibleEdgeIds, showLabels }, ref) => {
    const [scene, setScene] = useState<Scene | null>(null);
    const [isSceneReady, setIsSceneReady] = useState(false);
    const nodeMeshesRef = useRef<Map<string, Mesh | InstancedMesh>>(new Map());
    const graphRenderer = useRef(new GraphRenderer());

    useImperativeHandle(ref, () => ({
        resetCamera: () => {
            if (scene) {
                const camera = scene.getCameraByName("camera") as ArcRotateCamera;
                if (camera) {
                    camera.setTarget(Vector3.Zero());
                    camera.alpha = -Math.PI / 2;
                    camera.beta = Math.PI / 2.5;
                    camera.radius = 100;
                }
            }
        },
        getCameraState: () => {
            if (scene) {
                const camera = scene.getCameraByName("camera") as ArcRotateCamera;
                if (camera) {
                    return {
                        alpha: camera.alpha,
                        beta: camera.beta,
                        radius: camera.radius,
                        target: { x: camera.target.x, y: camera.target.y, z: camera.target.z },
                        position: { x: camera.position.x, y: camera.position.y, z: camera.position.z }
                    };
                }
            }
            return null;
        }
    }));

    // Handle visibility updates
    useEffect(() => {
        if (scene && nodeMeshesRef.current.size > 0) {
            graphRenderer.current.updateVisibility(visibleNodeIds ?? null, visibleEdgeIds ?? null, nodeMeshesRef.current);
            // Sync labels with visibility
            graphRenderer.current.updateLabelVisibility(!!showLabels, nodeMeshesRef.current, scene);
        }
    }, [visibleNodeIds, visibleEdgeIds, scene, showLabels]);

    // Handle Label Visibility
    useEffect(() => {
        if (scene && nodeMeshesRef.current.size > 0) {
            graphRenderer.current.updateLabelVisibility(!!showLabels, nodeMeshesRef.current, scene);
        }
    }, [showLabels, scene]);

    const onSceneReady = useCallback(async (sceneInstance: Scene) => {
        setScene(sceneInstance);

        // Common Setup (Lights, Background, Glow)
        await setupCommonScene(sceneInstance);

        // Camera setup (ArcRotate for Web/Desktop)
        const camera = new ArcRotateCamera("camera", -Math.PI / 2, Math.PI / 2.5, 100, Vector3.Zero(), sceneInstance);
        const canvas = sceneInstance.getEngine().getRenderingCanvas();

        camera.attachControl(canvas, true);

        // Camera Optimization
        camera.wheelPrecision = 10;
        camera.pinchPrecision = 10;
        camera.panningSensibility = 20;
        camera.wheelDeltaPercentage = 0.05;
        camera.lowerRadiusLimit = 0.1;
        camera.upperRadiusLimit = 10000;
        camera.inertia = 0.9;
        camera.angularSensibilityX = 800;
        camera.angularSensibilityY = 800;

        // Prevent page zoom
        if (canvas) {
            const preventZoom = (e: WheelEvent) => {
                if (e.ctrlKey || e.metaKey) e.preventDefault();
            };
            const preventTouchZoom = (e: TouchEvent) => {
                if (e.touches.length > 1) e.preventDefault();
            };
            canvas.addEventListener('wheel', preventZoom, { passive: false });
            canvas.addEventListener('touchmove', preventTouchZoom, { passive: false });
        }

        setIsSceneReady(true);
    }, []);

    useEffect(() => {
        return () => {
            if (scene) {
                graphRenderer.current.disposeGraph(nodeMeshesRef.current, scene);
            }
        };
    }, [scene]);

    // Handle graph data updates
    useEffect(() => {
        if (!scene || !data) return;

        // Clean up old graph
        graphRenderer.current.disposeGraph(nodeMeshesRef.current, scene);

        // Render graph
        graphRenderer.current.createNodes(
            data,
            scene,
            nodeMeshesRef.current,
            onSelect,
            undefined,
            undefined,
            true
        );
        graphRenderer.current.createEdges(
            data,
            scene,
            nodeMeshesRef.current,
            onSelect
        );

        // Force visibility update after creation
        graphRenderer.current.updateVisibility(visibleNodeIds ?? null, visibleEdgeIds ?? null, nodeMeshesRef.current);
        // Force label update
        graphRenderer.current.updateLabelVisibility(!!showLabels, nodeMeshesRef.current, scene);

    }, [scene, data, onSelect]); // visibleNodeIds is handled by separate effect, but we need initial state

    return (
        <div className="h-full w-full overflow-hidden rounded-xl bg-black/20 relative" style={{ touchAction: 'none' }}>
            {!isSceneReady && (
                <div className="absolute inset-0 flex items-center justify-center bg-black z-10">
                    <div className="flex flex-col items-center gap-4">
                        <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary-500 border-t-transparent"></div>
                        <p className="text-sm text-gray-400">Chargement de la scène...</p>
                    </div>
                </div>
            )}
            <SceneComponent
                antialias
                onSceneReady={onSceneReady}
                id="graph-canvas-web"
                className="h-full w-full outline-none"
                style={{ touchAction: 'none' }}
            />
        </div>
    );
});

GraphSceneWeb.displayName = 'GraphSceneWeb';

export default GraphSceneWeb;
