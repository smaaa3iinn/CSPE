import { WebXRFeatureName } from '@babylonjs/core';

export function useVRLocomotion() {
    // Ce hook ne fait plus rien, la config VR est désormais dans GraphSceneXR.tsx selon la doc Babylon.js v8
    return { setupLocomotion: () => {} };
}
