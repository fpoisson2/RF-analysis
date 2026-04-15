import * as Cesium from 'cesium';

function createRxCanvas(): HTMLCanvasElement {
  const canvas = document.createElement('canvas');
  canvas.width = 72;
  canvas.height = 90;
  const ctx = canvas.getContext('2d')!;
  ctx.scale(2, 2);

  // Shadow
  ctx.fillStyle = 'rgba(0,0,0,0.3)';
  ctx.beginPath();
  ctx.ellipse(18, 42, 6, 2, 0, 0, Math.PI * 2);
  ctx.fill();

  // Pin body
  ctx.fillStyle = '#3b82f6';
  ctx.strokeStyle = 'white';
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(18, 5);
  ctx.bezierCurveTo(8, 5, 5, 14, 5, 19);
  ctx.bezierCurveTo(5, 28, 18, 40, 18, 40);
  ctx.bezierCurveTo(18, 40, 31, 28, 31, 19);
  ctx.bezierCurveTo(31, 14, 28, 5, 18, 5);
  ctx.closePath();
  ctx.fill();
  ctx.stroke();

  // Inner ring
  ctx.fillStyle = 'white';
  ctx.beginPath();
  ctx.arc(18, 19, 6, 0, Math.PI * 2);
  ctx.fill();

  // Dot
  ctx.fillStyle = '#1e40af';
  ctx.beginPath();
  ctx.arc(18, 19, 3, 0, Math.PI * 2);
  ctx.fill();

  return canvas;
}

let cached: HTMLCanvasElement | null = null;

export interface RxMarkerHandle {
  entity: Cesium.Entity;
  destroy: () => void;
  setPosition: (lat: number, lon: number) => void;
}

export function createRxMarker(
  viewer: Cesium.Viewer,
  position: [number, number] | null,
  onDragEnd: (lat: number, lon: number) => void,
): RxMarkerHandle {
  if (!cached) cached = createRxCanvas();

  const entity = viewer.entities.add({
    position: position
      ? Cesium.Cartesian3.fromDegrees(position[0], position[1])
      : Cesium.Cartesian3.fromDegrees(0, 0),
    billboard: {
      image: cached,
      verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
      heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
      scale: 0.5,
      disableDepthTestDistance: Number.POSITIVE_INFINITY,
      show: position !== null,
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
    if (!dragging) return;
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
  }, Cesium.ScreenSpaceEventType.LEFT_UP);

  return {
    entity,
    setPosition: (lat: number, lon: number) => {
      entity.position = Cesium.Cartesian3.fromDegrees(lon, lat) as any;
      if (entity.billboard) entity.billboard.show = true as any;
    },
    destroy: () => {
      handler.destroy();
      viewer.entities.remove(entity);
    },
  };
}
