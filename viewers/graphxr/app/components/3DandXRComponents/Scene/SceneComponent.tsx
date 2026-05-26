'use client';

import { useEffect, useRef } from "react";
import type { CanvasHTMLAttributes } from "react";
import { Engine, Scene } from "@babylonjs/core";
import "./index.css";

/** Props pour le composant Scene Babylon.js */
export interface SceneComponentProps extends CanvasHTMLAttributes<HTMLCanvasElement> {
  antialias?: boolean;
  engineOptions?: Record<string, unknown>;
  adaptToDeviceRatio?: boolean;
  sceneOptions?: Record<string, unknown>;
  onRender?: (scene: Scene) => void;
  onSceneReady?: (scene: Scene) => void;
}

/**
 * Composant wrapper pour intégrer Babylon.js dans React
 * Gère le cycle de vie du moteur et de la scène
 */
export default function SceneComponent({
  antialias,
  engineOptions,
  adaptToDeviceRatio,
  sceneOptions,
  onRender,
  onSceneReady,
  ...rest
}: SceneComponentProps) {
  const reactCanvas = useRef<HTMLCanvasElement>(null);
  const loaded = useRef(false);

  useEffect(() => {
    if (loaded.current) return;
    const { current: canvas } = reactCanvas;

    if (!canvas) return;

    // Moteur
    const engine = new Engine(
      canvas,
      antialias,
      engineOptions,
      adaptToDeviceRatio
    );

    // Scene
    const scene = new Scene(engine, sceneOptions);

    if (scene.isReady()) {
      if (onSceneReady) onSceneReady(scene);
    } else {
      scene.onReadyObservable.addOnce((scene) => {
        if (onSceneReady) onSceneReady(scene);
      });
    }

    // Boucle de rendu
    engine.runRenderLoop(() => {
      if (typeof onRender === "function") onRender(scene);
      // Only render if there is an active camera to avoid "No camera defined" errors during async init
      if (scene.activeCamera) {
        scene.render();
      }
    });

    const resize = () => {
      scene.getEngine().resize();
    };

    if (window) {
      window.addEventListener("resize", resize);
    }

    loaded.current = true;
    return () => {
      scene.getEngine().dispose();
      if (window) {
        window.removeEventListener("resize", resize);
      }
      loaded.current = false;
    };
  }, [antialias, engineOptions, adaptToDeviceRatio, sceneOptions, onRender, onSceneReady]);

  return <canvas ref={reactCanvas} {...rest} className="canvas" />;
}