import React, { useState, useCallback, useRef, useEffect, useMemo } from 'react';
import { MapView } from './components/Map';
import { Sidebar } from './components/Sidebar';
import { Console } from './components/Console';
import { PathProfilePanel } from './components/PathProfilePanel';
import {
  Transmitter, Signal, Feeder, Antenna, Receiver,
  PropagationModel, Environment, OutputConfig, TabId, AreaResponse, PathResponse,
} from './types';
import { calculateArea, calculatePath, getHealth } from './api/client';
import { t, getLocale, setLocale, Locale } from './i18n';
import { Radio, Sun, Moon, HelpCircle, Zap, Globe } from 'lucide-react';

const DEFAULT_TX: Transmitter = { lat: 46.83035, lon: -71.227008, height: 30, name: 'Site', network: 'Mon Réseau' };
const DEFAULT_SIGNAL: Signal = { frequency: 155, power: 5, bandwidth: 0.25 };
const DEFAULT_FEEDER: Feeder = { loss: 3 };
const DEFAULT_ANTENNA: Antenna = { gain: 2.15, azimuth: 0, tilt: 0, h_beamwidth: 360, v_beamwidth: 90, pattern_type: 'dipole', polarization: 'V' };
const DEFAULT_RX: Receiver = { lat: null, lon: null, height: 1.5, gain: 2, sensitivity: -90 };
const DEFAULT_MODEL: PropagationModel = { name: 'itm', reliability: 50, diffraction: 'deygout94' };
const DEFAULT_ENV: Environment = { elevation_model: 'dtm', noise_floor: -100 };
const DEFAULT_OUTPUT: OutputConfig = { resolution: 30, radius: 10, units: 'dBm', color_schema: 'signal_strength' };

