import React, { useEffect, useRef, useState, useCallback, useMemo } from 'react';
import * as Cesium from 'cesium';
import { AreaResponse } from '../types';
import { Locale, t } from '../i18n';
import { Layers, Mountain, TreePine, Building2, X, Box, Route } from 'lucide-react';
import { createCesiumViewer, swapBaseImagery, destroyCesiumViewer } from './cesium/CesiumViewer';
import { HoverReadout, HoverSample } from './HoverReadout';
import { addCoverageLayer, removeCoverageLayer } from './cesium/CoverageLayer';
import { addTerrainOverlay, removeTerrainOverlay } from './cesium/TerrainOverlayLayer';
import { createTxMarker, updateTxMarkerPosition, TxMarkerHandle } from './cesium/TxMarker';
import { createRxMarker, RxMarkerHandle } from './cesium/RxMarker';
import { createPathLine, PathLineHandle } from './cesium/PathLine';
import { PathResponse } from '../types';
import { parseScene, shouldReloadScene, ParsedBuilding, ParsedScene } from './cesium/SceneLoader';
import { createBuildingPrimitives, recolorBuildings, BuildingPrimitives } from './cesium/BuildingsMesh';
import { createTreePrimitives, TreePrimitives } from './cesium/TreesMesh';
import { sampleBuildingSignals } from './cesium/CoverageColoring';

interface MapProps {
  onMapClick: (lat: number, lon: number) => void;
  onTxDragEnd: (lat: number, lon: number) => void;
  onRxDragEnd: (id: string, lat: number, lon: number) => void;
  onRxSelect: (id: string) => void;
  txPosition: [number, number]; // [lon, lat]
  rxPositions: Array<{ id: string; lat: number; lon: number }>;
  selectedRxId: string | null;
  placementMode: 'tx' | 'rx' | null;
  pathResult: PathResponse | null;
  pathHoverDistance: number | null;
  coverageResult: AreaResponse | null;
  noiseFloor: number;
  darkMode: boolean;
  locale: Locale;
  outputUnits: string;
  terrainLayer: string | null;
  onTerrainLayerChange: (layer: string | null) => void;
  hasLidar: boolean;
  radius: number;
}

// Color legend stops — must stay in sync with backend engine.py COLOR_SCHEMAS.
const COLOR_STOPS: Record<string, { label: string; stops: [number, string][] }> = {
  dBm: {
    label: 'dBm',
    stops: [
      [-30, '#ff1e1e'],
      [-40, '#ff3c00'],
      [-50, '#ff6e00'],
      [-55, '#ff9600'],
      [-60, '#ffbe00'],
      [-65, '#ffe100'],
      [-70, '#dcf000'],
      [-75, '#aaf000'],
      [-80, '#64e114'],
      [-85, '#1ec83c'],
      [-90, '#00b478'],
      [-95, '#00a0b4'],
      [-100, '#0082d2'],
      [-105, '#0a5adc'],
      [-110, '#283cc8'],
      [-115, '#461eaa'],
      [-120, '#500a8c'],
      [-125, '#46006e'],
      [-130, '#320050'],
    ],
  },
  dB: {
    label: 'SNR (dB)',
    stops: [
      [45, '#ff1e1e'],
      [40, '#ff5a00'],
      [35, '#ff9600'],
      [30, '#ffd200'],
      [25, '#c8eb00'],
      [20, '#78e114'],
      [15, '#1ec850'],
      [10, '#00aaaa'],
      [5, '#0082d2'],
      [0, '#283cc8'],
      [-5, '#4614a0'],
      [-10, '#320064'],
    ],
  },
  dBuV: {
    label: 'dBuV/m',
    stops: [
      [60, '#ff1e1e'],
      [55, '#ff5a00'],
      [50, '#ff9600'],
      [45, '#ffd200'],
      [40, '#c8eb00'],
      [35, '#78e114'],
      [30, '#1ec850'],
      [25, '#00aaaa'],
      [20, '#0082d2'],
      [15, '#283cc8'],
      [10, '#4614a0'],
      [5, '#500a82'],
      [0, '#46006e'],
      [-5, '#320050'],
      [-10, '#1e0032'],
    ],
  },
};

