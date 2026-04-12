import * as Cesium from 'cesium';
import { ParsedBuilding } from './SceneLoader';

const EXAG = 1.5;
const CHUNK_SIZE = 5000; // buildings per Primitive

export interface BuildingPrimitives {
  chunks: Cesium.Primitive[];
  destroy: (viewer: Cesium.Viewer) => void;
}

export function createBuildingPrimitives(
  buildings: ParsedBuilding[],
  viewer: Cesium.Viewer,
  signalValues?: Map<number, number>,
): BuildingPrimitives {
  const chunks: Cesium.Primitive[] = [];
  const nChunks = Math.ceil(buildings.length / CHUNK_SIZE);

  for (let ci = 0; ci < nChunks; ci++) {
    const start = ci * CHUNK_SIZE;
    const end = Math.min(start + CHUNK_SIZE, buildings.length);
    const instances: Cesium.GeometryInstance[] = [];

    for (let i = start; i < end; i++) {
      const b = buildings[i];
      if (b.nVerts < 3) continue;

      // Build polygon hierarchy from lon/lat ring
      const positions: Cesium.Cartesian3[] = [];
      for (let v = 0; v < b.nVerts; v++) {
        positions.push(Cesium.Cartesian3.fromDegrees(b.ring[v * 2], b.ring[v * 2 + 1]));
      }

      try {
        const instance = new Cesium.GeometryInstance({
          geometry: new Cesium.PolygonGeometry({
            polygonHierarchy: new Cesium.PolygonHierarchy(positions),
            extrudedHeight: b.height * EXAG,
            height: 0,
            vertexFormat: Cesium.PerInstanceColorAppearance.VERTEX_FORMAT,
          }),
          attributes: {
            color: Cesium.ColorGeometryInstanceAttribute.fromColor(
              signalValues?.has(i)
                ? signalToColor(signalValues.get(i)!)
                : Cesium.Color.fromBytes(176, 176, 176, 204),
            ),
          },
          id: `bldg_${i}`,
        });
        instances.push(instance);
      } catch {
        // Skip degenerate polygons
      }
    }

    if (instances.length === 0) continue;

    try {
      const primitive = new Cesium.Primitive({
        geometryInstances: instances,
        appearance: new Cesium.PerInstanceColorAppearance({
          translucent: false,
          flat: false,
        }),
        asynchronous: true,
      });
      viewer.scene.primitives.add(primitive);
      chunks.push(primitive);
    } catch (e) {
      console.warn(`Building primitive chunk ${ci} failed:`, e);
    }

    console.log(`BuildingsMesh: chunk ${ci + 1}/${nChunks} (${instances.length} buildings)`);
  }

  console.log(`BuildingsMesh: ${buildings.length} buildings in ${chunks.length} primitives`);

  return {
    chunks,
    destroy: (v: Cesium.Viewer) => {
      for (const p of chunks) {
        v.scene.primitives.remove(p);
      }
      chunks.length = 0;
    },
  };
}

export function recolorBuildings(
  buildings: ParsedBuilding[],
  viewer: Cesium.Viewer,
  signalValues: Map<number, number>,
  existing: BuildingPrimitives,
): BuildingPrimitives {
  existing.destroy(viewer);
  return createBuildingPrimitives(buildings, viewer, signalValues);
}

// Signal color stops (same as Map.tsx COLOR_STOPS dBm)
const SIGNAL_STOPS: [number, [number, number, number, number]][] = [
  [-30, [255, 30, 30, 235]],
  [-50, [255, 110, 0, 230]],
  [-60, [255, 190, 0, 225]],
  [-70, [220, 240, 0, 220]],
  [-80, [100, 225, 20, 215]],
  [-90, [0, 180, 120, 210]],
  [-100, [0, 130, 210, 205]],
  [-110, [40, 60, 200, 200]],
  [-120, [70, 30, 170, 195]],
  [-130, [50, 0, 80, 190]],
];

function signalToColor(dBm: number): Cesium.Color {
  if (dBm >= SIGNAL_STOPS[0][0]) {
    const c = SIGNAL_STOPS[0][1];
    return Cesium.Color.fromBytes(c[0], c[1], c[2], c[3]);
  }
  if (dBm <= SIGNAL_STOPS[SIGNAL_STOPS.length - 1][0]) {
    const c = SIGNAL_STOPS[SIGNAL_STOPS.length - 1][1];
    return Cesium.Color.fromBytes(c[0], c[1], c[2], c[3]);
  }
  for (let i = 0; i < SIGNAL_STOPS.length - 1; i++) {
    const [v0, c0] = SIGNAL_STOPS[i];
    const [v1, c1] = SIGNAL_STOPS[i + 1];
    if (dBm <= v0 && dBm >= v1) {
      const t = (dBm - v1) / (v0 - v1);
      return Cesium.Color.fromBytes(
        Math.round(c1[0] + (c0[0] - c1[0]) * t),
        Math.round(c1[1] + (c0[1] - c1[1]) * t),
        Math.round(c1[2] + (c0[2] - c1[2]) * t),
        Math.round(c1[3] + (c0[3] - c1[3]) * t),
      );
    }
  }
  return Cesium.Color.fromBytes(176, 176, 176, 204);
}