export default function App() {
  const [darkMode, setDarkMode] = useState(true);
  const [locale, setLocaleState] = useState<Locale>(getLocale());
  const [activeTab, setActiveTab] = useState<TabId>('tx');
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [consoleOpen, setConsoleOpen] = useState(true);
  const [consoleMessages, setConsoleMessages] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<AreaResponse | null>(null);
  const [terrainLayer, setTerrainLayer] = useState<string | null>(null); // null, 'elevation', 'canopy', 'surface'
  const [hasLidar, setHasLidar] = useState(false);
  const [gpuName, setGpuName] = useState<string | null>(null);
  const [placementMode, setPlacementMode] = useState<'tx' | 'rx' | null>(null);
  const [pathResult, setPathResult] = useState<PathResponse | null>(null);
  const [pathLoading, setPathLoading] = useState(false);
  const [pathHover, setPathHover] = useState<number | null>(null);

  // Receiver positions (multiple). The Receiver template holds shared
  // height/gain/sensitivity; each entry just adds a (lat,lon,id).
  const [rxPositions, setRxPositions] = useState<Array<{ id: string; lat: number; lon: number }>>([]);
  const [selectedRxId, setSelectedRxId] = useState<string | null>(null);
  // Per-RX computed signal values (ITM only + with diffraction)
  const [rxSignals, setRxSignals] = useState<Record<string, { itm: number; fresnel: number; clear: boolean }>>({});

  const [tx, setTx] = useState<Transmitter>(DEFAULT_TX);
  const [signal, setSignal] = useState<Signal>(DEFAULT_SIGNAL);
  const [feeder, setFeeder] = useState<Feeder>(DEFAULT_FEEDER);
  const [antenna, setAntenna] = useState<Antenna>(DEFAULT_ANTENNA);
  const [rx, setRx] = useState<Receiver>(DEFAULT_RX);
  const [model, setModel] = useState<PropagationModel>(DEFAULT_MODEL);
  const [env, setEnv] = useState<Environment>(DEFAULT_ENV);
  const [output, setOutput] = useState<OutputConfig>(DEFAULT_OUTPUT);

  const i = useCallback((key: any) => t(key, locale), [locale]);

  useEffect(() => {
    setConsoleMessages([`[${new Date().toLocaleTimeString()}] ${i('console.ready')}`]);
    // Check server capabilities
    getHealth().then(h => {
      if (h.lidar?.available) setHasLidar(true);
      if (h.gpu?.available) setGpuName(h.gpu.device);
    }).catch(() => {});
  }, [locale]);

  const log = useCallback((msg: string) => {
    setConsoleMessages(prev => [...prev, `[${new Date().toLocaleTimeString()}] ${msg}`]);
  }, []);

  const handleMapClick = useCallback((lat: number, lon: number) => {
    if (!placementMode) return;
    const rLat = parseFloat(lat.toFixed(6));
    const rLon = parseFloat(lon.toFixed(6));
    if (placementMode === 'rx') {
      // Adds a NEW receiver at the clicked point. Multiple RXs supported.
      const id = `rx-${Date.now().toString(36)}`;
      setRxPositions(prev => [...prev, { id, lat: rLat, lon: rLon }]);
      setSelectedRxId(id);
      log(`+RX${rxPositions.length + 1} → ${rLat}, ${rLon}`);
    } else {
      setTx(prev => ({ ...prev, lat: rLat, lon: rLon }));
      log(`${i('console.tx_moved')} ${rLat}, ${rLon}`);
    }
    setPlacementMode(null);
  }, [log, i, placementMode, rxPositions.length]);

  const handleTxDragEnd = useCallback((lat: number, lon: number) => {
    const rLat = parseFloat(lat.toFixed(6));
    const rLon = parseFloat(lon.toFixed(6));
    setTx(prev => ({ ...prev, lat: rLat, lon: rLon }));
    log(`${i('console.tx_moved')} ${rLat}, ${rLon}`);
  }, [log, i]);

  const handleRxDragEnd = useCallback((id: string, lat: number, lon: number) => {
    const rLat = parseFloat(lat.toFixed(6));
    const rLon = parseFloat(lon.toFixed(6));
    setRxPositions(prev => prev.map(p => p.id === id ? { ...p, lat: rLat, lon: rLon } : p));
    log(`RX → ${rLat}, ${rLon}`);
  }, [log]);

  const handleRxSelect = useCallback((id: string) => setSelectedRxId(id), []);
  const handleRxRemove = useCallback((id: string) => {
    setRxPositions(prev => prev.filter(p => p.id !== id));
    setSelectedRxId(prev => (prev === id ? null : prev));
  }, []);
  const handleRxClearAll = useCallback(() => {
    setRxPositions([]);
    setSelectedRxId(null);
    setPathResult(null);
  }, []);

  // Cancel placement with Escape
  useEffect(() => {
    if (!placementMode) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setPlacementMode(null);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [placementMode]);

  // Auto-select first RX if none selected
  useEffect(() => {
    if (rxPositions.length === 0) {
      setSelectedRxId(null);
      setPathResult(null);
    } else if (!selectedRxId || !rxPositions.find(p => p.id === selectedRxId)) {
      setSelectedRxId(rxPositions[0].id);
    }
  }, [rxPositions, selectedRxId]);

  const selectedRx = useMemo(
    () => rxPositions.find(p => p.id === selectedRxId) ?? null,
    [rxPositions, selectedRxId],
  );

  // Compute paths for ALL RX positions (parallel). Store signal values per RX
  // for the sidebar list, and the full result for the selected one.
  useEffect(() => {
    if (rxPositions.length === 0) {
      setPathResult(null);
      setRxSignals({});
      return;
    }
    let cancelled = false;
    setPathLoading(true);
    const baseReq = { transmitter: tx, signal, feeder, antenna, model, environment: env };

    Promise.all(rxPositions.map(p =>
      calculatePath({ ...baseReq, receiver: { ...rx, lat: p.lat, lon: p.lon } })
        .then(res => ({ id: p.id, res }))
        .catch(() => ({ id: p.id, res: null as PathResponse | null }))
    )).then(results => {
      if (cancelled) return;
      const sigs: Record<string, { itm: number; fresnel: number; clear: boolean }> = {};
      let selectedRes: PathResponse | null = null;
      for (const { id, res } of results) {
        if (!res) continue;
        const s = res.stats;
        sigs[id] = {
          itm: s.signal_at_rx_itm ?? s.signal_at_rx,
          fresnel: s.signal_at_rx,
          clear: !!s.clear_path,
        };
        if (id === selectedRxId) selectedRes = res;
      }
      setRxSignals(sigs);
      setPathResult(selectedRes);
    }).finally(() => { if (!cancelled) setPathLoading(false); });

    return () => { cancelled = true; };
  }, [rxPositions, selectedRxId, tx.lat, tx.lon, tx.height,
      rx.height, rx.gain,
      signal.frequency, signal.power, feeder.loss, antenna.gain,
      model.name, model.diffraction]);

  const toggleLocale = useCallback(() => {
    const next = locale === 'fr' ? 'en' : 'fr';
    setLocaleState(next);
    setLocale(next);
  }, [locale]);

  // Stable reference for map position
  const txPosition = useMemo<[number, number]>(() => [tx.lon, tx.lat], [tx.lon, tx.lat]);

  // Computed values
  const erp_w = signal.power * Math.pow(10, (antenna.gain - 2.15 - feeder.loss) / 10);
  const eirp_w = signal.power * Math.pow(10, (antenna.gain - feeder.loss) / 10);
  const erp_dbm = 10 * Math.log10(Math.max(erp_w, 0.0001) * 1000);
  const eirp_dbm = 10 * Math.log10(Math.max(eirp_w, 0.0001) * 1000);
  const megapixels = Math.pow(2 * output.radius * 1000 / output.resolution, 2) / 1e6;

  const handleRun = useCallback(async () => {
    setLoading(true);
    log(i('console.calculation_start'));
    log(`ERP: ${erp_w.toFixed(3)}W / ${erp_dbm.toFixed(1)}dBm`);
    log(`EIRP: ${eirp_w.toFixed(3)}W / ${eirp_dbm.toFixed(1)}dBm`);
    log(`${i('out.megapixels')}: ${megapixels.toFixed(2)} MP`);

    try {
      const res = await calculateArea({
        transmitter: tx, signal, feeder, antenna,
        receiver: rx, model, environment: env, output,
      });
      setResult(res);
      log(`${i('console.calculation_done')} (${res.computation_time_ms.toFixed(0)}ms)`);
      log(`${i('console.coverage')}: ${res.stats.coverage_pct}%`);
    } catch (e: any) {
      log(`${i('console.error')}: ${e.message}`);
    } finally {
      setLoading(false);
    }
  }, [tx, signal, feeder, antenna, rx, model, env, output, log, i, erp_w, erp_dbm, eirp_w, eirp_dbm, megapixels]);

  useEffect(() => {
    document.documentElement.classList.toggle('dark', darkMode);
  }, [darkMode]);

  return (
    <div className={`h-screen flex flex-col ${darkMode ? 'dark bg-gray-950' : 'bg-gray-50 text-gray-900'}`}>
      {/* Header */}
      <header className="h-12 flex items-center justify-between px-4 bg-surface-2 border-b border-gray-800 shrink-0 z-10">
        <div className="flex items-center gap-2">
          <Radio className="w-5 h-5 text-brand-400" />
          <span className="font-bold text-lg text-white">{i('app.title')}</span>
          <span className="text-xs text-gray-500 ml-1">{i('app.version')}</span>
        </div>
        <div className="flex items-center gap-1">
          <div className="flex items-center gap-1 px-2 py-1 rounded bg-surface-3 text-xs mr-2" title={gpuName || 'CPU'}>
            <Zap className={`w-3 h-3 ${gpuName ? 'text-yellow-400' : 'text-gray-600'}`} />
            <span className="text-gray-400">{gpuName ? 'GPU' : 'CPU'}</span>
            <span className={`w-2 h-2 rounded-full ${gpuName ? 'bg-green-500' : 'bg-gray-600'}`} />
          </div>
          <button onClick={toggleLocale}
                  className="px-2 py-1 rounded hover:bg-surface-3 transition-colors text-xs font-semibold text-gray-400 border border-gray-700"
                  title={locale === 'fr' ? 'Switch to English' : 'Passer en français'}>
            <Globe className="w-4 h-4 inline mr-1" />
            {locale.toUpperCase()}
          </button>
          <button onClick={() => setDarkMode(!darkMode)} className="p-2 rounded hover:bg-surface-3 transition-colors">
            {darkMode ? <Sun className="w-4 h-4 text-gray-400" /> : <Moon className="w-4 h-4" />}
          </button>
          <button className="p-2 rounded hover:bg-surface-3 transition-colors">
            <HelpCircle className="w-4 h-4 text-gray-400" />
          </button>
        </div>
      </header>

      {/* Main */}
      <div className="flex flex-1 overflow-hidden">
        <Sidebar
          isOpen={sidebarOpen}
          onToggle={() => setSidebarOpen(!sidebarOpen)}
          activeTab={activeTab}
          onTabChange={setActiveTab}
          locale={locale}
          tx={tx} setTx={setTx}
          signal={signal} setSignal={setSignal}
          feeder={feeder} setFeeder={setFeeder}
          antenna={antenna} setAntenna={setAntenna}
          rx={rx} setRx={setRx}
          model={model} setModel={setModel}
          env={env} setEnv={setEnv}
          output={output} setOutput={setOutput}
          onRun={handleRun}
          loading={loading}
          erp_w={erp_w} erp_dbm={erp_dbm}
          eirp_w={eirp_w} eirp_dbm={eirp_dbm}
          megapixels={megapixels}
          placementMode={placementMode}
          setPlacementMode={setPlacementMode}
          rxPositions={rxPositions}
          selectedRxId={selectedRxId}
          rxSignals={rxSignals}
          onRxSelect={handleRxSelect}
          onRxRemove={handleRxRemove}
          onRxClearAll={handleRxClearAll}
        />

        <div className="flex-1 relative flex flex-col">
          <MapView
            onMapClick={handleMapClick}
            onTxDragEnd={handleTxDragEnd}
            onRxDragEnd={handleRxDragEnd}
            onRxSelect={handleRxSelect}
            txPosition={txPosition}
            rxPositions={rxPositions}
            selectedRxId={selectedRxId}
            placementMode={placementMode}
            pathResult={pathResult}
            pathHoverDistance={pathHover}
            coverageResult={result}
            noiseFloor={env.noise_floor}
            darkMode={darkMode}
            locale={locale}
            outputUnits={output.units}
            terrainLayer={terrainLayer}
            onTerrainLayerChange={setTerrainLayer}
            hasLidar={hasLidar}
            radius={output.radius}
          />
          {/* Path profile bottom panel */}
          <PathProfilePanel
            path={pathResult}
            loading={pathLoading}
            locale={locale}
            onClose={handleRxClearAll}
            onHoverDistance={setPathHover}
            tx={{ lat: tx.lat, lon: tx.lon }}
            rx={{ lat: selectedRx?.lat ?? null, lon: selectedRx?.lon ?? null }}
          />
          <Console
            messages={consoleMessages}
            isOpen={consoleOpen}
            onToggle={() => setConsoleOpen(!consoleOpen)}
            locale={locale}
          />
        </div>
      </div>
    </div>
  );
}
