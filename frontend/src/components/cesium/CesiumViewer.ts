import * as Cesium from 'cesium';
import { createTerrainProvider } from './TerrainProvider';
import { createBaseImagery } from './BaseImagery';

export interface CesiumViewerOptions {
  container: HTMLElement;
  darkMode: boolean;
  txPosition: [number, number]; // [lon, lat]
}

export function createCesiumViewer(options: CesiumViewerOptions): Cesium.Viewer {
  Cesium.Ion.defaultAccessToken = '';

  const terrainProvider = createTerrainProvider();
  const baseImagery = createBaseImagery(options.darkMode);

  const viewer = new Cesium.Viewer(options.container, {
    terrainProvider,
    baseLayer: new Cesium.ImageryLayer(baseImagery),
    scene3DOnly: true,
    animation: false,
    timeline: false,
    baseLayerPicker: false,
    geocoder: false,
    homeButton: false,
    sceneModePicker: false,
    selectionIndicator: false,
    infoBox: false,
    navigationHelpButton: false,
    fullscreenButton: false,
    creditContainer: document.createElement('div'),
    msaaSamples: 4,
    contextOptions: {
      webgl: {
        alpha: false,
        antialias: true,
        powerPreference: 'high-performance',
      },
    },
  });

  // Terrain exaggeration
  viewer.scene.verticalExaggeration = 1.5;

  // Lighting — summer afternoon Quebec sun
  viewer.scene.globe.enableLighting = true;
  viewer.scene.light = new Cesium.DirectionalLight({
    direction: new Cesium.Cartesian3(
      Math.sin(210 * Math.PI / 180) * Math.cos(45 * Math.PI / 180),
      Math.cos(210 * Math.PI / 180) * Math.cos(45 * Math.PI / 180),
      -Math.sin(45 * Math.PI / 180),
    ),
    color: Cesium.Color.fromCssColorString('#fffde8'),
    intensity: 2.0,
  });

  // Globe settings
  viewer.scene.globe.depthTestAgainstTerrain = true;
  viewer.scene.globe.showGroundAtmosphere = false;
  viewer.scene.fog.enabled = false;
  if (viewer.scene.skyAtmosphere) {
    viewer.scene.skyAtmosphere.show = true;
  }

  // Performance: FXAA post-process
  viewer.scene.postProcessStages.fxaa.enabled = true;

  // Set initial camera to Quebec City region
  const [lon, lat] = options.txPosition;
  viewer.camera.setView({
    destination: Cesium.Cartesian3.fromDegrees(lon, lat, 40000),
    orientation: {
      heading: 0,
      pitch: Cesium.Math.toRadians(-60),
      roll: 0,
    },
  });

  return viewer;
}

export function swapBaseImagery(viewer: Cesium.Viewer, darkMode: boolean): void {
  const baseLayer = viewer.imageryLayers.get(0);
  if (baseLayer) {
    viewer.imageryLayers.remove(baseLayer, true);
  }
  const newBase = createBaseImagery(darkMode);
  viewer.imageryLayers.addImageryProvider(newBase, 0);
  viewer.scene.requestRender();
}

export function destroyCesiumViewer(viewer: Cesium.Viewer): void {
  if (!viewer.isDestroyed()) {
    viewer.destroy();
  }
}
