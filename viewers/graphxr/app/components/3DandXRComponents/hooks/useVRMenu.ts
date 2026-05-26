import { Scene, WebXRDefaultExperience } from '@babylonjs/core';
import { VRMenuPanel } from '../components/VRMenuPanel';

export const useVRMenu = () => {

    // Simple VR Menu using Babylon GUI 3D (Refactored to use VRMenuPanel)
    const createVRMenu = (
        scene: Scene,
        xr: WebXRDefaultExperience,
        onLayoutRequest: (layoutName: string) => void,
        onResetFilters?: () => void,
        onToggleLabels?: () => void,
        onOpenFilters?: () => void,
        currentLayout: string = 'forceatlas2'
    ) => {
        const menuPanel = new VRMenuPanel();

        // Create Menu
        menuPanel.create(scene, {
            onLayoutRequest,
            onResetFilters,
            onToggleLabels,
            onOpenFilters,
            onClose: () => {
                // Optional cleanup if needed
            }
        }, currentLayout);

        return {
            dispose: () => {
                menuPanel.dispose();
            }
        };
    };

    return { createVRMenu };
};
