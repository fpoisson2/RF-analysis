import React, { useEffect, useRef, useState } from 'react';
import maplibregl from 'maplibre-gl';
// deck.gl removed — MapLibre fill-extrusion with GPU hardware acceleration is fast enough
import { AreaResponse } from '../types';
import { Locale, t } from '../i18n';
import { Layers, Mountain, TreePine, Building2, X, Box } from 'lucide-react';

interface MapProps {
  onMapClick: (lat: number, lon: number) => void;
  txPosition: [number, number]; // [lon, lat]
  coverageResult: AreaResponse | null;
  darkMode: boolean;
  locale: Locale;
  outputUnits: string;
  terrainLayer: string | null;
  onTerrainLayerChange: (layer: string | null) => void;
  hasLidar: boolean;
  radius: number;
}

// Color legend stops - CloudRF-style rainbow (red=strong, blue=weak).
// MUST stay in sync with backend engine.py COLOR_SCHEMAS.
const COLOR_STOPS: Record<string, { label: string; stops: [number, string][] }> = {
  dBm: {
    label: 'dBm',
    stops: [
      [-30, '#ff1e1e'],   // Excellent - bright red
      [-40, '#ff3c00'],
      [-50, '#ff6e00'],   // Very good - red-orange
      [-55, '#ff9600'],
      [-60, '#ffbe00'],   // Good - amber
      [-65, '#ffe100'],
      [-70, '#dcf000'],   // Fair - yellow-green
      [-75, '#aaf000'],
      [-80, '#64e114'],   // Weak - green
      [-85, '#1ec83c'],
      [-90, '#00b478'],   // Very weak - teal-green
      [-95, '#00a0b4'],
      [-100, '#0082d2'],  // Marginal - cyan-blue
      [-105, '#0a5adc'],
      [-110, '#283cc8'],  // Poor - deep blue
      [-115, '#461eaa'],
      [-120, '#500a8c'],  // Very poor - violet
      [-125, '#46006e'],
      [-130, '#320050'],  // Near noise - dark purple
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

// Antenna SVG marker
function createTxMarkerElement(): HTMLDivElement {
  const el = document.createElement('div');
  el.style.cssText = 'cursor:grab;width:40px;height:50px;';
  el.innerHTML = `
    <svg viewBox="0 0 40 50" width="40" height="50" xmlns="http://www.w3.org/2000/svg">
      <ellipse cx="20" cy="48" rx="6" ry="2" fill="rgba(0,0,0,0.3)"/>
      <line x1="20" y1="15" x2="20" y2="45" stroke="#f97316" stroke-width="3" stroke-linecap="round"/>
      <line x1="20" y1="45" x2="12" y2="48" stroke="#f97316" stroke-width="2" stroke-linecap="round"/>
      <line x1="20" y1="45" x2="28" y2="48" stroke="#f97316" stroke-width="2" stroke-linecap="round"/>
      <line x1="15" y1="30" x2="20" y2="25" stroke="#f97316" stroke-width="1.5"/>
      <line x1="25" y1="30" x2="20" y2="25" stroke="#f97316" stroke-width="1.5"/>
      <path d="M 25 12 Q 30 8 25 4" stroke="#fbbf24" stroke-width="1.5" fill="none" opacity="0.8"/>
      <path d="M 28 15 Q 35 8 28 1" stroke="#fbbf24" stroke-width="1.5" fill="none" opacity="0.5"/>
      <path d="M 15 12 Q 10 8 15 4" stroke="#fbbf24" stroke-width="1.5" fill="none" opacity="0.8"/>
      <path d="M 12 15 Q 5 8 12 1" stroke="#fbbf24" stroke-width="1.5" fill="none" opacity="0.5"/>
      <circle cx="20" cy="14" r="3" fill="#f97316" stroke="white" stroke-width="1.5"/>
    </svg>`;
  return el;
}

export const MapView = React.memo(function MapView({
  onMapClick, txPosition, coverageResult, darkMode, locale, outputUnits,
  terrainLayer, onTerrainLayerChange, hasLidar, radius,
}: MapProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const coordsRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const markerRef = useRef<maplibregl.Marker | null>(null);
  const cleanupRef = useRef<(() => void) | null>(null);
  const onMapClickRef = useRef(onMapClick);
  const [layerMenuOpen, setLayerMenuOpen] = useState(false);
  const [loadingTerrain, setLoadingTerrain] = useState(false);
  const [view3D, setView3D] = useState(false);
  const [buildingsLoaded, setBuildingsLoaded] = useState(false);
  const [mapReady, setMapReady] = useState(0); // increment to signal map created

  onMapClickRef.current = onMapClick;

  // Initialize map
  useEffect(() => {
    if (!containerRef.current) return;
    let cancelled = false;

    const demTilesUrl = window.location.origin + '/api/terrain/dem/{z}/{x}/{y}.png';
    const cartoStyleUrl = darkMode
      ? 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json'
      : 'https://basemaps.cartocdn.com/gl/positron-gl-style/style.json';

    // Fetch CARTO style, inject DEM + terrain, then create map
    fetch(cartoStyleUrl).then(r => r.json()).catch(() => ({
      version: 8, sources: {}, layers: [],
    })).then((style: any) => {
      if (cancelled || !containerRef.current) return;

      // Inject DEM sources — AWS Terrarium tiles (fast CDN, global coverage)
      style.sources['terrain-dem'] = {
        type: 'raster-dem',
        tiles: ['https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png'],
        encoding: 'terrarium',
        tileSize: 256,
        maxzoom: 15,
      };
      style.sources['hillshade-dem'] = {
        type: 'raster-dem',
        tiles: ['https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png'],
        encoding: 'terrarium',
        tileSize: 256,
        maxzoom: 15,
      };

      // 3D terrain extrusion via style (not setTerrain API)
      style.terrain = { source: 'terrain-dem', exaggeration: 1.5 };
      style.sky = {};

      // Hillshade under all layers
      style.layers.unshift({
        id: 'hillshade-layer',
        type: 'hillshade',
        source: 'hillshade-dem',
        paint: {
          'hillshade-shadow-color': darkMode ? '#000000' : '#473B24',
          'hillshade-exaggeration': 0.5,
        },
      });

      const map = new maplibregl.Map({
        container: containerRef.current!,
        style,
        center: txPosition,
        zoom: 11,
        attributionControl: false,
        maxPitch: 85,
      });

      map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), 'top-right');
      map.addControl(new maplibregl.ScaleControl({ unit: 'metric' }), 'bottom-right');
      map.addControl(new maplibregl.AttributionControl({ compact: true }), 'bottom-right');
      map.addControl(new maplibregl.TerrainControl({ source: 'terrain-dem', exaggeration: 1.5 }));

      map.on('click', (e) => {
        const target = (e.originalEvent as MouseEvent)?.target as HTMLElement;
        if (target && !target.closest('.maplibregl-canvas')) return;
        onMapClickRef.current(e.lngLat.lat, e.lngLat.lng);
      });

      map.on('mousemove', (e) => {
        if (coordsRef.current) {
          coordsRef.current.textContent = `${e.lngLat.lat.toFixed(6)}, ${e.lngLat.lng.toFixed(6)}`;
        }
      });

      const el = createTxMarkerElement();
      const marker = new maplibregl.Marker({ element: el, draggable: true, anchor: 'bottom' })
        .setLngLat(txPosition)
        .addTo(map);

      marker.on('dragend', () => {
        const pos = marker.getLngLat();
        onMapClickRef.current(pos.lat, pos.lng);
      });

      markerRef.current = marker;
      mapRef.current = map;
      // Signal other effects once the map is fully loaded
      map.once('idle', () => setMapReady(n => n + 1));

      // Middle-mouse-button drag = rotate + pitch (3D navigation)
      const canvas = map.getCanvas();
      let midDrag = false;
      let lastX = 0;
      let lastY = 0;

      const onMidDown = (e: MouseEvent) => {
        if (e.button !== 1) return;
        e.preventDefault();
        midDrag = true;
        lastX = e.clientX;
        lastY = e.clientY;
        canvas.style.cursor = 'grabbing';
        map.dragPan.disable();
      };
      const onMidMove = (e: MouseEvent) => {
        if (!midDrag) return;
        e.preventDefault();
        const dx = e.clientX - lastX;
        const dy = e.clientY - lastY;
        lastX = e.clientX;
        lastY = e.clientY;
        const bearing = map.getBearing() + dx * 0.5;
        const pitch = Math.max(0, Math.min(85, map.getPitch() - dy * 0.5));
        map.jumpTo({ bearing, pitch });
      };
      const onMidUp = (e: MouseEvent) => {
        if (e.button !== 1 || !midDrag) return;
        midDrag = false;
        canvas.style.cursor = '';
        map.dragPan.enable();
      };
      const onMidDownPrevent = (e: MouseEvent) => {
        if (e.button === 1) e.preventDefault();
      };

      canvas.addEventListener('mousedown', onMidDown);
      canvas.addEventListener('auxclick', onMidDownPrevent);
      window.addEventListener('mousemove', onMidMove);
      window.addEventListener('mouseup', onMidUp);

      cleanupRef.current = () => {
        canvas.removeEventListener('mousedown', onMidDown);
        canvas.removeEventListener('auxclick', onMidDownPrevent);
        window.removeEventListener('mousemove', onMidMove);
        window.removeEventListener('mouseup', onMidUp);
        marker.remove();
        map.remove();
        markerRef.current = null;
        mapRef.current = null;
      };
    });

    return () => {
      cancelled = true;
      cleanupRef.current?.();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [darkMode]);

  // Update marker
  useEffect(() => {
    if (markerRef.current) {
      const current = markerRef.current.getLngLat();
      if (Math.abs(current.lng - txPosition[0]) > 0.000001 ||
          Math.abs(current.lat - txPosition[1]) > 0.000001) {
        markerRef.current.setLngLat(txPosition);
      }
    }
  }, [txPosition[0], txPosition[1], mapReady]);

  // Coverage overlay
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !coverageResult) return;

    const add = () => {
      if (map.getLayer('coverage-layer')) map.removeLayer('coverage-layer');
      if (map.getSource('coverage-source')) map.removeSource('coverage-source');

      const { north, south, east, west } = coverageResult.bounds;
      map.addSource('coverage-source', {
        type: 'image',
        url: coverageResult.image_url,
        coordinates: [[west, north], [east, north], [east, south], [west, south]],
      });
      map.addLayer({
        id: 'coverage-layer',
        type: 'raster',
        source: 'coverage-source',
        paint: { 'raster-opacity': 0.55 },
      });
    };

    add();
  }, [coverageResult, mapReady]);

  // Terrain/canopy layer overlay
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    const removeTerrain = () => {
      if (map.getLayer('terrain-layer')) map.removeLayer('terrain-layer');
      if (map.getSource('terrain-source')) map.removeSource('terrain-source');
    };

    if (!terrainLayer) {
      if (map.isStyleLoaded()) removeTerrain();
      return;
    }

    setLoadingTerrain(true);
    const lat = txPosition[1];
    const lon = txPosition[0];
    // Use finer resolution for smaller areas, cap at 500x500 grid max
    const res = Math.max(2, (2 * radius * 1000) / 500);

    fetch(`/api/terrain/render?lat=${lat}&lon=${lon}&radius_km=${radius}&resolution_m=${res}&mode=${terrainLayer}`)
      .then(r => r.json())
      .then(data => {
        if (!data.image_url || !map) return;

        const add = () => {
          removeTerrain();
          const { north, south, east, west } = data.bounds;
          map.addSource('terrain-source', {
            type: 'image',
            url: data.image_url,
            coordinates: [[west, north], [east, north], [east, south], [west, south]],
          });
          map.addLayer({
            id: 'terrain-layer',
            type: 'raster',
            source: 'terrain-source',
            paint: { 'raster-opacity': 0.6 },
          }, map.getLayer('coverage-layer') ? 'coverage-layer' : undefined);
        };

        add();
      })
      .catch(console.error)
      .finally(() => setLoadingTerrain(false));
  }, [terrainLayer, txPosition[0], txPosition[1], radius, mapReady]);

  // 3D toggle: camera tilt
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    if (view3D) {
      map.easeTo({ pitch: 60, bearing: -20, duration: 800 });
    } else {
      map.easeTo({ pitch: 0, bearing: 0, duration: 500 });
    }
  }, [view3D, mapReady]);

  // 3D buildings via MapLibre fill-extrusion (sits on terrain, GPU accelerated)
  const lastBuildingsLoad = useRef<{ lat: number; lon: number; radius: number } | null>(null);
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    const lat = txPosition[1];
    const lon = txPosition[0];
    const buildingsRadius = Math.min(Math.max(radius, 2), 100);

    // Skip if TX hasn't moved much
    const prev = lastBuildingsLoad.current;
    if (prev) {
      const dlat = (lat - prev.lat) * 111320;
      const dlon = (lon - prev.lon) * 111320 * Math.cos(lat * Math.PI / 180);
      if (Math.sqrt(dlat * dlat + dlon * dlon) < 500 && Math.abs(buildingsRadius - prev.radius) < 0.5) return;
    }

    let cancelled = false;

    const loadBuildings = async () => {
      try {
        const bResp = await fetch(`/api/data/buildings?lat=${lat}&lon=${lon}&radius_km=${buildingsRadius}`);
        if (!bResp.ok || cancelled) return;
        const data = await bResp.json();
        if (!data?.features || cancelled) return;

        const features = data.features
          .filter((f: any) => f.geometry && (f.geometry.type === 'Polygon' || f.geometry.type === 'MultiPolygon'))
          .map((f: any) => {
            const h = Number(f.properties?._height ?? f.properties?.HAUTEUR ?? f.properties?.HEIGHT ?? 8);
            return { ...f, properties: { ...f.properties, height: h } };
          });

        if (cancelled || features.length === 0) return;

        try {
          if (map.getLayer('buildings-3d')) map.removeLayer('buildings-3d');
          if (map.getSource('buildings-3d-source')) map.removeSource('buildings-3d-source');
        } catch (_) { /* ignore */ }

        map.addSource('buildings-3d-source', {
          type: 'geojson',
          data: { type: 'FeatureCollection', features },
        });
        map.addLayer({
          id: 'buildings-3d',
          type: 'fill-extrusion',
          source: 'buildings-3d-source',
          minzoom: 11,
          paint: {
            'fill-extrusion-color': '#b0b0b0',
            'fill-extrusion-height': ['get', 'height'],
            'fill-extrusion-base': 0,
            'fill-extrusion-opacity': 0.7,
          },
        });
        setBuildingsLoaded(true);
        lastBuildingsLoad.current = { lat, lon, radius: buildingsRadius };
        console.log(`3D buildings loaded: ${features.length} features`);
      } catch (e) {
        console.error('3D buildings failed:', e);
      }
    };

    loadBuildings();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [txPosition[0], txPosition[1], radius, mapReady]);


  const stops = COLOR_STOPS[outputUnits] || COLOR_STOPS['dBm'];
  const fr = locale === 'fr';

  return (
    <div className="flex-1 relative overflow-hidden">
      <div ref={containerRef} style={{ position: 'absolute', inset: 0 }} />

      {/* Layer control buttons — stopPropagation prevents clicks reaching the map */}
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
          title={fr ? 'Couches de données' : 'Data layers'}
        >
          <Layers className="w-4 h-4" />
        </button>
        <button
          onClick={() => setView3D(!view3D)}
          className={`p-2 rounded-lg shadow-lg border transition-colors ${
            view3D ? 'bg-brand-600 border-brand-500 text-white' : 'bg-surface-2/90 border-gray-700/50 text-gray-300 hover:bg-surface-3'
          }`}
          title={fr ? 'Vue 3D (bâtiments + signal)' : '3D view (buildings + signal)'}
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
              label={fr ? 'Élévation (MNT)' : 'Elevation (DTM)'}
              active={terrainLayer === 'elevation'}
              onClick={() => onTerrainLayerChange(terrainLayer === 'elevation' ? null : 'elevation')}
              loading={loadingTerrain && terrainLayer === 'elevation'}
            />
            {hasLidar && (
              <>
                <LayerButton
                  icon={<TreePine className="w-3.5 h-3.5" />}
                  label={fr ? 'Canopée / Bâtiments' : 'Canopy / Buildings'}
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

      {/* Stats overlay */}
      {coverageResult && (
        <div className="absolute bottom-8 right-2 bg-surface-2/90 backdrop-blur-sm px-3 py-2 rounded-lg text-[11px] font-mono text-gray-400 border border-gray-700/50 pointer-events-none z-10 space-y-0.5">
          <div>ERP: <span className="text-brand-400">{coverageResult.erp_w.toFixed(3)}W</span> / {coverageResult.erp_dbm.toFixed(1)}dBm</div>
          <div>EIRP: <span className="text-brand-400">{coverageResult.eirp_w.toFixed(3)}W</span> / {coverageResult.eirp_dbm.toFixed(1)}dBm</div>
          <div>{fr ? 'Temps' : 'Time'}: {coverageResult.computation_time_ms.toFixed(0)}ms</div>
          {coverageResult.stats.resolution_m && (
            <div>Res: {coverageResult.stats.resolution_m}m ({coverageResult.stats.megapixels} MP)</div>
          )}
        </div>
      )}
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
