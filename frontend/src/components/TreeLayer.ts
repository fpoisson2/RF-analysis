/**
 * Three.js MapLibre custom layer — instanced 3D trees.
 *
 * Each tree = brown cylinder (trunk) + green icosphere (canopy).
 * Heights from LiDAR are applied per-instance via InstancedMesh.
 */
import * as THREE from 'three';
import maplibregl from 'maplibre-gl';

interface TreeData {
  lng: number;
  lat: number;
  height: number; // canopy height in meters (from LiDAR)
}

const TERRAIN_EXAG = 1.5;

export function createTreeLayer(trees: TreeData[]): maplibregl.CustomLayerInterface {
  let renderer: THREE.WebGLRenderer;
  let scene: THREE.Scene;
  let camera: THREE.Camera;

  return {
    id: 'trees-3d',
    type: 'custom' as const,
    renderingMode: '3d',

    onAdd(map: maplibregl.Map, gl: WebGLRenderingContext) {
      camera = new THREE.Camera();
      scene = new THREE.Scene();

      // Lighting
      scene.add(new THREE.AmbientLight(0xffffff, 0.65));
      const sun = new THREE.DirectionalLight(0xffffff, 0.7);
      sun.position.set(0, -70, 100).normalize();
      scene.add(sun);
      const fill = new THREE.DirectionalLight(0xffffff, 0.3);
      fill.position.set(0, 70, 100).normalize();
      scene.add(fill);

      const n = trees.length;
      const mat4 = new THREE.Matrix4();
      const pos = new THREE.Vector3();
      const quat = new THREE.Quaternion();
      const scl = new THREE.Vector3();

      // --- Trunks (cylinders) ---
      const trunkGeo = new THREE.CylinderGeometry(0.12, 0.18, 1, 6);
      trunkGeo.translate(0, 0.5, 0); // base at origin
      const trunkMat = new THREE.MeshLambertMaterial({ color: 0x5D4037 });
      const trunks = new THREE.InstancedMesh(trunkGeo, trunkMat, n);

      // --- Canopy (icosphere = organic/round look) ---
      const canopyGeo = new THREE.IcosahedronGeometry(1, 1); // subdivision 1
      canopyGeo.translate(0, 0.5, 0);
      const canopyMat = new THREE.MeshLambertMaterial({
        color: 0x388E3C,
        flatShading: true,
      });
      const canopies = new THREE.InstancedMesh(canopyGeo, canopyMat, n);

      // Green palette for variation
      const greens = [0x2E7D32, 0x388E3C, 0x43A047, 0x1B5E20, 0x33691E, 0x558B2F]
        .map(c => new THREE.Color(c));

      for (let i = 0; i < n; i++) {
        const t = trees[i];
        const h = t.height * TERRAIN_EXAG;

        const mc = maplibregl.MercatorCoordinate.fromLngLat([t.lng, t.lat], 0);
        const s = mc.meterInMercatorCoordinateUnits();

        // Trunk: 30% of height, thin
        const tH = h * 0.3;
        const tR = Math.max(0.15, h * 0.025);
        pos.set(mc.x, mc.y, mc.z!);
        scl.set(tR * s, tH * s, tR * s);
        mat4.compose(pos, quat, scl);
        trunks.setMatrixAt(i, mat4);

        // Canopy: 80% of height, wide sphere on top of trunk
        const cH = h * 0.8;
        const cR = Math.max(1.5, h * 0.22);
        pos.set(mc.x, mc.y, mc.z! + tH * s);
        scl.set(cR * s, cH * s, cR * s);
        mat4.compose(pos, quat, scl);
        canopies.setMatrixAt(i, mat4);

        canopies.setColorAt(i, greens[i % greens.length]);
      }

      trunks.instanceMatrix.needsUpdate = true;
      canopies.instanceMatrix.needsUpdate = true;
      if (canopies.instanceColor) canopies.instanceColor.needsUpdate = true;

      scene.add(trunks);
      scene.add(canopies);

      renderer = new THREE.WebGLRenderer({
        canvas: map.getCanvas(),
        context: gl as unknown as WebGL2RenderingContext,
      });
      renderer.autoClear = false;
    },

    render(_gl: WebGLRenderingContext, args: any) {
      const m = new THREE.Matrix4().fromArray(args.defaultProjectionData.mainMatrix);
      camera.projectionMatrix = m;
      renderer.resetState();
      renderer.render(scene, camera);
    },
  };
}
