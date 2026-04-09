import React, { useState, useCallback, useRef, useEffect, useMemo } from 'react';
import { MapView } from './components/Map';
import { Sidebar } from './components/Sidebar';
import { Console } from './components/Console';
import {
  Transmitter, Signal, Feeder, Antenna, Receiver,
  PropagationModel, Environment, OutputConfig, TabId, AreaResponse,
} from './types';
import { calculateArea, getHealth } from './api/client';
import { t, getLocale, setLocale, Locale } from './i18n';
import { Radio, Sun, Moon, HelpCircle, Zap, Globe } from 'lucide-react';

const DEFAULT_TX: Transmitter = { lat: 46.83035, lon: -71.227008, height: 30, name: 'Site', network: 'Mon Réseau' };
const DEFAULT_SIGNAL: Signal = { frequency: 155, power: 5, bandwidth: 0.25 };
const DEFAULT_FEEDER: Feeder = { loss: 3 };
const DEFAULT_ANTENNA: Antenna = { gain: 2.15, azimuth: 0, tilt: 0, h_beamwidth: 360, v_beamwidth: 90, pattern_type: 'dipole' };
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
    setTx(prev => ({ ...prev, lat: parseFloat(lat.toFixed(6)), lon: parseFloat(lon.toFixed(6)) }));
    log(`${i('console.tx_moved')} ${lat.toFixed(6)}, ${lon.toFixed(6)}`);
  }, [log, i]);

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
        />

        <div className="flex-1 relative flex flex-col">
          <MapView
            onMapClick={handleMapClick}
            txPosition={txPosition}
            coverageResult={result}
            darkMode={darkMode}
            locale={locale}
            outputUnits={output.units}
            terrainLayer={terrainLayer}
            onTerrainLayerChange={setTerrainLayer}
            hasLidar={hasLidar}
            radius={output.radius}
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
