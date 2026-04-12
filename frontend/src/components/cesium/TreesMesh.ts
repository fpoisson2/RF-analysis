import * as Cesium from 'cesium';
import { ParsedTree } from './SceneLoader';

const EXAG = 1.5;
const CHUNK_SIZE = 10000;

const GREENS = [
  Cesium.Color.fromCssColorString('#2e7d32'),
  Cesium.Color.fromCssColorString('#388e3c'),
  Cesium.Color.fromCssColorString('#43a047'),
  Cesium.Color.fromCssColorString('#1b5e20'),
  Cesium.Color.fromCssColorString('#336a1c'),
  Cesium.Color.fromCssColorString('#4caf50'),
];

export interface TreePrimitives {
  primitives: Cesium.Primitive[];
  destroy: (viewer: Cesium.Viewer) => void;
  setVisible: (visible: boolean) => void;
}

export function createTreePrimitives(
  trees: ParsedTree[],
  viewer: Cesium.Viewer,
): TreePrimitives {
  const primitives: Cesium.Primitive[] = [];
  const nChunks = Math.ceil(trees.length / CHUNK_SIZE);

  for (let ci = 0; ci < nChunks; ci++) {
    const start = ci * CHUNK_SIZE;
    const end = Math.min(start + CHUNK_SIZE, trees.length);

    // Canopy instances
    const canopyInstances: Cesium.GeometryInstance[] = [];

    for (let i = start; i < end; i++) {
      const tree = trees[i];
      const h = tree.height * EXAG;
      const canopyR = Math.max(1.5, tree.height * 0.35);
      const canopyH = h * 0.7;
      const trunkH = h * 0.3;

      try {
        // Canopy as a cylinder (simple, fast)
        const position = Cesium.Cartesian3.fromDegrees(tree.lon, tree.lat, trunkH + canopyH / 2);
        const modelMatrix = Cesium.Transforms.eastNorthUpToFixedFrame(position);

        canopyInstances.push(new Cesium.GeometryInstance({
          geometry: new Cesium.CylinderGeometry({
            length: canopyH,
            topRadius: canopyR * 0.3,
            bottomRadius: canopyR,
            slices: 6,
            vertexFormat: Cesium.PerInstanceColorAppearance.VERTEX_FORMAT,
          }),
          modelMatrix,
          attributes: {
            color: Cesium.ColorGeometryInstanceAttribute.fromColor(
              GREENS[i % GREENS.length].withAlpha(0.85),
            ),
          },
        }));
      } catch {
        // Skip bad trees
      }
    }

    if (canopyInstances.length > 0) {
      try {
        const canopyPrim = new Cesium.Primitive({
          geometryInstances: canopyInstances,
          appearance: new Cesium.PerInstanceColorAppearance({
            translucent: true,
            flat: false,
          }),
          asynchronous: true,
        });
        viewer.scene.primitives.add(canopyPrim);
        primitives.push(canopyPrim);
      } catch (e) {
        console.warn(`Tree canopy chunk ${ci} failed:`, e);
      }
    }

    console.log(`TreesMesh: chunk ${ci + 1}/${nChunks} (${end - start} trees)`);
  }

  console.log(`TreesMesh: ${trees.length} trees in ${primitives.length} primitives`);

  return {
    primitives,
    destroy: (v: Cesium.Viewer) => {
      for (const p of primitives) {
        v.scene.primitives.remove(p);
      }
      primitives.length = 0;
    },
    setVisible: (visible: boolean) => {
      for (const p of primitives) {
        p.show = visible;
      }
    },
  };
}
