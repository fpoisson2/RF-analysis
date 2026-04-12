import * as Cesium from 'cesium';

// Render the antenna SVG to a canvas for use as a billboard
function createAntennaCanvas(): HTMLCanvasElement {
  const canvas = document.createElement('canvas');
  canvas.width = 80;
  canvas.height = 100;
  const ctx = canvas.getContext('2d')!;
  ctx.scale(2, 2);

  // Shadow
  ctx.fillStyle = 'rgba(0,0,0,0.3)';
  ctx.beginPath();
  ctx.ellipse(20, 48, 6, 2, 0, 0, Math.PI * 2);
  ctx.fill();

  // Pole
  ctx.strokeStyle = '#f97316';
  ctx.lineWidth = 3;
  ctx.lineCap = 'round';
  ctx.beginPath();
  ctx.moveTo(20, 15);
  ctx.lineTo(20, 45);
  ctx.stroke();

  // Legs
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(20, 45); ctx.lineTo(12, 48);
  ctx.moveTo(20, 45); ctx.lineTo(28, 48);
  ctx.stroke();

  // Cross arms
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.moveTo(15, 30); ctx.lineTo(20, 25);
  ctx.moveTo(25, 30); ctx.lineTo(20, 25);
  ctx.stroke();

  // Radio waves
  ctx.strokeStyle = '#fbbf24';
  ctx.lineWidth = 1.5;

  // Right waves
  ctx.globalAlpha = 0.8;
  ctx.beginPath();
  ctx.moveTo(25, 12);
  ctx.quadraticCurveTo(30, 8, 25, 4);
  ctx.stroke();
  ctx.globalAlpha = 0.5;
  ctx.beginPath();
  ctx.moveTo(28, 15);
  ctx.quadraticCurveTo(35, 8, 28, 1);
  ctx.stroke();

  // Left waves
  ctx.globalAlpha = 0.8;
  ctx.beginPath();
  ctx.moveTo(15, 12);
  ctx.quadraticCurveTo(10, 8, 15, 4);
  ctx.stroke();
  ctx.globalAlpha = 0.5;
  ctx.beginPath();
  ctx.moveTo(12, 15);
  ctx.quadraticCurveTo(5, 8, 12, 1);
  ctx.stroke();

  // Center dot
  ctx.globalAlpha = 1.0;
  ctx.fillStyle = '#f97316';
  ctx.strokeStyle = 'white';
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.arc(20, 14, 3, 0, Math.PI * 2);
  ctx.fill();
  ctx.stroke();

  return canvas;
}

let cachedBillboard: HTMLCanvasElement | null = null;

export interface TxMarkerHandle {
  entity: Cesium.Entity;
  handler: Cesium.ScreenSpaceEventHandler;
  destroy: () => void;
}

export function createTxMarker(
  viewer: Cesium.Viewer,
  position: [number, number],
  onDragEnd: (lat: number, lon: number) => void,
  onClick: (lat: number, lon: number) => void,
): TxMarkerHandle {
  if (!cachedBillboard) {
    cachedBillboard = createAntennaCanvas();
  }

  const entity = viewer.entities.add({
    position: Cesium.Cartesian3.fromDegrees(position[0], position[1]),
    billboard: {
      image: cachedBillboard,
      verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
      heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
      scale: 0.5,
      disableDepthTestDistance: Number.POSITIVE_INFINITY,
    },
  });

  const handler = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas as HTMLCanvasElement);
  let dragging = false;

  handler.setInputAction((click: Cesium.ScreenSpaceEventHandler.PositionedEvent) => {
    const picked = viewer.scene.pick(click.position);
    if (Cesium.defined(picked) && picked.id === entity) {
      dragging = true;
      viewer.scene.screenSpaceCameraController.enableRotate = false;
      viewer.scene.screenSpaceCameraController.enableTranslate = false;
      viewer.scene.screenSpaceCameraController.enableZoom = false;
      viewer.scene.screenSpaceCameraController.enableTilt = false;
      viewer.scene.screenSpaceCameraController.enableLook = false;
      (viewer.scene.canvas as HTMLCanvasElement).style.cursor = 'grabbing';
    }
  }, Cesium.ScreenSpaceEventType.LEFT_DOWN);

  handler.setInputAction((movement: Cesium.ScreenSpaceEventHandler.MotionEvent) => {
    if (!dragging) return;
    const ray = viewer.camera.getPickRay(movement.endPosition);
    if (!ray) return;
    const cartesian = viewer.scene.globe.pick(ray, viewer.scene);
    if (!cartesian) return;
    entity.position = cartesian as any;
    viewer.scene.requestRender();
  }, Cesium.ScreenSpaceEventType.MOUSE_MOVE);

  handler.setInputAction(() => {
    if (dragging) {
      dragging = false;
      viewer.scene.screenSpaceCameraController.enableRotate = true;
      viewer.scene.screenSpaceCameraController.enableTranslate = true;
      viewer.scene.screenSpaceCameraController.enableZoom = true;
      viewer.scene.screenSpaceCameraController.enableTilt = true;
      viewer.scene.screenSpaceCameraController.enableLook = true;
      (viewer.scene.canvas as HTMLCanvasElement).style.cursor = '';

      const pos = entity.position?.getValue(Cesium.JulianDate.now());
      if (pos) {
        const carto = Cesium.Cartographic.fromCartesian(pos);
        onDragEnd(
          Cesium.Math.toDegrees(carto.latitude),
          Cesium.Math.toDegrees(carto.longitude),
        );
      }
    }
  }, Cesium.ScreenSpaceEventType.LEFT_UP);

  // Click-to-place (on globe, not on marker)
  handler.setInputAction((click: Cesium.ScreenSpaceEventHandler.PositionedEvent) => {
    if (dragging) return;
    const picked = viewer.scene.pick(click.position);
    if (Cesium.defined(picked) && picked.id === entity) return;

    const ray = viewer.camera.getPickRay(click.position);
    if (!ray) return;
    const cartesian = viewer.scene.globe.pick(ray, viewer.scene);
    if (!cartesian) return;

    const carto = Cesium.Cartographic.fromCartesian(cartesian);
    const lat = Cesium.Math.toDegrees(carto.latitude);
    const lon = Cesium.Math.toDegrees(carto.longitude);

    entity.position = cartesian as any;
    onClick(lat, lon);
    viewer.scene.requestRender();
  }, Cesium.ScreenSpaceEventType.LEFT_CLICK);

  return {
    entity,
    handler,
    destroy: () => {
      handler.destroy();
      viewer.entities.remove(entity);
    },
  };
}

export function updateTxMarkerPosition(
  entity: Cesium.Entity,
  position: [number, number],
): void {
  const current = entity.position?.getValue(Cesium.JulianDate.now());
  if (current) {
    const carto = Cesium.Cartographic.fromCartesian(current);
    const curLon = Cesium.Math.toDegrees(carto.longitude);
    const curLat = Cesium.Math.toDegrees(carto.latitude);
    if (Math.abs(curLon - position[0]) < 0.000001 && Math.abs(curLat - position[1]) < 0.000001) {
      return;
    }
  }
  entity.position = Cesium.Cartesian3.fromDegrees(position[0], position[1]) as any;
}
