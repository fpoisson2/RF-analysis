/**
 * Renders millions of trees using merged geometry buffers.
 * Each chunk = one Cesium.Primitive containing N trees as a single merged mesh.
 * Tree shape: tapered cone (canopy) — 6-slice cylinder with smaller top radius.
 */
import * as Cesium from 'cesium';
import { ParsedTree } from './SceneLoader';

const EXAG = 1.5;
const CHUNK_SIZE = 50000; // trees per primitive — 50k keeps memory per chunk ~35MB
const SLICES = 6;

// Green color palette (RGB 0-1)
const GREENS: [number, number, number][] = [
  [0.18, 0.49, 0.20],
  [0.22, 0.56, 0.24],
  [0.26, 0.63, 0.28],
  [0.11, 0.37, 0.13],
  [0.20, 0.41, 0.12],
  [0.30, 0.69, 0.31],
];

// Pre-compute unit cone template (bottom radius=1, top radius=0.3, height=1)
interface ConeTemplate {
  positions: number[];  // flat xyz
  normals: number[];    // flat xyz
  indices: number[];
  vertCount: number;
  idxCount: number;
}

function buildConeTemplate(): ConeTemplate {
  const positions: number[] = [];
  const normals: number[] = [];
  const indices: number[] = [];

  const topR = 0.3, botR = 1.0;

  // Bottom center (0)
  positions.push(0, 0, 0);
  normals.push(0, 0, -1);

  // Bottom ring (1..SLICES)
  for (let i = 0; i < SLICES; i++) {
    const a = (2 * Math.PI * i) / SLICES;
    positions.push(Math.cos(a) * botR, Math.sin(a) * botR, 0);
    normals.push(0, 0, -1);
  }

  // Top center (SLICES+1)
  positions.push(0, 0, 1);
  normals.push(0, 0, 1);

  // Top ring (SLICES+2 .. 2*SLICES+1)
  for (let i = 0; i < SLICES; i++) {
    const a = (2 * Math.PI * i) / SLICES;
    positions.push(Math.cos(a) * topR, Math.sin(a) * topR, 1);
    normals.push(0, 0, 1);
  }

  // Bottom cap triangles
  for (let i = 0; i < SLICES; i++) {
    indices.push(0, 1 + ((i + 1) % SLICES), 1 + i);
  }

  // Top cap triangles
  const tc = SLICES + 1;
  for (let i = 0; i < SLICES; i++) {
    indices.push(tc, tc + 1 + i, tc + 1 + ((i + 1) % SLICES));
  }

  // Side triangles
  for (let i = 0; i < SLICES; i++) {
    const b0 = 1 + i;
    const b1 = 1 + ((i + 1) % SLICES);
    const t0 = tc + 1 + i;
    const t1 = tc + 1 + ((i + 1) % SLICES);
    indices.push(b0, t0, t1);
    indices.push(b0, t1, b1);
  }

  return {
    positions,
    normals,
    indices,
    vertCount: positions.length / 3,
    idxCount: indices.length,
  };
}

