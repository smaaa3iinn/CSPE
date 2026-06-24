'use client';

import { useRef, useCallback, useEffect, useState, forwardRef, useImperativeHandle } from 'react';
import {
    Vector3,
    Scene,
    ArcRotateCamera,
    Mesh,
    InstancedMesh,
    WebXRState,
    Quaternion,
    Color3,
    Color4,
    Ray,
    MeshBuilder,
    StandardMaterial,
    WebXRMotionControllerManager,
    WebXRFeatureName,
    Scalar,
} from '@babylonjs/core';
import '@babylonjs/core/XR/motionController/webXROculusTouchMotionController'; // Local Oculus Touch controller
import '@babylonjs/loaders'; // Required for glTF controller models
import '@babylonjs/core/Materials/Node/Blocks'; // Required for NodeMaterial in controller models
import * as GUI from '@babylonjs/gui';
import SceneComponent from '@/app/components/3DandXRComponents/Scene/SceneComponent';
import { useVRMenu } from '../hooks/useVRMenu';
import { VRDetailsPanel } from '../components/VRDetailsPanel';
import { VRRoutePanel } from '../components/VRRoutePanel';
import { VRFilterPanel } from '../components/VRFilterPanel';
import { GraphRenderer } from '../utils/GraphRenderer';
import { setupCommonScene, fitArcRotateCameraToGraph, updateArcRotateCameraClipPlanes } from '../utils/SceneSetup';

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
    metadata?: {
        route_legs?: Array<{ kind?: string; color?: string; summary?: string }>;
        route_meta?: string;
        has_route?: boolean;
        [key: string]: unknown;
    };
}

interface GraphSceneProps {
    data: GraphData;
    onSelect?: (data: any, type: 'node' | 'edge' | null) => void;
    visibleNodeIds?: Set<string> | null;
    visibleEdgeIds?: Set<string> | null;
    onXRStateChange?: (isInXR: boolean) => void;
    showLabels?: boolean;
    onResetFilters?: () => void;
    onToggleLabels?: () => void;
}

// Match GraphSceneWeb interface
export interface GraphSceneRef {
    resetCamera: () => void;
    getCameraState: () => any;
}