export const MapView = React.memo(function MapView({
  onMapClick, onTxDragEnd, onRxDragEnd, onRxSelect, txPosition, rxPositions, selectedRxId, placementMode, pathResult, pathHoverDistance,
  coverageResult, noiseFloor, darkMode, locale, outputUnits,
  terrainLayer, onTerrainLayerChange, hasLidar, radius,
}: MapProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const coordsRef = useRef<HTMLDivElement>(null);
  const viewerRef = useRef<Cesium.Viewer | null>(null);
  const markerRef = useRef<TxMarkerHandle | null>(null);
  const rxMarkersRef = useRef<Map<string, RxMarkerHandle>>(new globalThis.Map());
  const pathLineRef = useRef<PathLineHandle | null>(null);
  const onMapClickRef = useRef(onMapClick);
  const onTxDragEndRef = useRef(onTxDragEnd);
  const onRxDragEndRef = useRef(onRxDragEnd);
  const onRxSelectRef = useRef(onRxSelect);
  const placementModeRef = useRef(placementMode);
  onMapClickRef.current = onMapClick;
  onTxDragEndRef.current = onTxDragEnd;
  onRxDragEndRef.current = onRxDragEnd;
  onRxSelectRef.current = onRxSelect;
  placementModeRef.current = placementMode;

  const [hoverSample, setHoverSample] = useState<HoverSample | null>(null);
  const hoverPendingRef = useRef<{ lat: number; lon: number; x: number; y: number } | null>(null);
  const hoverTimerRef = useRef<number | null>(null);

  const [layerMenuOpen, setLayerMenuOpen] = useState(false);
  const [loadingTerrain, setLoadingTerrain] = useState(false);
  const [view3D, setView3D] = useState(false);
  const [showVegetation, setShowVegetation] = useState(true);
  const [showRoads, setShowRoads] = useState(true);
  const [viewerReady, setViewerReady] = useState(0);
  const [sceneReady, setSceneReady] = useState(false);
  const [loadMetrics, setLoadMetrics] = useState<Record<string, number>>({});
  const loadStartRef = useRef(performance.now());

  // Persistent refs for scene data
  const buildingPrimRef = useRef<BuildingPrimitives | null>(null);
  const treePrimRef = useRef<TreePrimitives | null>(null);
  const parsedBuildingsRef = useRef<ParsedBuilding[]>([]);
  const lastSceneLoad = useRef<{ lat: number; lon: number; radius: number } | null>(null);
  const darkModeRef = useRef(darkMode);

  onMapClickRef.current = onMapClick;
  darkModeRef.current = darkMode;

  // Initialize CesiumJS viewer
  useEffect(() => {
    if (!containerRef.current) return;

    loadStartRef.current = performance.now();
    const viewer = createCesiumViewer({
      container: containerRef.current,
      darkMode,
      txPosition,
    });
    viewerRef.current = viewer;

    // Coordinate tracking on mouse move
    const coordHandler = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas as HTMLCanvasElement);
    coordHandler.setInputAction((movement: Cesium.ScreenSpaceEventHandler.MotionEvent) => {
      const ray = viewer.camera.getPickRay(movement.endPosition);
      if (!ray) return;
      const cartesian = viewer.scene.globe.pick(ray, viewer.scene);
      if (!cartesian) return;
      const carto = Cesium.Cartographic.fromCartesian(cartesian);
      const lat = Cesium.Math.toDegrees(carto.latitude);
      const lon = Cesium.Math.toDegrees(carto.longitude);
      if (coordsRef.current) {
        coordsRef.current.textContent = `${lat.toFixed(6)}, ${lon.toFixed(6)}`;
      }
      hoverPendingRef.current = { lat, lon, x: movement.endPosition.x, y: movement.endPosition.y };
    }, Cesium.ScreenSpaceEventType.MOUSE_MOVE);

    // Center coordinates update on camera move
    const updateCenter = () => {
      const ray = viewer.camera.getPickRay(new Cesium.Cartesian2(
        viewer.canvas.clientWidth / 2,
        viewer.canvas.clientHeight / 2,
      ));
      if (!ray) return;
      const cartesian = viewer.scene.globe.pick(ray, viewer.scene);
      if (!cartesian) return;
      const carto = Cesium.Cartographic.fromCartesian(cartesian);
      const el = document.getElementById('center-coords');
      if (el) {
        el.textContent =
          `${Cesium.Math.toDegrees(carto.latitude).toFixed(6)}, ${Cesium.Math.toDegrees(carto.longitude).toFixed(6)}`;
      }
    };
    viewer.camera.moveEnd.addEventListener(updateCenter);

    // TX marker — drag moves TX directly; clicks on map go through placement-mode logic
    const marker = createTxMarker(
      viewer,
      txPosition,
      (lat, lon) => onTxDragEndRef.current(lat, lon),
      (lat, lon) => onMapClickRef.current(lat, lon),
    );
    markerRef.current = marker;

    // RX markers are managed in a separate effect (one per position).
    // Path line overlay
    pathLineRef.current = createPathLine(viewer);

    const tMap = performance.now() - loadStartRef.current;
    setLoadMetrics(m => ({ ...m, map: Math.round(tMap) }));
    console.log(`Cesium viewer ready: ${Math.round(tMap)}ms`);

    setViewerReady(n => n + 1);

    return () => {
      coordHandler.destroy();
      viewer.camera.moveEnd.removeEventListener(updateCenter);
      marker.destroy();
      markerRef.current = null;
      for (const m of rxMarkersRef.current.values()) m.destroy();
      rxMarkersRef.current.clear();
      pathLineRef.current?.destroy();
      pathLineRef.current = null;
      buildingPrimRef.current?.destroy(viewer);
      buildingPrimRef.current = null;
      treePrimRef.current?.destroy(viewer);
      treePrimRef.current = null;
      destroyCesiumViewer(viewer);
      viewerRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []); // Only init once — dark mode handled separately

  // Dark mode: swap base imagery
  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer || viewerReady === 0) return;
    swapBaseImagery(viewer, darkMode);
  }, [darkMode, viewerReady]);

  // Update marker position
  useEffect(() => {
    if (markerRef.current) {
      updateTxMarkerPosition(markerRef.current.entity, txPosition);
      viewerRef.current?.scene.requestRender();
    }
  }, [txPosition[0], txPosition[1], viewerReady]);

  // Coverage overlay
  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer || !coverageResult) return;

    addCoverageLayer(viewer, coverageResult);
    viewer.scene.requestRender();

    return () => {
      if (viewerRef.current) removeCoverageLayer(viewerRef.current);
    };
  }, [coverageResult, viewerReady]);

  // Terrain overlay layer
  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer) return;

    if (!terrainLayer) {
      removeTerrainOverlay(viewer);
      viewer.scene.requestRender();
      return;
    }

    setLoadingTerrain(true);
    addTerrainOverlay(viewer, terrainLayer, txPosition, radius)
      .then(() => viewer.scene.requestRender())
      .catch(console.error)
      .finally(() => setLoadingTerrain(false));
  }, [terrainLayer, txPosition[0], txPosition[1], radius, viewerReady]);

  // 3D toggle: camera pitch
  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer) return;

    if (view3D) {
      viewer.camera.flyTo({
        destination: viewer.camera.positionWC,
        orientation: {
          heading: Cesium.Math.toRadians(-20),
          pitch: Cesium.Math.toRadians(-30),
          roll: 0,
        },
        duration: 0.8,
      });
    } else {
      viewer.camera.flyTo({
        destination: viewer.camera.positionWC,
        orientation: {
          heading: 0,
          pitch: Cesium.Math.toRadians(-90),
          roll: 0,
        },
        duration: 0.5,
      });
    }
  }, [view3D, viewerReady]);

  // Load 3D scene (buildings + trees) from binary endpoint
  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer || viewerReady === 0) return;

    const lat = txPosition[1], lon = txPosition[0];
    const sceneRadius = Math.min(Math.max(radius, 2), 100);

    if (!shouldReloadScene(lastSceneLoad.current, lat, lon, sceneRadius)) return;

    let cancelled = false;

    const loadScene = async () => {
      try {
        const resp = await fetch(`/api/data/scene?lat=${lat}&lon=${lon}&radius_km=${sceneRadius}`);
        if (!resp.ok || cancelled) return;
        const buf = await resp.arrayBuffer();
        if (cancelled) return;

        const tFetch = performance.now() - loadStartRef.current;
        setLoadMetrics(m => ({ ...m, fetch: Math.round(tFetch) }));

        const scene: ParsedScene = parseScene(buf);
        console.log(`Scene fetched: ${scene.buildings.length} bldg + ${scene.trees.length} trees (${Math.round(tFetch)}ms, ${(scene.byteLength / 1e6).toFixed(1)}MB, server ${Math.round(scene.serverMs)}ms)`);

        if (cancelled) return;

        // --- Buildings ---
        if (scene.buildings.length > 0) {
          buildingPrimRef.current?.destroy(viewer);
          const tBldg = performance.now();
          buildingPrimRef.current = createBuildingPrimitives(scene.buildings, viewer);
          parsedBuildingsRef.current = scene.buildings;
          const dtBldg = performance.now() - tBldg;
          setLoadMetrics(m => ({ ...m, buildings: Math.round(performance.now() - loadStartRef.current) }));
          console.log(`Buildings rendered: ${scene.buildings.length} (${Math.round(dtBldg)}ms)`);
        }

        if (cancelled) return;

        // --- Trees ---
        if (scene.trees.length > 0) {
          treePrimRef.current?.destroy(viewer);
          const tTrees = performance.now();
          treePrimRef.current = createTreePrimitives(scene.trees, viewer);
          const dtTrees = performance.now() - tTrees;
          setLoadMetrics(m => ({ ...m, trees: Math.round(performance.now() - loadStartRef.current) }));
          console.log(`Trees rendered: ${scene.trees.length} (${Math.round(dtTrees)}ms)`);
        }

        lastSceneLoad.current = { lat, lon, radius: sceneRadius };
        viewer.scene.requestRender();
        setSceneReady(true);

        const totalT = performance.now() - loadStartRef.current;
        setLoadMetrics(m => ({ ...m, total: Math.round(totalT) }));
        console.log(`Scene complete: ${Math.round(totalT)}ms`);
      } catch (e) {
        console.error('Scene load failed:', e);
        setSceneReady(true);
      }
    };

    loadScene();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [txPosition[0], txPosition[1], radius, viewerReady]);

  // Recolor buildings after coverage calculation
  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer || !coverageResult || parsedBuildingsRef.current.length === 0) return;

    let cancelled = false;
    const doRecolor = async () => {
      const signalValues = await sampleBuildingSignals(parsedBuildingsRef.current);
      if (cancelled || signalValues.size === 0) return;

      buildingPrimRef.current = recolorBuildings(
        parsedBuildingsRef.current,
        viewer,
        signalValues,
        buildingPrimRef.current!,
      );
      viewer.scene.requestRender();
      console.log(`Buildings colored: ${signalValues.size} sampled`);
    };

    doRecolor();
    return () => { cancelled = true; };
  }, [coverageResult]);

  // Toggle tree visibility
  useEffect(() => {
    treePrimRef.current?.setVisible(showVegetation);
    viewerRef.current?.scene.requestRender();
  }, [showVegetation, viewerReady]);

  // Sync RX markers (add/remove/update) with rxPositions list.
  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer || viewerReady === 0) return;
    const map = rxMarkersRef.current;
    const seen = new Set<string>();

    for (const p of rxPositions) {
      seen.add(p.id);
      let m = map.get(p.id);
      if (!m) {
        m = createRxMarker(viewer, [p.lon, p.lat], (lat, lon) => {
          onRxDragEndRef.current(p.id, lat, lon);
        });
        // Click on marker selects this RX
        const handler = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas as HTMLCanvasElement);
        handler.setInputAction((click: Cesium.ScreenSpaceEventHandler.PositionedEvent) => {
          const picked = viewer.scene.pick(click.position);
          if (Cesium.defined(picked) && picked.id === m!.entity) {
            onRxSelectRef.current(p.id);
          }
        }, Cesium.ScreenSpaceEventType.LEFT_CLICK);
        // attach handler to marker for cleanup
        const origDestroy = m.destroy;
        m.destroy = () => { handler.destroy(); origDestroy(); };
        map.set(p.id, m);
      } else {
        m.setPosition(p.lat, p.lon);
      }
      // Visual highlight for selected
      const isSel = p.id === selectedRxId;
      if (m.entity.billboard) m.entity.billboard.scale = (isSel ? 0.6 : 0.45) as any;
    }

    // Remove markers no longer in the list
    for (const [id, m] of map.entries()) {
      if (!seen.has(id)) { m.destroy(); map.delete(id); }
    }
    viewer.scene.requestRender();
  }, [rxPositions, selectedRxId, viewerReady]);

  // Update path line when path or endpoints change
  const selectedRxPos = useMemo(() => {
    const p = rxPositions.find(p => p.id === selectedRxId);
    return p ? [p.lon, p.lat] as [number, number] : null;
  }, [rxPositions, selectedRxId]);

  useEffect(() => {
    const line = pathLineRef.current;
    if (!line) return;
    if (selectedRxPos && pathResult) {
      line.update(txPosition, selectedRxPos, pathResult);
    } else {
      line.update(txPosition, selectedRxPos || txPosition, null);
    }
  }, [pathResult, txPosition[0], txPosition[1], selectedRxPos?.[0], selectedRxPos?.[1], viewerReady]);

  // Hover marker on path line
  useEffect(() => {
    pathLineRef.current?.setHover(pathHoverDistance);
  }, [pathHoverDistance]);

  // Throttled hover sampling (every 120ms) — only when coverage exists
  useEffect(() => {
    if (!coverageResult) {
      setHoverSample(null);
      if (hoverTimerRef.current) {
        window.clearInterval(hoverTimerRef.current);
        hoverTimerRef.current = null;
      }
      return;
    }
    let inFlight = false;
    const tick = async () => {
      const pending = hoverPendingRef.current;
      if (!pending || inFlight) return;
      inFlight = true;
      try {
        const res = await fetch('/api/coverage/sample', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ points: [[pending.lat, pending.lon]] }),
        });
        if (!res.ok) return;
        const data = await res.json();
        const val = data.values?.[0];
        setHoverSample({
          lat: pending.lat,
          lon: pending.lon,
          signal_dbm: typeof val === 'number' ? val : null,
          screenX: pending.x,
          screenY: pending.y,
        });
      } catch {}
      finally { inFlight = false; }
    };
    hoverTimerRef.current = window.setInterval(tick, 120);
    return () => {
      if (hoverTimerRef.current) {
        window.clearInterval(hoverTimerRef.current);
        hoverTimerRef.current = null;
      }
    };
  }, [coverageResult]);

  // Cursor feedback for placement mode
  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer) return;
    const canvas = viewer.scene.canvas as HTMLCanvasElement;
    canvas.style.cursor = placementMode ? 'crosshair' : '';
    return () => { canvas.style.cursor = ''; };
  }, [placementMode, viewerReady]);

  const stops = COLOR_STOPS[outputUnits] || COLOR_STOPS['dBm'];
  const fr = locale === 'fr';

  return (
    <div className="flex-1 relative overflow-hidden">
      <div ref={containerRef} style={{ position: 'absolute', inset: 0, backgroundColor: '#87CEEB' }} />

      {/* Center crosshair + GPS coordinates */}
      <div className="absolute inset-0 pointer-events-none z-20 flex items-center justify-center">
        <div className="relative">
          <div className="absolute w-8 h-[2px] bg-white/80 -left-4 top-1/2 -translate-y-1/2 shadow-sm" style={{ boxShadow: '0 0 3px rgba(0,0,0,0.8)' }} />
          <div className="absolute h-8 w-[2px] bg-white/80 left-1/2 -top-4 -translate-x-1/2 shadow-sm" style={{ boxShadow: '0 0 3px rgba(0,0,0,0.8)' }} />
          <div className="absolute w-1.5 h-1.5 rounded-full bg-red-500 left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2" />
        </div>
      </div>
      <div className="absolute left-1/2 -translate-x-1/2 bottom-16 z-20">
        <div
          className="bg-black/70 backdrop-blur-sm px-3 py-1 rounded text-xs font-mono text-white cursor-pointer hover:bg-black/90 active:bg-brand-600 transition-colors select-all"
          title={fr ? 'Cliquer pour copier' : 'Click to copy'}
          onClick={() => {
            const el = document.getElementById('center-coords');
            if (el) { navigator.clipboard.writeText(el.textContent || ''); }
          }}
        >
          <span id="center-coords">...</span>
        </div>
      </div>

      {/* Loading overlay */}
      {!sceneReady && (
        <div className="absolute inset-0 z-50 bg-surface-1 flex flex-col items-center justify-center gap-4">
          <div className="w-10 h-10 border-4 border-brand-500 border-t-transparent rounded-full animate-spin" />
          <div className="text-sm text-gray-400 space-y-1 text-center">
            <div>{fr ? 'Chargement du modele 3D...' : 'Loading 3D model...'}</div>
            <div className="text-xs text-gray-500 font-mono space-y-0.5">
              {loadMetrics.map ? <div>Carte: {loadMetrics.map}ms</div> : <div>Carte...</div>}
              {loadMetrics.buildings ? <div>Batiments: {loadMetrics.buildings}ms</div> : viewerReady > 0 ? <div>Batiments...</div> : null}
              {loadMetrics.trees ? <div>Arbres: {loadMetrics.trees}ms</div> : loadMetrics.buildings ? <div>Arbres...</div> : null}
            </div>
          </div>
        </div>
      )}

      {/* Layer control buttons */}
      <div
        className="absolute top-4 left-2 z-10 flex flex-col gap-1"
        onMouseDown={(e) => e.stopPropagation()}
        onClick={(e) => e.stopPropagation()}
      >
        <button
          onClick={() => setLayerMenuOpen(!layerMenuOpen)}
          className={`p-2 rounded-lg shadow-lg border transition-colors ${
            layerMenuOpen ? 'bg-brand-600 border-brand-500 text-white' : 'bg-surface-2/90 border-gray-700/50 text-gray-300 hover:bg-surface-3'
          }`}
          title={fr ? 'Couches de donnees' : 'Data layers'}
        >
          <Layers className="w-4 h-4" />
        </button>
        <button
          onClick={() => setView3D(!view3D)}
          className={`p-2 rounded-lg shadow-lg border transition-colors ${
            view3D ? 'bg-brand-600 border-brand-500 text-white' : 'bg-surface-2/90 border-gray-700/50 text-gray-300 hover:bg-surface-3'
          }`}
          title={fr ? 'Vue 3D (batiments + signal)' : '3D view (buildings + signal)'}
        >
          <Box className="w-4 h-4" />
        </button>

        {layerMenuOpen && (
          <div className="bg-surface-2/95 backdrop-blur-sm rounded-lg border border-gray-700/50 shadow-xl p-2 space-y-1 min-w-[180px]">
            <div className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider px-2 py-1">
              {fr ? 'Couches terrain' : 'Terrain layers'}
            </div>

            <LayerButton
              icon={<Mountain className="w-3.5 h-3.5" />}
              label={fr ? 'Elevation (MNT)' : 'Elevation (DTM)'}
              active={terrainLayer === 'elevation'}
              onClick={() => onTerrainLayerChange(terrainLayer === 'elevation' ? null : 'elevation')}
              loading={loadingTerrain && terrainLayer === 'elevation'}
            />
            {hasLidar && (
              <>
                <LayerButton
                  icon={<TreePine className="w-3.5 h-3.5" />}
                  label={fr ? 'Canopee / Batiments' : 'Canopy / Buildings'}
                  active={terrainLayer === 'canopy'}
                  onClick={() => onTerrainLayerChange(terrainLayer === 'canopy' ? null : 'canopy')}
                  loading={loadingTerrain && terrainLayer === 'canopy'}
                  badge="LiDAR"
                />
                <LayerButton
                  icon={<Building2 className="w-3.5 h-3.5" />}
                  label={fr ? 'Surface (MNS)' : 'Surface (DSM)'}
                  active={terrainLayer === 'surface'}
                  onClick={() => onTerrainLayerChange(terrainLayer === 'surface' ? null : 'surface')}
                  loading={loadingTerrain && terrainLayer === 'surface'}
                  badge="LiDAR"
                />
              </>
            )}
            {terrainLayer && (
              <button
                onClick={() => onTerrainLayerChange(null)}
                className="w-full flex items-center gap-2 px-2 py-1.5 rounded text-xs text-red-400 hover:bg-red-900/20 transition-colors"
              >
                <X className="w-3.5 h-3.5" />
                {fr ? 'Effacer couche' : 'Clear layer'}
              </button>
            )}

            <div className="border-t border-gray-700/50 mt-1 pt-1">
              <div className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider px-2 py-1">
                {fr ? 'Couches 3D' : '3D layers'}
              </div>
              <LayerButton
                icon={<TreePine className="w-3.5 h-3.5" />}
                label={fr ? 'Arbres 3D' : '3D Trees'}
                active={showVegetation}
                onClick={() => setShowVegetation(!showVegetation)}
                badge="LiDAR"
              />
              <LayerButton
                icon={<Route className="w-3.5 h-3.5" />}
                label={fr ? 'Routes' : 'Roads'}
                active={showRoads}
                onClick={() => setShowRoads(!showRoads)}
              />
            </div>
          </div>
        )}
      </div>

      {/* Color Legend */}
      {coverageResult && (
        <div className="absolute top-4 right-14 bg-surface-2/90 backdrop-blur-sm rounded-lg border border-gray-700/50 p-3 z-10 pointer-events-none">
          <div className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider mb-2">
            {stops.label}
          </div>
          <div className="space-y-0.5">
            {stops.stops.map(([value, color], idx) => (
              <div key={idx} className="flex items-center gap-2">
                <div className="w-5 h-3 rounded-sm" style={{ backgroundColor: color }} />
                <span className="text-[11px] font-mono text-gray-300">{value}</span>
              </div>
            ))}
          </div>
          {coverageResult.stats.coverage_pct !== undefined && (
            <div className="mt-2 pt-2 border-t border-gray-700/50 text-[10px] text-gray-400">
              {fr ? 'Couverture' : 'Coverage'}: {coverageResult.stats.coverage_pct}%
            </div>
          )}
        </div>
      )}

      {/* Coordinates */}
      <div className="absolute bottom-8 left-2 bg-surface-2/90 backdrop-blur-sm px-3 py-1.5 rounded-lg text-xs font-mono text-gray-300 border border-gray-700/50 pointer-events-none z-10">
        <span ref={coordsRef}>{t('map.click_to_place', locale)}</span>
      </div>

      {/* Placement-mode banner */}
      {placementMode && (
        <div className="absolute top-4 left-1/2 -translate-x-1/2 z-30 px-3 py-1.5 rounded-lg shadow-lg border text-xs font-semibold pointer-events-none flex items-center gap-2"
             style={{
               backgroundColor: placementMode === 'rx' ? 'rgba(59,130,246,0.95)' : 'rgba(249,115,22,0.95)',
               borderColor: 'white',
               color: 'white',
             }}>
          <span className="w-2 h-2 rounded-full bg-white animate-pulse" />
          {placementMode === 'rx'
            ? (fr ? 'Cliquer pour placer le récepteur (Échap pour annuler)' : 'Click to place receiver (Esc to cancel)')
            : (fr ? 'Cliquer pour placer l\'émetteur (Échap pour annuler)' : 'Click to place transmitter (Esc to cancel)')}
        </div>
      )}

      {/* Hover readout */}
      {coverageResult && (
        <HoverReadout sample={hoverSample} coverageResult={coverageResult} noiseFloor={noiseFloor} locale={locale} />
      )}

      {/* Stats overlay */}
      <div className="absolute bottom-8 right-2 bg-surface-2/90 backdrop-blur-sm px-3 py-2 rounded-lg text-[11px] font-mono text-gray-400 border border-gray-700/50 pointer-events-none z-10 space-y-0.5">
        {coverageResult && (
          <>
            <div>ERP: <span className="text-brand-400">{coverageResult.erp_w.toFixed(3)}W</span> / {coverageResult.erp_dbm.toFixed(1)}dBm</div>
            <div>EIRP: <span className="text-brand-400">{coverageResult.eirp_w.toFixed(3)}W</span> / {coverageResult.eirp_dbm.toFixed(1)}dBm</div>
            <div>{fr ? 'Temps' : 'Time'}: {coverageResult.computation_time_ms.toFixed(0)}ms</div>
            {coverageResult.stats.resolution_m && (
              <div>Res: {coverageResult.stats.resolution_m}m ({coverageResult.stats.megapixels} MP)</div>
            )}
          </>
        )}
        {loadMetrics.total && (
          <div className="border-t border-gray-700/30 pt-0.5 mt-0.5">
            3D: {(loadMetrics.total / 1000).toFixed(1)}s
            <span className="text-gray-500"> (map {((loadMetrics.map || 0) / 1000).toFixed(1)}s + bldg {(((loadMetrics.buildings || 0) - (loadMetrics.map || 0)) / 1000).toFixed(1)}s + trees {(((loadMetrics.trees || 0) - (loadMetrics.buildings || 0)) / 1000).toFixed(1)}s)</span>
          </div>
        )}
      </div>
    </div>
  );
});


function LayerButton({ icon, label, active, onClick, loading, badge }: {
  icon: React.ReactNode;
  label: string;
  active: boolean;
  onClick: () => void;
  loading?: boolean;
  badge?: string;
}) {
  return (
    <button
      onClick={onClick}
      className={`w-full flex items-center gap-2 px-2 py-1.5 rounded text-xs transition-colors ${
        active
          ? 'bg-brand-600/20 text-brand-400'
          : 'text-gray-300 hover:bg-surface-3'
      }`}
    >
      {loading ? (
        <div className="w-3.5 h-3.5 border-2 border-brand-400 border-t-transparent rounded-full animate-spin" />
      ) : icon}
      <span className="flex-1 text-left">{label}</span>
      {badge && (
        <span className="text-[9px] px-1 py-0.5 rounded bg-brand-900/50 text-brand-400 font-semibold">{badge}</span>
      )}
    </button>
  );
}