const TEMPLATE = buildConeTemplate();

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
  const tpl = TEMPLATE;

  for (let ci = 0; ci < nChunks; ci++) {
    const start = ci * CHUNK_SIZE;
    const end = Math.min(start + CHUNK_SIZE, trees.length);
    const count = end - start;

    const totalVerts = count * tpl.vertCount;
    const totalIdx = count * tpl.idxCount;

    const positions = new Float64Array(totalVerts * 3);
    const normals = new Float32Array(totalVerts * 3);
    const colors = new Float32Array(totalVerts * 4);
    const indices = new Uint32Array(totalIdx);

    // Reusable scratch objects
    const localPos = new Cesium.Cartesian3();
    const worldPos = new Cesium.Cartesian3();
    const localNrm = new Cesium.Cartesian3();
    const worldNrm = new Cesium.Cartesian3();

    for (let ti = 0; ti < count; ti++) {
      const tree = trees[start + ti];
      const h = tree.height * EXAG;
      const canopyR = Math.max(1.5, tree.height * 0.35);
      const canopyH = h * 0.7;
      const trunkH = h * 0.3;

      // ENU transform at tree base (ground elevation + trunk height, with exaggeration)
      const baseZ = tree.groundZ * EXAG + trunkH;
      const origin = Cesium.Cartesian3.fromDegrees(tree.lon, tree.lat, baseZ);
      const transform = Cesium.Transforms.eastNorthUpToFixedFrame(origin);

      const vBase = ti * tpl.vertCount;
      const iBase = ti * tpl.idxCount;

      // Transform template vertices
      for (let v = 0; v < tpl.vertCount; v++) {
        const lx = tpl.positions[v * 3] * canopyR;
        const ly = tpl.positions[v * 3 + 1] * canopyR;
        const lz = tpl.positions[v * 3 + 2] * canopyH;

        localPos.x = lx; localPos.y = ly; localPos.z = lz;
        Cesium.Matrix4.multiplyByPoint(transform, localPos, worldPos);

        const pi = (vBase + v) * 3;
        positions[pi] = worldPos.x;
        positions[pi + 1] = worldPos.y;
        positions[pi + 2] = worldPos.z;

        // Transform normal
        localNrm.x = tpl.normals[v * 3];
        localNrm.y = tpl.normals[v * 3 + 1];
        localNrm.z = tpl.normals[v * 3 + 2];
        Cesium.Matrix4.multiplyByPointAsVector(transform, localNrm, worldNrm);
        const len = Cesium.Cartesian3.magnitude(worldNrm);
        if (len > 0) {
          worldNrm.x /= len; worldNrm.y /= len; worldNrm.z /= len;
        }

        normals[pi] = worldNrm.x;
        normals[pi + 1] = worldNrm.y;
        normals[pi + 2] = worldNrm.z;

        // Color with vertical shading
        const shade = 0.6 + 0.4 * tpl.positions[v * 3 + 2];
        const gc = GREENS[(start + ti) % GREENS.length];
        const ci4 = (vBase + v) * 4;
        colors[ci4] = gc[0] * shade;
        colors[ci4 + 1] = gc[1] * shade;
        colors[ci4 + 2] = gc[2] * shade;
        colors[ci4 + 3] = 0.85;
      }

      // Indices (offset by vertex base)
      for (let j = 0; j < tpl.idxCount; j++) {
        indices[iBase + j] = vBase + tpl.indices[j];
      }
    }

    // Compute bounding sphere from center of chunk
    const midTree = trees[start + Math.floor(count / 2)];
    const center = Cesium.Cartesian3.fromDegrees(midTree.lon, midTree.lat, midTree.groundZ * EXAG + 50);
    // Estimate radius: max distance from center to any tree in chunk
    let maxDist = 0;
    for (let ti = 0; ti < count; ti += Math.max(1, Math.floor(count / 100))) {
      const t = trees[start + ti];
      const p = Cesium.Cartesian3.fromDegrees(t.lon, t.lat, 0);
      const d = Cesium.Cartesian3.distance(center, p);
      if (d > maxDist) maxDist = d;
    }
    const boundingSphere = new Cesium.BoundingSphere(center, maxDist + 500);

    try {
      const geometry = new Cesium.Geometry({
        attributes: {
          position: new Cesium.GeometryAttribute({
            componentDatatype: Cesium.ComponentDatatype.DOUBLE,
            componentsPerAttribute: 3,
            values: positions,
          }),
          normal: new Cesium.GeometryAttribute({
            componentDatatype: Cesium.ComponentDatatype.FLOAT,
            componentsPerAttribute: 3,
            values: normals,
          }),
          color: new Cesium.GeometryAttribute({
            componentDatatype: Cesium.ComponentDatatype.FLOAT,
            componentsPerAttribute: 4,
            values: colors,
          }),
        } as any,
        indices,
        primitiveType: Cesium.PrimitiveType.TRIANGLES,
        boundingSphere,
      });

      const primitive = new Cesium.Primitive({
        geometryInstances: new Cesium.GeometryInstance({ geometry }),
        appearance: new Cesium.PerInstanceColorAppearance({
          flat: false,
          translucent: true,
          renderState: {
            depthTest: { enabled: true },
            cull: { enabled: true, face: Cesium.CullFace.BACK },
            blending: Cesium.BlendingState.ALPHA_BLEND,
          },
        }),
        asynchronous: false,
      });

      viewer.scene.primitives.add(primitive);
      primitives.push(primitive);
    } catch (e) {
      console.warn(`Tree chunk ${ci} failed:`, e);
    }

    console.log(`TreesMesh: chunk ${ci + 1}/${nChunks} (${count} trees, ${(positions.byteLength / 1e6).toFixed(1)}MB)`);
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