const GraphSceneXR = forwardRef<GraphSceneRef, GraphSceneProps>(({ data, onSelect, visibleNodeIds, visibleEdgeIds, onXRStateChange, showLabels, onResetFilters, onToggleLabels }, ref) => {
    // ... lines 68-114 ... (retained implicit context but need to be careful with replacer) - Wait, I should not replace the whole component definition if I can avoid it.
    // I will target the interface definition and useImperativeHandle block.
    // However, the component start line is in the middle of arguments.
    // Let's target the lines specifically.
    // Actually, I'll just replace the interface and useImperativeHandle.

    const [scene, setScene] = useState<Scene | null>(null);
    const [isSceneReady, setIsSceneReady] = useState(false);
    const xrHelperRef = useRef<any>(null);
    const detailsPanelRef = useRef(new VRDetailsPanel());
    const routePanelRef = useRef(new VRRoutePanel());
    const filterPanelRef = useRef(new VRFilterPanel());
    const nodeMeshesRef = useRef<Map<string, Mesh | InstancedMesh>>(new Map());
    const graphRenderer = useRef(new GraphRenderer());
    const vrMenuRef = useRef<{ dispose: () => void } | null>(null);
    const dataRef = useRef(data);
    dataRef.current = data;
    const onSelectRef = useRef(onSelect);
    onSelectRef.current = onSelect;
    const initialCameraFitDoneRef = useRef(false);

    const invokeSelect = useCallback((item: any, type: 'node' | 'edge' | null) => {
        onSelectRef.current?.(item, type);
    }, []);

    const fitPreviewCamera = useCallback((sceneInstance: Scene | null, force = false) => {
        if (!sceneInstance || xrHelperRef.current?.baseExperience?.state === WebXRState.IN_XR) {
            return;
        }
        const camera = sceneInstance.getCameraByName("camera") as ArcRotateCamera;
        if (!camera) {
            return;
        }
        if (force || !initialCameraFitDoneRef.current) {
            fitArcRotateCameraToGraph(camera, dataRef.current.nodes ?? []);
            initialCameraFitDoneRef.current = true;
        } else {
            updateArcRotateCameraClipPlanes(camera, dataRef.current.nodes ?? []);
        }
    }, []);

    const handleLayoutRequest = useCallback(async (algorithm: string) => {
        console.info("Layout changes from the VR menu are handled from the desktop overlay.", algorithm);
    }, []);


    useImperativeHandle(ref, () => ({
        resetCamera: () => {
            if (xrHelperRef.current && xrHelperRef.current.baseExperience) {
                xrHelperRef.current.baseExperience.camera.position.set(0, 0, 0);
            } else {
                fitPreviewCamera(scene, true);
            }
        },
        getCameraState: () => {
            if (xrHelperRef.current && xrHelperRef.current.baseExperience) {
                const cam = xrHelperRef.current.baseExperience.camera;
                return {
                    position: { x: cam.position.x, y: cam.position.y, z: cam.position.z },
                    rotation: { x: cam.rotation.x, y: cam.rotation.y, z: cam.rotation.z },
                    mode: 'VR'
                };
            }
            return { mode: 'VR_Preview' };
        }
    }));

    const { createVRMenu } = useVRMenu();

    // Local reset that forces visibility update (needed because handleShowNeighbors modifies locally)
    const handleLocalResetFilters = useCallback(() => {
        // Call parent callback
        if (onResetFilters) onResetFilters();
        // Force local visibility reset (in case parent state was already null)
        if (scene && nodeMeshesRef.current.size > 0) {
            graphRenderer.current.updateVisibility(null, null, nodeMeshesRef.current);
            graphRenderer.current.updateLabelVisibility(!!showLabels, nodeMeshesRef.current, scene, true);
            console.log("VR: Filters reset, all nodes visible");
        }
    }, [onResetFilters, scene, showLabels]);

    // Local Filter Change Handler
    const handleLocalFilterChange = useCallback((visibleNodes: Set<string> | null, visibleEdges: Set<string> | null) => {
        if (scene && nodeMeshesRef.current.size > 0) {
            graphRenderer.current.updateVisibility(visibleNodes, visibleEdges, nodeMeshesRef.current);
            graphRenderer.current.updateLabelVisibility(!!showLabels, nodeMeshesRef.current, scene, true);
        }
    }, [scene, showLabels]);

    // Handle Filter Panel Open
    const handleLocalOpenFilters = useCallback(() => {
        console.log("VR: Opening Filter Panel");
        if (filterPanelRef.current && scene) {
            // Pass current data
            const graphData = { nodes: data.nodes || [], edges: data.edges || [] };
            filterPanelRef.current.create(scene, graphData, {
                onFilterChange: handleLocalFilterChange,
                onClose: () => {
                    // Optional
                }
            });
        }
    }, [scene, data, handleLocalFilterChange]);

    const syncRoutePanel = useCallback(() => {
        if (!scene) return;
        const meta = dataRef.current?.metadata;
        const legs = meta?.route_legs;
        const routeMeta = meta?.route_meta;
        const inXr = xrHelperRef.current?.baseExperience?.state === WebXRState.IN_XR;
        const anchor = inXr
            ? xrHelperRef.current?.baseExperience?.camera
            : scene.getCameraByName('camera');
        routePanelRef.current.sync(scene, anchor ?? null, legs, routeMeta);
    }, [scene]);

    const vrUtilsRef = useRef({ createVRMenu, handleLayoutRequest, onXRStateChange, onResetFilters: handleLocalResetFilters, onToggleLabels, onOpenFilters: handleLocalOpenFilters, syncRoutePanel });
    useEffect(() => {
        vrUtilsRef.current = { createVRMenu, handleLayoutRequest, onXRStateChange, onResetFilters: handleLocalResetFilters, onToggleLabels, onOpenFilters: handleLocalOpenFilters, syncRoutePanel };
    }, [createVRMenu, handleLayoutRequest, onXRStateChange, handleLocalResetFilters, onToggleLabels, handleLocalOpenFilters, syncRoutePanel]);

    // Handle visibility updates (Nodes/Edges)
    useEffect(() => {
        if (scene && nodeMeshesRef.current.size > 0) {
            graphRenderer.current.updateVisibility(visibleNodeIds ?? null, visibleEdgeIds ?? null, nodeMeshesRef.current);
            // Sync labels with visibility WITHOUT resetting
            graphRenderer.current.updateLabelVisibility(!!showLabels, nodeMeshesRef.current, scene, true);
        }
    }, [visibleNodeIds, visibleEdgeIds, scene]); // Removed showLabels

    // Handle Label Toggle separately
    useEffect(() => {
        if (scene && nodeMeshesRef.current.size > 0) {
            // Just update labels, respecting current node visibility (handled inside updateLabelVisibility)
            graphRenderer.current.updateLabelVisibility(!!showLabels, nodeMeshesRef.current, scene, true);
        }
    }, [showLabels, scene]);

    const onSceneReady = useCallback(async (sceneInstance: Scene) => {
        setScene(sceneInstance);

        // Common Setup
        await setupCommonScene(sceneInstance);



        // Basic Camera for non-VR view (Preview)
        const camera = new ArcRotateCamera("camera", -Math.PI / 2, Math.PI / 2.5, 100, Vector3.Zero(), sceneInstance);
        const canvas = sceneInstance.getEngine().getRenderingCanvas();
        camera.attachControl(canvas, true);

        // Camera Optimization
        camera.wheelPrecision = 10;
        camera.pinchPrecision = 10;
        camera.panningSensibility = 20;
        camera.wheelDeltaPercentage = 0.05;

        // Prevent page zoom
        if (canvas) {
            const preventZoom = (e: WheelEvent) => { if (e.ctrlKey || e.metaKey) e.preventDefault(); };
            canvas.addEventListener('wheel', preventZoom, { passive: false });
        }


        // --- WebXR Setup (Using manual rays per article, native pointer disabled) ---
        try {
            // Configure to use local controller models (Oculus Touch) instead of online repository
            // This fixes issues where online repository models don't load
            WebXRMotionControllerManager.PrioritizeOnlineRepository = false;
            console.log("🎮 Using local controller models (PrioritizeOnlineRepository = false)");

            // 1. Initialize Default Experience
            const xr = await sceneInstance.createDefaultXRExperienceAsync({
                floorMeshes: [],
                disableTeleportation: true, // Disable teleport for Free Fly
                inputOptions: {
                    doNotLoadControllerMeshes: false,
                },
                uiOptions: {
                    sessionMode: 'immersive-vr',
                },
                outputCanvasOptions: {
                    canvasOptions: {
                        framebufferScaleFactor: 1 // Improves resolution (supersampling)
                    }
                }
            });

            // 2. Validate XR initialization
            if (!xr.baseExperience) {
                console.error("WebXR not supported or failed to initialize");
                return;
            }

            xrHelperRef.current = xr;
            console.log("WebXR initialized - using standard pointers");

            // Improve XR Rendering Quality (after XR is fully initialized)
            xr.baseExperience.onStateChangedObservable.add((state: WebXRState) => {
                if (state === WebXRState.IN_XR) {
                    console.log("VR Experience Started");
                    // Try to improve quality when entering XR
                    try {
                        if (xr.renderTarget && xr.renderTarget.xrLayer) {
                            xr.renderTarget.xrLayer.fixedFoveation = 0;
                        }
                    } catch (e) {
                        console.warn("Could not set XR quality:", e);
                    }
                    if (vrUtilsRef.current.onXRStateChange) {
                        vrUtilsRef.current.onXRStateChange(true);
                    }
                } else if (state === WebXRState.EXITING_XR) {
                    console.log("VR Experience Ending");
                    if (vrUtilsRef.current.onXRStateChange) {
                        vrUtilsRef.current.onXRStateChange(false);
                    }
                }
            });

            // 3. Setup Locomotion (Free Fly)
            const featuresManager = xr.baseExperience.featuresManager;
            const PITCH_SPEED = 0.5;
            const PITCH_THRESHOLD = 0.05;
            const MIN_PITCH = -Math.PI / 2 + 0.12;
            const MAX_PITCH = Math.PI / 2 - 0.12;
            let pitchRenderObserver: { remove: () => void } | null = null;

            const getLeftThumbstickY = (): number => {
                for (const controller of xr.input.controllers) {
                    if (controller.inputSource?.handedness !== 'left') {
                        continue;
                    }
                    const motionController = controller.motionController;
                    if (!motionController) {
                        continue;
                    }
                    for (const componentId of motionController.getComponentIds()) {
                        const component = motionController.getComponent(componentId);
                        if (component?.type !== 'thumbstick' || !component.axes) {
                            continue;
                        }
                        const y = component.axes.y ?? 0;
                        return Math.abs(y) > PITCH_THRESHOLD ? y : 0;
                    }
                }
                return 0;
            };

            const enablePitchLook = () => {
                if (pitchRenderObserver) {
                    return;
                }
                pitchRenderObserver = sceneInstance.onBeforeRenderObservable.add(() => {
                    if (xr.baseExperience.state !== WebXRState.IN_XR) {
                        return;
                    }
                    const pitchAxis = getLeftThumbstickY();
                    if (pitchAxis === 0) {
                        return;
                    }
                    const xrCamera = xr.input.xrCamera;
                    if (!xrCamera) {
                        return;
                    }
                    const deltaMillis = sceneInstance.getEngine().getDeltaTime();
                    const handednessSign = sceneInstance.useRightHandedSystem ? -1 : 1;
                    const pitchDelta =
                        deltaMillis * 0.001 * PITCH_SPEED * pitchAxis * handednessSign;
                    xrCamera.cameraRotation.x = Scalar.Clamp(
                        xrCamera.cameraRotation.x + pitchDelta,
                        MIN_PITCH,
                        MAX_PITCH,
                    );
                });
            };

            const disablePitchLook = () => {
                pitchRenderObserver?.remove();
                pitchRenderObserver = null;
            };

            try {
                featuresManager.enableFeature(
                    WebXRFeatureName.MOVEMENT,
                    'latest',
                    {
                        xrInput: xr.input,
                        movementOrientationFollowsViewerPose: false,
                        movementOrientationFollowsController: true, // Direction follows controller
                        movementSpeed: 0.5, // Reasonable speed
                        rotationSpeed: 0.5,
                        movementEnabled: true,
                        rotationEnabled: true, // Smooth rotation
                        movementThreshold: 0.05,
                        rotationThreshold: 0.05,
                    }
                );
                console.log('[VR] Free Fly Locomotion enabled');
            } catch (error) {
                console.error('[VR] Error enabling locomotion:', error);
            }
            // 6. Interactions (Menu & Grab)
            xr.input.onControllerAddedObservable.add((controller) => {
                controller.onMotionControllerInitObservable.add((motionController) => {
                    const ids = motionController.getComponentIds();

                    // A. Menu Toggle (A / X)
                    const primaryId = ids.find((id: string) => id === 'a-button' || id === 'x-button');
                    if (primaryId) {
                        const primaryButton = motionController.getComponent(primaryId);
                        if (primaryButton) {
                            primaryButton.onButtonStateChangedObservable.add(() => {
                                if (primaryButton.changes.pressed && primaryButton.pressed) {
                                    if (vrMenuRef.current) {
                                        vrMenuRef.current.dispose();
                                        vrMenuRef.current = null;
                                    } else {
                                        vrMenuRef.current = vrUtilsRef.current.createVRMenu(
                                            sceneInstance,
                                            xr,
                                            vrUtilsRef.current.handleLayoutRequest,
                                            vrUtilsRef.current.onResetFilters,
                                            vrUtilsRef.current.onToggleLabels
                                        );
                                    }
                                }
                            });
                        }
                    }

                    // B. Graph Grabbing (Grip / Squeeze)
                    const squeezeId = ids.find((id: string) => id === 'squeeze');
                    if (squeezeId) {
                        const squeeze = motionController.getComponent(squeezeId);
                        if (squeeze) {
                            squeeze.onButtonStateChangedObservable.add(() => {
                                const root = graphRenderer.current.getGraphRoot();
                                if (root) {
                                    if (squeeze.changes.pressed) {
                                        if (squeeze.pressed) {
                                            // Grab: Parent root to controller
                                            // Use rootMesh of controller for stability
                                            root.setParent(motionController.rootMesh || controller.pointer, true);
                                            console.log("Graph Grabbed");
                                        } else {
                                            // Release: Unparent
                                            root.setParent(null, true);
                                            console.log("Graph Released");
                                        }
                                    }
                                }
                            });
                        }
                    }
                });
            });

            // 7. HUD (Instructions)
            let hudTexture: GUI.AdvancedDynamicTexture | null = null;
            const createVRHUD = () => {
                // Ensure no duplicates
                if (hudTexture) {
                    hudTexture.dispose();
                    hudTexture = null;
                }
                const oldHud = sceneInstance.getMeshByName("VR_HUD");
                if (oldHud) oldHud.dispose();

                const hudPlane = MeshBuilder.CreatePlane("VR_HUD", { width: 0.6, height: 0.2 }, sceneInstance);
                // Parent to camera to stay in view
                hudPlane.parent = xr.baseExperience.camera;
                hudPlane.position = new Vector3(0, -0.4, 1); // Lower and further for discretion
                // Tilt up slightly
                hudPlane.rotation.x = -Math.PI / 8;

                hudTexture = GUI.AdvancedDynamicTexture.CreateForMesh(hudPlane, 512, 170); // Higher resolution relative to size
                hudTexture.background = "rgba(0, 0, 0, 0.2)"; // Very transparent

                const stack = new GUI.StackPanel();
                hudTexture.addControl(stack);

                const title = new GUI.TextBlock();
                title.text = "COMMANDES";
                title.color = "#4ade80"; // Green
                title.fontSize = 24;
                title.height = "40px";
                title.fontWeight = "bold";
                stack.addControl(title);

                const instructions = [
                    "Grip: Saisir Monde",
                    "Gauche: Tourner + Haut/Bas",
                    "Droit: Voler | A/X: Menu | Trigger: Select"
                ];

                instructions.forEach(line => {
                    const t = new GUI.TextBlock();
                    t.text = line;
                    t.color = "rgba(255, 255, 255, 0.8)";
                    t.fontSize = 18;
                    t.height = "30px";
                    stack.addControl(t);
                });
            };

            // 5. XR State Management
            xr.baseExperience.onStateChangedObservable.add((state: WebXRState) => {
                if (state === WebXRState.IN_XR) {
                    console.log("VR Experience Started");
                    createVRHUD(); // Create HUD
                    enablePitchLook();
                    vrUtilsRef.current.syncRoutePanel();
                    if (vrUtilsRef.current.onXRStateChange) {
                        vrUtilsRef.current.onXRStateChange(true);
                    }
                } else if (state === WebXRState.EXITING_XR) {
                    console.log("VR Experience Ending");

                    disablePitchLook();

                    // Cleanup
                    if (hudTexture) {
                        hudTexture.dispose();
                        hudTexture = null;
                    }
                    const hud = sceneInstance.getMeshByName("VR_HUD");
                    if (hud) hud.dispose();

                    vrUtilsRef.current.syncRoutePanel();
                    if (vrUtilsRef.current.onXRStateChange) {
                        vrUtilsRef.current.onXRStateChange(false);
                    }
                }
            });

        } catch (e) {
            console.error("WebXR Initialization Failed:", e);
        }

        setIsSceneReady(true);
    }, []);

    useEffect(() => {
        return () => {
            initialCameraFitDoneRef.current = false;
            routePanelRef.current.dispose();
            if (scene) {
                graphRenderer.current.disposeGraph(nodeMeshesRef.current, scene);
            }
        };
    }, [scene]);

    // Handle graph data updates
    useEffect(() => {
        if (!scene || !data) return;

        // --- Topology Handlers (defined here to capture current data) ---
        const handleShowNeighbors = (nodeId: string) => {
            console.log("VR: Show Neighbors for", nodeId);
            if (!data || !scene) return;
            const neighbors = new Set<string>();
            neighbors.add(nodeId);
            data.edges.forEach(e => {
                if (String(e.source) === nodeId) neighbors.add(String(e.target));
                if (String(e.target) === nodeId) neighbors.add(String(e.source));
            });
            graphRenderer.current.updateVisibility(neighbors, null, nodeMeshesRef.current);
            // Sync labels with updated visibility
            graphRenderer.current.updateLabelVisibility(!!showLabels, nodeMeshesRef.current, scene, true);
        };

        // Define VR Selection Callback
        const handleVRSelect = (itemData: any, type: string) => {
            console.log("VR Selection Triggered:", itemData);

            // Normal selection - show details panel
            if (detailsPanelRef.current) {
                detailsPanelRef.current.create(
                    scene,
                    itemData,
                    type,
                    xrHelperRef.current,
                    {
                        onShowNeighbors: handleShowNeighbors,
                        onResetFilters: handleLocalResetFilters
                    }
                );
            }
        };

        // Try to update positions only (faster, no flicker)
        const graphExists = nodeMeshesRef.current.size > 0;
        if (graphExists) {
            const updated = graphRenderer.current.updatePositions(data, nodeMeshesRef.current);
            if (updated) {
                console.log("VR: Graph positions updated in place");
                graphRenderer.current.updateVisibility(visibleNodeIds ?? null, visibleEdgeIds ?? null, nodeMeshesRef.current);
                graphRenderer.current.updateLabelVisibility(!!showLabels, nodeMeshesRef.current, scene, true);
                syncRoutePanel();
                return; // Success - no need to recreate
            }
            console.log("VR: Graph structure changed, recreating...");
        }

        // Full graph creation (first time or structure changed)
        graphRenderer.current.disposeGraph(nodeMeshesRef.current, scene);

        graphRenderer.current.createNodes(
            data,
            scene,
            nodeMeshesRef.current,
            invokeSelect,
            handleVRSelect,
            xrHelperRef,
            true // skip2DUI
        );
        graphRenderer.current.createEdges(
            data,
            scene,
            nodeMeshesRef.current,
            invokeSelect,
            handleVRSelect,
            xrHelperRef
        );

        graphRenderer.current.updateVisibility(visibleNodeIds ?? null, visibleEdgeIds ?? null, nodeMeshesRef.current);
        graphRenderer.current.updateLabelVisibility(!!showLabels, nodeMeshesRef.current, scene, true);
        syncRoutePanel();
    }, [scene, data, invokeSelect, visibleNodeIds, visibleEdgeIds, showLabels, handleLocalResetFilters, fitPreviewCamera, syncRoutePanel]);

    return (
        <div className="h-full w-full overflow-hidden rounded-xl bg-black/20 relative" style={{ touchAction: 'none' }}>
            {!isSceneReady && (
                <div className="absolute inset-0 flex items-center justify-center bg-black z-10">
                    <div className="flex flex-col items-center gap-4">
                        <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary-500 border-t-transparent"></div>
                        <p className="text-sm text-gray-400">Chargement de la scène VR...</p>
                    </div>
                </div>
            )}



            <SceneComponent
                antialias
                adaptToDeviceRatio
                onSceneReady={onSceneReady}
                id="graph-canvas-xr"
                className="h-full w-full outline-none"
                style={{ touchAction: 'none' }}
            />
        </div>
    );
});

GraphSceneXR.displayName = 'GraphSceneXR';

export default GraphSceneXR;
