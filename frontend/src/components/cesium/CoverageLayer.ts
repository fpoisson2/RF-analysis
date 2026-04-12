import * as Cesium from 'cesium';
import { AreaResponse } from '../../types';

const LAYER_ID = 'rf-coverage';

export function addCoverageLayer(
  viewer: Cesium.Viewer,
  result: AreaResponse,
): Cesium.ImageryLayer {
  // Remove existing coverage layer
  removeCoverageLayer(viewer);

  const { north, south, east, west } = result.bounds;
  const cacheBuster = Date.now();

  // Calculate optimal maxzoom from coverage resolution
  const covWidthDeg = east - west;
  const covPixels = result.stats?.grid_size || 666;
  const pixelDeg = covWidthDeg / covPixels;
  const optimalMaxZoom = Math.min(15, Math.max(10, Math.floor(Math.log2(360 / (pixelDeg * 512)))));

  const provider = new Cesium.UrlTemplateImageryProvider({
    url: window.location.origin + `/api/coverage/tiles/{z}/{x}/{y}.png?t=${cacheBuster}`,
    rectangle: Cesium.Rectangle.fromDegrees(west, south, east, north),
    minimumLevel: 8,
    maximumLevel: optimalMaxZoom,
    tileWidth: 512,
    tileHeight: 512,
  });

  const layer = viewer.imageryLayers.addImageryProvider(provider);
  layer.alpha = 0.55;
  (layer as any)._rfCoverageId = LAYER_ID;
  return layer;
}

export function removeCoverageLayer(viewer: Cesium.Viewer): void {
  for (let i = viewer.imageryLayers.length - 1; i >= 0; i--) {
    const layer = viewer.imageryLayers.get(i);
    if ((layer as any)._rfCoverageId === LAYER_ID) {
      viewer.imageryLayers.remove(layer, true);
    }
  }
}
