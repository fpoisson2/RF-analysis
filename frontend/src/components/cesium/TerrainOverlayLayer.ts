import * as Cesium from 'cesium';

const LAYER_ID = 'terrain-overlay';

export async function addTerrainOverlay(
  viewer: Cesium.Viewer,
  terrainLayer: string,
  txPosition: [number, number],
  radius: number,
): Promise<Cesium.ImageryLayer | null> {
  removeTerrainOverlay(viewer);

  const lat = txPosition[1];
  const lon = txPosition[0];
  const res = Math.max(2, (2 * radius * 1000) / 500);

  try {
    const resp = await fetch(
      `/api/terrain/render?lat=${lat}&lon=${lon}&radius_km=${radius}&resolution_m=${res}&mode=${terrainLayer}`,
    );
    const data = await resp.json();
    if (!data.image_url) return null;

    const { north, south, east, west } = data.bounds;

    const provider = new Cesium.SingleTileImageryProvider({
      url: data.image_url,
      rectangle: Cesium.Rectangle.fromDegrees(west, south, east, north),
    });

    const layer = viewer.imageryLayers.addImageryProvider(provider);
    layer.alpha = 0.6;
    (layer as any)._rfTerrainId = LAYER_ID;

    // Move below coverage layer if it exists
    for (let i = viewer.imageryLayers.length - 1; i >= 0; i--) {
      const l = viewer.imageryLayers.get(i);
      if ((l as any)._rfCoverageId) {
        // Coverage should be above terrain overlay
        const terrainIdx = viewer.imageryLayers.indexOf(layer);
        const covIdx = viewer.imageryLayers.indexOf(l);
        if (terrainIdx > covIdx) {
          viewer.imageryLayers.lower(layer);
        }
        break;
      }
    }

    return layer;
  } catch (e) {
    console.error('Terrain overlay load failed:', e);
    return null;
  }
}

export function removeTerrainOverlay(viewer: Cesium.Viewer): void {
  for (let i = viewer.imageryLayers.length - 1; i >= 0; i--) {
    const layer = viewer.imageryLayers.get(i);
    if ((layer as any)._rfTerrainId === LAYER_ID) {
      viewer.imageryLayers.remove(layer, true);
    }
  }
}
