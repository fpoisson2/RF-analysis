/**
 * Three.js custom MapLibre layer for rendering 3D trees.
 *
 * Uses InstancedMesh for performance — each tree is a cone (canopy)
 * + cylinder (trunk) placed at its LiDAR-detected position with
 * correct height.
 */
import * as THREE from 'three';
import maplibregl from 'maplibre-gl';

interface TreeData {
  lng: number;
  lat: number;
  height: number;
}

const TERRAIN_EXAGGERATION = 1.5;

export function createTreeLayer(trees: TreeData[]): maplibregl.CustomLayerInterface {
  let renderer: THREE.WebGLRenderer;
  let scene: THREE.Scene;
  let camera: THREE.Camera;
  let trunkMesh: THREE.InstancedMesh;
  let canopyMesh: THREE.InstancedMesh;
  let mapInstance: maplibregl.Map;

  return {
    id: 'trees-3d',
    type: 'custom' as const,
    renderingMode: '3d',

    onAdd(map: maplibregl.Map, gl: WebGLRenderingContext) {
      mapInstance = map;
      camera = new THREE.Camera();
      scene = new THREE.Scene();

      // Ambient + directional lighting
      scene.add(new THREE.AmbientLight(0xffffff, 0.6));
      const sun = new THREE.DirectionalLight(0xffffff, 0.8);
      sun.position.set(50, 100, 80).normalize();
      scene.add(sun);

      const count = trees.length;

      // Trunk geometry: cylinder (radius 0.15m, height 1m — scaled per instance)
      const trunkGeo = new THREE.CylinderGeometry(0.15, 0.2, 1, 5);
      trunkGeo.translate(0, 0.5, 0); // pivot at base
      const trunkMat = new THREE.MeshLambertMaterial({ color: 0x5D4037 });
      trunkMesh = new THREE.InstancedMesh(trunkGeo, trunkMat, count);

      // Canopy geometry: cone (radius 1m, height 1m — scaled per instance)
      const canopyGeo = new THREE.ConeGeometry(1, 1, 6);
      canopyGeo.translate(0, 0.5, 0); // pivot at base
      const canopyMat = new THREE.MeshLambertMaterial({ color: 0x2E7D32 });
      canopyMesh = new THREE.InstancedMesh(canopyGeo, canopyMat, count);

      // Assign random canopy color variation per instance
      const greens = [
        new THREE.Color(0x2E7D32), // dark green
        new THREE.Color(0x388E3C),
        new THREE.Color(0x43A047),
        new THREE.Color(0x4CAF50), // medium green
        new THREE.Color(0x1B5E20), // very dark green
        new THREE.Color(0x33691E), // olive green
      ];

      const dummy = new THREE.Object3D();

      for (let i = 0; i < count; i++) {
        const tree = trees[i];
        const h = tree.height * TERRAIN_EXAGGERATION;

        // Convert lng/lat to Mercator coordinates
        const mc = maplibregl.MercatorCoordinate.fromLngLat(
          [tree.lng, tree.lat], 0
        );
        const scale = mc.meterInMercatorCoordinateUnits();

        // Trunk: height = 30% of tree, thin
        const trunkH = h * 0.3;
        const trunkRadius = Math.max(0.1, h * 0.03);
        dummy.position.set(mc.x, mc.y, mc.z!);
        dummy.scale.set(trunkRadius * scale, trunkH * scale, trunkRadius * scale);
        dummy.updateMatrix();
        trunkMesh.setMatrixAt(i, dummy.matrix);

        // Canopy: height = 70% of tree, wider
        const canopyH = h * 0.7;
        const canopyR = Math.max(1.5, h * 0.3);
        dummy.position.set(mc.x, mc.y, mc.z! + trunkH * scale);
        dummy.scale.set(canopyR * scale, canopyH * scale, canopyR * scale);
        dummy.updateMatrix();
        canopyMesh.setMatrixAt(i, dummy.matrix);

        // Random green shade
        canopyMesh.setColorAt(i, greens[i % greens.length]);
      }

      trunkMesh.instanceMatrix.needsUpdate = true;
      canopyMesh.instanceMatrix.needsUpdate = true;
      if (canopyMesh.instanceColor) canopyMesh.instanceColor.needsUpdate = true;

      scene.add(trunkMesh);
      scene.add(canopyMesh);

      renderer = new THREE.WebGLRenderer({
        canvas: map.getCanvas(),
        context: gl as any,
        antialias: true,
      });
      renderer.autoClear = false;
    },

    render(gl: WebGLRenderingContext, args: any) {
      // Build projection matrix from MapLibre's projection data
      const m = new THREE.Matrix4().fromArray(args.defaultProjectionData.mainMatrix);
      camera.projectionMatrix = m;

      renderer.resetState();
      renderer.render(scene, camera);
    },

    onRemove() {
      if (trunkMesh) {
        trunkMesh.geometry.dispose();
        (trunkMesh.material as THREE.Material).dispose();
      }
      if (canopyMesh) {
        canopyMesh.geometry.dispose();
        (canopyMesh.material as THREE.Material).dispose();
      }
      if (renderer) {
        renderer.dispose();
      }
    },
  };
}
