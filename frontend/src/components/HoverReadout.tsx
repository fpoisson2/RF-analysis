import React, { useState, useEffect, useRef } from 'react';
import { Settings } from 'lucide-react';
import { AreaResponse } from '../types';
import { Locale } from '../i18n';

export interface HoverSample {
  lat: number;
  lon: number;
  signal_dbm: number | null;
  screenX: number;
  screenY: number;
}

interface Props {
  sample: HoverSample | null;
  coverageResult: AreaResponse | null;
  noiseFloor: number;
  locale: Locale;
}

const ALL_METRICS = ['gps', 'signal', 'snr', 'pathloss'] as const;
type Metric = typeof ALL_METRICS[number];

const LABELS: Record<Metric, Record<'fr' | 'en', string>> = {
  gps:     { fr: 'Position GPS', en: 'GPS position' },
  signal:  { fr: 'Signal', en: 'Signal' },
  snr:     { fr: 'SNR', en: 'SNR' },
  pathloss:{ fr: 'Perte de parcours', en: 'Path loss' },
};

export const HoverReadout: React.FC<Props> = ({ sample, coverageResult, noiseFloor, locale }) => {
  const [metrics, setMetrics] = useState<Metric[]>(() => {
    try {
      const s = localStorage.getItem('rf_hover_metrics');
      if (s) return JSON.parse(s);
    } catch {}
    return ['gps', 'signal', 'snr'];
  });
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    try { localStorage.setItem('rf_hover_metrics', JSON.stringify(metrics)); } catch {}
  }, [metrics]);

  const fr = locale === 'fr';

  const toggleMetric = (m: Metric) => {
    setMetrics(prev => prev.includes(m) ? prev.filter(x => x !== m) : [...prev, m]);
  };

  // Fixed overlay position (top-right of map, below legend if present)
  return (
    <>
      <div
        className="absolute right-4 top-24 z-20 bg-black/75 backdrop-blur-sm rounded-lg border border-gray-700/60 shadow-lg text-[11px] font-mono text-gray-100 min-w-[180px]"
      >
        <div className="flex items-center justify-between px-2 py-1 border-b border-gray-700/50">
          <span className="text-[10px] uppercase tracking-wider text-gray-400">
            {fr ? 'Survol' : 'Hover'}
          </span>
          <button
            onClick={() => setMenuOpen(!menuOpen)}
            className="p-0.5 rounded hover:bg-white/10"
            title={fr ? 'Métriques' : 'Metrics'}
          >
            <Settings className="w-3 h-3 text-gray-400" />
          </button>
        </div>

        <div className="px-2 py-1.5 space-y-0.5">
          {!sample && (
            <div className="text-gray-500 italic">
              {fr ? 'Déplacer le curseur sur la carte' : 'Move cursor over map'}
            </div>
          )}
          {sample && metrics.includes('gps') && (
            <Row label="GPS">
              <span className="text-white">{sample.lat.toFixed(5)}, {sample.lon.toFixed(5)}</span>
            </Row>
          )}
          {sample && metrics.includes('signal') && (
            <Row label={fr ? 'Signal' : 'Signal'}>
              <span className={signalColor(sample.signal_dbm)}>
                {sample.signal_dbm != null ? `${sample.signal_dbm.toFixed(1)} dBm` : '—'}
              </span>
            </Row>
          )}
          {sample && metrics.includes('snr') && (
            <Row label="SNR">
              <span className={snrColor(sample.signal_dbm, noiseFloor)}>
                {sample.signal_dbm != null
                  ? `${(sample.signal_dbm - noiseFloor).toFixed(1)} dB`
                  : '—'}
              </span>
            </Row>
          )}
          {sample && metrics.includes('pathloss') && coverageResult && (
            <Row label={fr ? 'Perte' : 'Loss'}>
              <span className="text-gray-200">
                {sample.signal_dbm != null
                  ? `${(coverageResult.eirp_dbm - sample.signal_dbm).toFixed(1)} dB`
                  : '—'}
              </span>
            </Row>
          )}
        </div>

        {menuOpen && (
          <div className="border-t border-gray-700/50 px-2 py-1.5 space-y-0.5 bg-black/40">
            <div className="text-[9px] uppercase tracking-wider text-gray-500 mb-1">
              {fr ? 'Afficher' : 'Show'}
            </div>
            {ALL_METRICS.map(m => (
              <label key={m} className="flex items-center gap-2 cursor-pointer hover:bg-white/5 px-1 py-0.5 rounded">
                <input
                  type="checkbox"
                  checked={metrics.includes(m)}
                  onChange={() => toggleMetric(m)}
                  className="w-3 h-3"
                />
                <span className="text-[11px] text-gray-200">{LABELS[m][fr ? 'fr' : 'en']}</span>
              </label>
            ))}
          </div>
        )}
      </div>
    </>
  );
};

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-gray-400">{label}</span>
      {children}
    </div>
  );
}

function signalColor(dbm: number | null): string {
  if (dbm == null) return 'text-gray-500';
  if (dbm >= -70) return 'text-green-400';
  if (dbm >= -90) return 'text-yellow-400';
  if (dbm >= -110) return 'text-orange-400';
  return 'text-red-400';
}

function snrColor(dbm: number | null, noise: number): string {
  if (dbm == null) return 'text-gray-500';
  const snr = dbm - noise;
  if (snr >= 20) return 'text-green-400';
  if (snr >= 10) return 'text-yellow-400';
  if (snr >= 0) return 'text-orange-400';
  return 'text-red-400';
}
