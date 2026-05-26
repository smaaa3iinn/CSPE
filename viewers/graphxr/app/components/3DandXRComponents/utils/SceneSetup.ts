import { Scene, Color3, Vector3, HemisphericLight, MeshBuilder, StandardMaterial, GlowLayer } from '@babylonjs/core';

export const setupCommonScene = async (scene: Scene) => {
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

    // Space background
    const spaceSphere = MeshBuilder.CreateSphere("spaceSphere", { diameter: 1000 }, scene);
    const spaceMat = new StandardMaterial("spaceMat", scene);
    spaceMat.backFaceCulling = false;
    spaceMat.disableLighting = true;
    spaceMat.emissiveColor = new Color3(0.01, 0.02, 0.05);
    spaceSphere.material = spaceMat;

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
