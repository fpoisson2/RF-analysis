import React, { useEffect, useRef, useState } from 'react';
import maplibregl from 'maplibre-gl';
import { AreaResponse } from '../types';
import { Locale, t } from '../i18n';
import { Layers, Mountain, TreePine, Building2, X, Box, Route } from 'lucide-react';

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
  const [showVegetation, setShowVegetation] = useState(true);
  const [showRoads, setShowRoads] = useState(true);
  const [mapReady, setMapReady] = useState(0); // increment to signal map created
  const [sceneReady, setSceneReady] = useState(false); // all layers loaded
  const [loadMetrics, setLoadMetrics] = useState<Record<string, number>>({});
  const loadStartRef = useRef(performance.now());

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
      // No sky/fog — clean 3D view
      delete style.sky;
      delete style.fog;

      // --- Build complete 3D city model from CARTO vector tiles ---
      const cartoSource = Object.keys(style.sources).find(
        (k: string) => style.sources[k].type === 'vector'
      );
      console.log('CARTO source:', cartoSource);

      if (cartoSource) {
        // Hide original CARTO fill/line layers — keep symbol layers (street names, place names)
        for (const layer of style.layers) {
          const sl = layer['source-layer'];
          if (!sl) continue;
          // Never hide symbol layers (labels) or transportation_name
          if (layer.type === 'symbol') continue;
          if (['water', 'waterway', 'landuse', 'landcover', 'transportation', 'building'].includes(sl)) {
            layer.paint = { ...layer.paint, [`${layer.type}-opacity`]: 0 };
          }
        }

        // Default ground color (grass everywhere — no empty zones)
        style.layers.push({
          id: 'ground-base',
          type: 'background',
          paint: {
            'background-color': darkMode ? '#1e3a1e' : '#7caa5a',
          },
        });

        // --- LANDCOVER: natural surfaces ---
        style.layers.push({
          id: 'landcover-3d',
          type: 'fill',
          source: cartoSource,
          'source-layer': 'landcover',
          paint: {
            'fill-color': [
              'match', ['get', 'class'],
              'wood', darkMode ? '#1b3d1b' : '#5a9e4a',
              'farmland', darkMode ? '#2a3d1a' : '#b8cc6a',
              'ice', '#e8f0f8',
              darkMode ? '#1e3a1e' : '#7caa5a', // grass default
            ],
            'fill-opacity': 0.8,
          },
        });

        // --- LANDUSE: parks, residential, industrial, commercial ---
        style.layers.push({
          id: 'landuse-3d',
          type: 'fill',
          source: cartoSource,
          'source-layer': 'landuse',
          paint: {
            'fill-color': [
              'match', ['get', 'class'],
              'grass', darkMode ? '#1e4a1e' : '#8bc34a',
              'park', darkMode ? '#1e4a1e' : '#81c784',
              'garden', darkMode ? '#1e4a1e' : '#8bc34a',
              'cemetery', darkMode ? '#2a3d2a' : '#a5c88a',
              'residential', darkMode ? '#252525' : '#d5dbb3',
              'industrial', darkMode ? '#2a2520' : '#c8bfb0',
              'commercial', darkMode ? '#2a2525' : '#d4c8b8',
              darkMode ? '#1e3a1e' : '#7caa5a',
            ],
            'fill-opacity': 0.7,
          },
        });

        // --- WATER: rivers, lakes (flat fill, draped on terrain) ---
        style.layers.push({
          id: 'water-3d',
          type: 'fill',
          source: cartoSource,
          'source-layer': 'water',
          paint: {
            'fill-color': darkMode ? '#0d2847' : '#4da8da',
            'fill-opacity': 0.85,
          },
        });

        // Waterways (streams, canals)
        style.layers.push({
          id: 'waterway-3d',
          type: 'line',
          source: cartoSource,
          'source-layer': 'waterway',
          layout: { 'line-cap': 'round' },
          paint: {
            'line-color': darkMode ? '#0d2847' : '#4da8da',
            'line-width': [
              'interpolate', ['linear'], ['zoom'],
              10, ['match', ['get', 'class'], 'river', 2, 1],
              16, ['match', ['get', 'class'], 'river', 8, 'canal', 5, 3],
            ],
            'line-opacity': 0.8,
          },
        });

        // --- ROADS: realistic widths ---
        // Widths in pixels that scale with zoom to approximate real meters.
        // At zoom 16: 1px ≈ 2.4m. Road widths (total with sidewalks):
        // motorway ~24m, trunk ~18m, primary ~14m, secondary ~10m, tertiary ~9m, minor ~8m, service ~6m
        // Match roads that are NOT tunnels: either no brunnel property, or brunnel != tunnel
        const roadFilter = ['all',
          ['any', ['!has', 'brunnel'], ['!=', 'brunnel', 'tunnel']],
          ['!=', 'class', 'rail'], ['!=', 'class', 'path']];

        // Layer 1: Sidewalk + curb (outermost, light gray)
        style.layers.push({
          id: 'road-sidewalk',
          type: 'line',
          source: cartoSource,
          'source-layer': 'transportation',
          filter: roadFilter,
          layout: { 'line-cap': 'round', 'line-join': 'round' },
          minzoom: 11,
          paint: {
            'line-color': darkMode ? '#3a3a3a' : '#b0b0a8',
            'line-width': [
              'interpolate', ['exponential', 2], ['zoom'],
              11, 1,
              13, ['match', ['get', 'class'], 'motorway', 6, 'trunk', 5, 'primary', 4, 'secondary', 3.5, 'tertiary', 3, 'minor', 3, 'service', 2.5, 2.5],
              16, ['match', ['get', 'class'], 'motorway', 22, 'trunk', 18, 'primary', 14, 'secondary', 11, 'tertiary', 10, 'minor', 9, 'service', 7, 7],
              20, ['match', ['get', 'class'], 'motorway', 180, 'trunk', 140, 'primary', 110, 'secondary', 85, 'tertiary', 76, 'minor', 72, 'service', 56, 56],
            ],
            'line-opacity': 0.9,
          },
        });

        // Layer 2: Asphalt surface (dark, narrower than sidewalk)
        style.layers.push({
          id: 'road-asphalt',
          type: 'line',
          source: cartoSource,
          'source-layer': 'transportation',
          filter: roadFilter,
          layout: { 'line-cap': 'round', 'line-join': 'round' },
          minzoom: 11,
          paint: {
            'line-color': darkMode ? '#252525' : '#505050',
            'line-width': [
              'interpolate', ['exponential', 2], ['zoom'],
              11, 0.5,
              13, ['match', ['get', 'class'], 'motorway', 5, 'trunk', 4, 'primary', 3, 'secondary', 2.5, 'tertiary', 2, 'minor', 2, 'service', 1.5, 1.5],
              16, ['match', ['get', 'class'], 'motorway', 18, 'trunk', 14, 'primary', 11, 'secondary', 8, 'tertiary', 7, 'minor', 7, 'service', 5, 5],
              20, ['match', ['get', 'class'], 'motorway', 150, 'trunk', 114, 'primary', 90, 'secondary', 66, 'tertiary', 58, 'minor', 54, 'service', 42, 42],
            ],
            'line-opacity': 0.95,
          },
        });

        // Layer 3: Center line (yellow for arterials, white for local)
        style.layers.push({
          id: 'road-center-line',
          type: 'line',
          source: cartoSource,
          'source-layer': 'transportation',
          filter: ['all', ['!=', 'brunnel', 'tunnel'], ['!=', 'class', 'rail'], ['!=', 'class', 'path'],
                   ['in', 'class', 'motorway', 'trunk', 'primary', 'secondary', 'tertiary']],
          layout: { 'line-cap': 'butt' },
          minzoom: 15,
          paint: {
            'line-color': ['match', ['get', 'class'], 'motorway', '#ffcc00', 'trunk', '#ffcc00', 'primary', '#ffcc00', '#ffffff'],
            'line-width': ['interpolate', ['exponential', 2], ['zoom'], 15, 0.3, 18, 1.2, 20, 5],
            'line-dasharray': [6, 4],
            'line-opacity': 0.8,
          },
        });

        // Layer 4: Edge lines (white on both sides of major roads)
        style.layers.push({
          id: 'road-edge-lines',
          type: 'line',
          source: cartoSource,
          'source-layer': 'transportation',
          filter: ['all', ['!=', 'brunnel', 'tunnel'],
                   ['in', 'class', 'motorway', 'trunk', 'primary', 'secondary']],
          layout: { 'line-cap': 'butt' },
          minzoom: 15,
          paint: {
            'line-color': '#ffffff',
            'line-width': ['interpolate', ['exponential', 2], ['zoom'], 15, 0.2, 18, 0.8, 20, 3],
            'line-gap-width': [
              'interpolate', ['exponential', 2], ['zoom'],
              15, ['match', ['get', 'class'], 'motorway', 4, 'trunk', 3, 'primary', 2.5, 2],
              18, ['match', ['get', 'class'], 'motorway', 22, 'trunk', 16, 'primary', 13, 9],
              20, ['match', ['get', 'class'], 'motorway', 120, 'trunk', 88, 'primary', 72, 50],
            ],
            'line-opacity': 0.5,
          },
        });

        // Paths / sidewalks standalone
        style.layers.push({
          id: 'road-paths',
          type: 'line',
          source: cartoSource,
          'source-layer': 'transportation',
          filter: ['==', 'class', 'path'],
          layout: { 'line-cap': 'round' },
          minzoom: 14,
          paint: {
            'line-color': darkMode ? '#4a4a3a' : '#c8b898',
            'line-width': ['interpolate', ['exponential', 2], ['zoom'], 14, 0.5, 18, 4],
            'line-opacity': 0.7,
          },
        });

        // Rail
        style.layers.push({
          id: 'rail-3d',
          type: 'line',
          source: cartoSource,
          'source-layer': 'transportation',
          filter: ['==', 'class', 'rail'],
          layout: { 'line-cap': 'butt' },
          paint: {
            'line-color': darkMode ? '#666666' : '#777777',
            'line-width': ['interpolate', ['exponential', 2], ['zoom'], 10, 0.5, 18, 5],
            'line-dasharray': [4, 2],
            'line-opacity': 0.8,
          },
        });

        // --- BRIDGES: wider with guardrails ---
        style.layers.push({
          id: 'bridge-edge',
          type: 'line',
          source: cartoSource,
          'source-layer': 'transportation',
          filter: ['==', 'brunnel', 'bridge'],
          layout: { 'line-cap': 'butt', 'line-join': 'miter' },
          paint: {
            'line-color': darkMode ? '#555555' : '#888888',
            'line-width': [
              'interpolate', ['exponential', 2], ['zoom'],
              11, ['match', ['get', 'class'], 'motorway', 3, 'trunk', 2.5, 'primary', 2, 1.5],
              18, ['match', ['get', 'class'], 'motorway', 38, 'trunk', 30, 'primary', 24, 16],
            ],
            'line-opacity': 0.95,
          },
        });
        style.layers.push({
          id: 'bridge-surface',
          type: 'line',
          source: cartoSource,
          'source-layer': 'transportation',
          filter: ['==', 'brunnel', 'bridge'],
          layout: { 'line-cap': 'butt', 'line-join': 'miter' },
          paint: {
            'line-color': darkMode ? '#333333' : '#a0a0a0',
            'line-width': [
              'interpolate', ['exponential', 2], ['zoom'],
              11, ['match', ['get', 'class'], 'motorway', 2.5, 'trunk', 2, 'primary', 1.5, 1],
              18, ['match', ['get', 'class'], 'motorway', 32, 'trunk', 24, 'primary', 20, 12],
            ],
            'line-opacity': 0.95,
          },
        });
      }

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
      map.once('idle', () => {
        const t = performance.now() - loadStartRef.current;
        setLoadMetrics(m => ({ ...m, map: Math.round(t) }));
        console.log(`⏱ Map base loaded: ${Math.round(t)}ms`);
        setMapReady(n => n + 1);
      });

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
      // Use raster tiles instead of image source to avoid 3D terrain clipping
      // Calculate optimal maxzoom from coverage resolution
      // At maxzoom, MapLibre will oversample for higher zooms (consistent quality)
      const covWidthDeg = east - west;
      const covPixels = coverageResult.stats?.grid_size || 666;
      const pixelDeg = covWidthDeg / covPixels;
      // Each zoom level tile covers 360/2^z degrees. We want ~1 source pixel per tile pixel.
      // tile_deg = 360 / 2^z, pixels_per_tile = tile_deg / pixelDeg
      // We want pixels_per_tile >= 512, so z <= log2(360 / (pixelDeg * 512))
      const optimalMaxZoom = Math.min(15, Math.max(10, Math.floor(Math.log2(360 / (pixelDeg * 512)))));

      // Cache-buster: unique timestamp per coverage result forces tile reload
      const cacheBuster = Date.now();
      map.addSource('coverage-source', {
        type: 'raster',
        tiles: [window.location.origin + `/api/coverage/tiles/{z}/{x}/{y}.png?t=${cacheBuster}`],
        tileSize: 512,
        bounds: [west, south, east, north],
        minzoom: 8,
        maxzoom: optimalMaxZoom,
      });
      map.addLayer({
        id: 'coverage-layer',
        type: 'raster',
        source: 'coverage-source',
        paint: { 'raster-opacity': 0.55, 'raster-fade-duration': 0 },
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
            const ring = f.geometry.type === 'Polygon'
              ? f.geometry.coordinates[0]
              : f.geometry.coordinates[0][0];
            const cLat = ring.reduce((s: number, p: number[]) => s + p[1], 0) / ring.length;
            const cLon = ring.reduce((s: number, p: number[]) => s + p[0], 0) / ring.length;
            return { ...f, properties: { ...f.properties, height: h, centroid_lat: cLat, centroid_lon: cLon } };
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
            'fill-extrusion-color': [
              'case',
              ['==', ['typeof', ['get', 'signal']] as any, 'number'],
              [
                'interpolate', ['linear'], ['get', 'signal'],
                -120, '#461eaa',
                -100, '#0082d2',
                -90,  '#00b478',
                -80,  '#64e114',
                -70,  '#dcf000',
                -60,  '#ffbe00',
                -50,  '#ff6e00',
                -30,  '#ff1e1e',
              ],
              '#b0b0b0',
            ],
            'fill-extrusion-height': ['*', ['get', 'height'], 1.5],  // scale to match terrain exaggeration
            'fill-extrusion-base': 0,
            'fill-extrusion-opacity': 0.8,
          },
        });
        setBuildingsLoaded(true);
        lastBuildingsLoad.current = { lat, lon, radius: buildingsRadius };
        const t = performance.now() - loadStartRef.current;
        setLoadMetrics(m => ({ ...m, buildings: Math.round(t) }));
        console.log(`⏱ 3D buildings loaded: ${features.length} features (${Math.round(t)}ms)`);
      } catch (e) {
        console.error('3D buildings failed:', e);
      }
    };

    loadBuildings();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [txPosition[0], txPosition[1], radius, mapReady]);

  // Color buildings based on actual coverage signal values (dBm)
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !coverageResult) return;
    const src = map.getSource('buildings-3d-source') as any;
    if (!src?._data?.features) return;

    let cancelled = false;
    const features = src._data.features;

    const updateColors = async () => {
      // Collect centroids
      const points: number[][] = [];
      const indices: number[] = [];
      for (let i = 0; i < features.length; i++) {
        const f = features[i];
        const clat = f.properties?.centroid_lat;
        const clon = f.properties?.centroid_lon;
        if (clat && clon) {
          points.push([clat, clon]);
          indices.push(i);
        }
      }

      if (points.length === 0 || cancelled) return;

      // Batch query — send in chunks of 50k to avoid huge payloads
      const chunkSize = 50000;
      for (let start = 0; start < points.length; start += chunkSize) {
        if (cancelled) return;
        const chunk = points.slice(start, start + chunkSize);
        try {
          const resp = await fetch('/api/coverage/sample', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ points: chunk }),
          });
          if (!resp.ok || cancelled) continue;
          const { values } = await resp.json();
          for (let j = 0; j < values.length; j++) {
            const fi = indices[start + j];
            features[fi].properties.signal = values[j];
          }
        } catch (e) {
          console.warn('Coverage sample failed:', e);
        }
      }

      if (!cancelled) {
        src.setData({ type: 'FeatureCollection', features });
        console.log(`Buildings colored with real dBm values`);
      }
    };

    updateColors();
    return () => { cancelled = true; };
  }, [coverageResult]);

  // 3D individual trees (Three.js) and roads (OSM)
  const lastEnvLoad = useRef<{ lat: number; lon: number; radius: number } | null>(null);
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    const lat = txPosition[1];
    const lon = txPosition[0];
    const envRadius = Math.min(Math.max(radius, 2), 10);

    // Skip if TX hasn't moved much
    const prev = lastEnvLoad.current;
    if (prev) {
      const dlat = (lat - prev.lat) * 111320;
      const dlon = (lon - prev.lon) * 111320 * Math.cos(lat * Math.PI / 180);
      if (Math.sqrt(dlat * dlat + dlon * dlon) < 500 && Math.abs(envRadius - prev.radius) < 0.5) return;
    }

    let cancelled = false;

    const loadEnvironment = async () => {
      try {
        const resp = await fetch(`/api/data/environment?lat=${lat}&lon=${lon}&radius_km=${envRadius}`);
        if (!resp.ok || cancelled) return;
        const data = await resp.json();
        if (cancelled) return;

        // --- 3D trees ---
        const treeFeatures = data.trees?.features || [];
        if (treeFeatures.length > 0) {
          try {
            if (map.getLayer('trees-3d')) map.removeLayer('trees-3d');
            if (map.getLayer('trees-trunk')) map.removeLayer('trees-trunk');
            if (map.getSource('trees-3d-src')) map.removeSource('trees-3d-src');
            if (map.getSource('trees-trunk-src')) map.removeSource('trees-trunk-src');
          } catch (_) { /* ignore */ }

          // Generate canopy + trunk hexagons from point data
          const cosLat = Math.cos((lat * Math.PI) / 180);
          const canopyFeatures: any[] = [];
          const trunkFeatures: any[] = [];

          for (const f of treeFeatures) {
            const [tlng, tlat] = f.geometry.coordinates;
            const h = f.properties.h || 8;

            // Canopy hexagon (wide)
            const cr = Math.max(3, h * 0.4);
            const cdlat = cr / 111320;
            const cdlng = cr / (111320 * cosLat);
            const cring: number[][] = [];
            for (let i = 0; i < 6; i++) {
              const a = (Math.PI / 3) * i;
              cring.push([tlng + cdlng * Math.cos(a), tlat + cdlat * Math.sin(a)]);
            }
            cring.push(cring[0]);
            canopyFeatures.push({
              type: 'Feature',
              geometry: { type: 'Polygon', coordinates: [cring] },
              properties: { h, base: h * 0.3 },
            });

            // Trunk hexagon (thin)
            const tr = Math.max(0.5, h * 0.06);
            const tdlat = tr / 111320;
            const tdlng = tr / (111320 * cosLat);
            const tring: number[][] = [];
            for (let i = 0; i < 6; i++) {
              const a = (Math.PI / 3) * i;
              tring.push([tlng + tdlng * Math.cos(a), tlat + tdlat * Math.sin(a)]);
            }
            tring.push(tring[0]);
            trunkFeatures.push({
              type: 'Feature',
              geometry: { type: 'Polygon', coordinates: [tring] },
              properties: { h: h * 0.3 },
            });
          }

          // Trunk layer (brown, from ground to 30% height)
          map.addSource('trees-trunk-src', {
            type: 'geojson',
            data: { type: 'FeatureCollection', features: trunkFeatures },
          });
          map.addLayer({
            id: 'trees-trunk',
            type: 'fill-extrusion',
            source: 'trees-trunk-src',
            paint: {
              'fill-extrusion-color': '#5D4037',
              'fill-extrusion-height': ['*', ['get', 'h'], 1.5],
              'fill-extrusion-base': 0,
              'fill-extrusion-opacity': 0.9,
            },
          });

          // Canopy layer (green, from 30% to 100% height)
          map.addSource('trees-3d-src', {
            type: 'geojson',
            data: { type: 'FeatureCollection', features: canopyFeatures },
          });
          map.addLayer({
            id: 'trees-3d',
            type: 'fill-extrusion',
            source: 'trees-3d-src',
            paint: {
              'fill-extrusion-color': [
                'interpolate', ['linear'], ['get', 'h'],
                3, '#7cb342',
                10, '#43a047',
                20, '#2e7d32',
              ],
              'fill-extrusion-height': ['*', ['get', 'h'], 1.5],
              'fill-extrusion-base': ['*', ['get', 'base'], 1.5],
              'fill-extrusion-opacity': 0.8,
            },
          });

          const t = performance.now() - loadStartRef.current;
          setLoadMetrics(m => ({ ...m, trees: Math.round(t) }));
          console.log(`⏱ 3D trees: ${canopyFeatures.length} (${Math.round(t)}ms)`);
        }

        lastEnvLoad.current = { lat, lon, radius: envRadius };
        // Mark scene as ready once trees are loaded (last heavy layer)
        setSceneReady(true);
        const totalT = performance.now() - loadStartRef.current;
        setLoadMetrics(m => ({ ...m, total: Math.round(totalT) }));
        console.log(`⏱ Scene fully loaded: ${Math.round(totalT)}ms`);
      } catch (e) {
        console.error('Environment data failed:', e);
        setSceneReady(true); // don't block on failure
      }
    };

    loadEnvironment();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [txPosition[0], txPosition[1], radius, mapReady, darkMode]);

  // Toggle trees visibility (Three.js custom layer)
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    try {
      const vis = showVegetation ? 'visible' : 'none';
      try {
        if (map.getLayer('trees-3d')) map.setLayoutProperty('trees-3d', 'visibility', vis);
        if (map.getLayer('trees-trunk')) map.setLayoutProperty('trees-trunk', 'visibility', vis);
      } catch(_) {}
    } catch (_) { /* layers may not exist yet */ }
  }, [showVegetation, mapReady]);

  // Toggle roads visibility
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    try {
      if (map.getLayer('roads-3d')) {
        map.setLayoutProperty('roads-3d', 'visibility', showRoads ? 'visible' : 'none');
      }
    } catch (_) { /* layer may not exist yet */ }
  }, [showRoads, mapReady]);


  const stops = COLOR_STOPS[outputUnits] || COLOR_STOPS['dBm'];
  const fr = locale === 'fr';

  return (
    <div className="flex-1 relative overflow-hidden">
      <div ref={containerRef} style={{ position: 'absolute', inset: 0 }} />

      {/* Loading overlay — hides map until all layers are loaded */}
      {!sceneReady && (
        <div className="absolute inset-0 z-50 bg-surface-1 flex flex-col items-center justify-center gap-4">
          <div className="w-10 h-10 border-4 border-brand-500 border-t-transparent rounded-full animate-spin" />
          <div className="text-sm text-gray-400 space-y-1 text-center">
            <div>{fr ? 'Chargement du modèle 3D...' : 'Loading 3D model...'}</div>
            <div className="text-xs text-gray-500 font-mono space-y-0.5">
              {loadMetrics.map ? <div>Carte: {loadMetrics.map}ms</div> : <div>Carte...</div>}
              {loadMetrics.buildings ? <div>Bâtiments: {loadMetrics.buildings}ms</div> : mapReady > 0 ? <div>Bâtiments...</div> : null}
              {loadMetrics.trees ? <div>Arbres: {loadMetrics.trees}ms</div> : loadMetrics.buildings ? <div>Arbres...</div> : null}
            </div>
          </div>
        </div>
      )}

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
