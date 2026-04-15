import * as Cesium from 'cesium';
import { PathResponse } from '../../types';

export interface PathLineHandle {
  destroy: () => void;
  update: (tx: [number, number], rx: [number, number], path: PathResponse | null) => void;
  setHover: (distance_m: number | null) => void;
}

export function createPathLine(viewer: Cesium.Viewer): PathLineHandle {
  const entities: Cesium.Entity[] = [];
  let hoverEntity: Cesium.Entity | null = null;
  let currentPath: PathResponse | null = null;
  let currentTx: [number, number] | null = null;
  let currentRx: [number, number] | null = null;

  const clear = () => {
    for (const e of entities) viewer.entities.remove(e);
    entities.length = 0;
  };

  const rebuild = () => {
    clear();
    if (!currentTx || !currentRx) return;

    // Elevation multiplier matches the rest of the scene (buildings/trees).
    const Z = 1.5;

    const txLon = currentTx[0], txLat = currentTx[1];
    const rxLon = currentRx[0], rxLat = currentRx[1];

    // LoS line (dashed yellow) in 3D — from TX top to RX top if we know heights.
    const stats = currentPath?.stats;
    const txH = (stats?.tx_elevation ?? 0) + (stats?.tx_height_agl ?? 30);
    const rxH = (stats?.rx_elevation ?? 0) + (stats?.rx_height_agl ?? 2);

    const losEntity = viewer.entities.add({
      polyline: {
        positions: [
          Cesium.Cartesian3.fromDegrees(txLon, txLat, txH * Z),
          Cesium.Cartesian3.fromDegrees(rxLon, rxLat, rxH * Z),
        ],
        width: 2,
        material: new Cesium.PolylineDashMaterialProperty({
          color: Cesium.Color.fromCssColorString('#fbbf24'),
          dashLength: 16,
        }),
        arcType: Cesium.ArcType.NONE,
      },
    });
    entities.push(losEntity);

    // Also draw a thin LoS on the ground for map-view visibility.
    const losGround = viewer.entities.add({
      polyline: {
        positions: Cesium.Cartesian3.fromDegreesArray([txLon, txLat, rxLon, rxLat]),
        width: 1,
        material: Cesium.Color.fromCssColorString('#fbbf24').withAlpha(0.4),
        clampToGround: true,
      },
    });
    entities.push(losGround);

    // --- 3D Fresnel zone ellipsoid ---
    // Approximates the 1st Fresnel zone as a rotational ellipsoid around the
    // TX→RX axis. Semi-major = half link length, semi-minor = max Fresnel
    // radius (midpoint).
    if (currentPath && currentPath.fresnel_radius && currentPath.fresnel_radius.length) {
      const fresnelMax = Math.max(...currentPath.fresnel_radius);
      const totalDist = currentPath.distances[currentPath.distances.length - 1] || 1;

      if (fresnelMax > 0.5 && totalDist > 1) {
        const txCart = Cesium.Cartesian3.fromDegrees(txLon, txLat, txH * Z);
        const rxCart = Cesium.Cartesian3.fromDegrees(rxLon, rxLat, rxH * Z);
        const midCart = Cesium.Cartesian3.midpoint(txCart, rxCart, new Cesium.Cartesian3());

        // Axis direction (TX → RX) in world coords
        const axis = Cesium.Cartesian3.subtract(rxCart, txCart, new Cesium.Cartesian3());
        const length3D = Cesium.Cartesian3.magnitude(axis);
        const axisUnit = Cesium.Cartesian3.normalize(axis, new Cesium.Cartesian3());

        // Build an orientation quaternion that rotates local X (1,0,0) → axisUnit.
        // Cesium ellipsoid radii are (x,y,z) along local frame axes; the
        // entity orientation rotates that local frame. We pre-multiply by the
        // ENU frame at the midpoint so the resulting orientation points x
        // along the link.
        const enu = Cesium.Transforms.eastNorthUpToFixedFrame(midCart);
        const invEnu = Cesium.Matrix4.inverseTransformation(enu, new Cesium.Matrix4());
        const axisLocal = Cesium.Matrix4.multiplyByPointAsVector(invEnu, axisUnit, new Cesium.Cartesian3());
        Cesium.Cartesian3.normalize(axisLocal, axisLocal);

        // Cesium HPR at midCart with ENU basis. Default body X points east.
        // A positive heading (rotation about -Z) rotates body X east → south.
        // So body X after heading h = (cos h, -sin h) in (east, north). For X
        // to point to bearing β (CW from north): (sin β, cos β) = (cos h, -sin h)
        // ⇒ h = β - π/2.
        const bearingRad = Math.atan2(axisLocal.x, axisLocal.y); // from north, CW
        const cesiumHeading = bearingRad - Math.PI / 2;
        const pitch = Math.asin(Cesium.Math.clamp(axisLocal.z, -1, 1));

        const hpr = new Cesium.HeadingPitchRoll(cesiumHeading, pitch, 0);
        const orientation = Cesium.Transforms.headingPitchRollQuaternion(midCart, hpr);

        // The default "forward" of the ellipsoid is its local X axis, which
        // after a HPR rotation corresponds to the body's "forward" (north when
        // heading=0). We use radii (length/2, fresnelMax, fresnelMax) — Cesium
        // ellipsoid renders with radii along local axes AFTER orientation,
        // so X becomes the TX→RX axis.
        const fresnelEntity = viewer.entities.add({
          position: midCart,
          orientation: orientation as any,
          ellipsoid: {
            radii: new Cesium.Cartesian3(length3D / 2, fresnelMax, fresnelMax),
            material: Cesium.Color.fromCssColorString('#fbbf24').withAlpha(0.18),
            outline: true,
            outlineColor: Cesium.Color.fromCssColorString('#fbbf24').withAlpha(0.6),
            slicePartitions: 24,
            stackPartitions: 16,
          },
        });
        entities.push(fresnelEntity);
      }
    }

    // Obstruction markers on the actual terrain surface.
    if (currentPath && currentPath.obstructions) {
      const dx = rxLon - txLon;
      const dy = rxLat - txLat;
      const totalDist = currentPath.distances[currentPath.distances.length - 1] || 1;

      for (const obs of currentPath.obstructions) {
        const t = obs.peak_m / totalDist;
        const lon = txLon + dx * t;
        const lat = txLat + dy * t;
        const color = obs.type === 'los' ? '#ef4444' : '#f97316';

        const e = viewer.entities.add({
          position: Cesium.Cartesian3.fromDegrees(lon, lat, obs.peak_elevation * Z),
          point: {
            pixelSize: 10,
            color: Cesium.Color.fromCssColorString(color),
            outlineColor: Cesium.Color.WHITE,
            outlineWidth: 2,
            heightReference: Cesium.HeightReference.NONE,
            disableDepthTestDistance: Number.POSITIVE_INFINITY,
          },
        });
        entities.push(e);
      }
    }
  };

  return {
    update: (tx, rx, path) => {
      currentTx = tx;
      currentRx = rx;
      currentPath = path;
      rebuild();
      viewer.scene.requestRender();
    },
    setHover: (distance_m) => {
      if (hoverEntity) {
        viewer.entities.remove(hoverEntity);
        hoverEntity = null;
      }
      if (distance_m == null || !currentTx || !currentRx || !currentPath) {
        viewer.scene.requestRender();
        return;
      }
      const totalDist = currentPath.distances[currentPath.distances.length - 1] || 1;
      const t = Math.max(0, Math.min(1, distance_m / totalDist));
      const lon = currentTx[0] + (currentRx[0] - currentTx[0]) * t;
      const lat = currentTx[1] + (currentRx[1] - currentTx[1]) * t;

      // Find sample for elevation
      const idx = Math.round(t * (currentPath.distances.length - 1));
      const z = (currentPath.surface_elevations?.[idx] ?? currentPath.elevations[idx] ?? 0) * 1.5;

      hoverEntity = viewer.entities.add({
        position: Cesium.Cartesian3.fromDegrees(lon, lat, z + 5),
        point: {
          pixelSize: 8,
          color: Cesium.Color.CYAN,
          outlineColor: Cesium.Color.WHITE,
          outlineWidth: 2,
          disableDepthTestDistance: Number.POSITIVE_INFINITY,
        },
      });
      viewer.scene.requestRender();
    },
    destroy: () => {
      clear();
      if (hoverEntity) viewer.entities.remove(hoverEntity);
    },
  };
}
