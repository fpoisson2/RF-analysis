import React, { useMemo, useRef, useState } from 'react';
import { PathResponse } from '../types';
import { Locale } from '../i18n';
import { X, ChevronUp, ChevronDown } from 'lucide-react';

interface Props {
  path: PathResponse | null;
  loading: boolean;
  locale: Locale;
  onClose: () => void;
  onHoverDistance: (distance_m: number | null) => void;
  tx: { lat: number; lon: number };
  rx: { lat: number | null; lon: number | null };
}

export const PathProfilePanel: React.FC<Props> = ({
  path, loading, locale, onClose, onHoverDistance, tx, rx,
}) => {
  const fr = locale === 'fr';
  const [collapsed, setCollapsed] = useState(false);
  const [hover, setHover] = useState<number | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);

  if (!path && !loading) return null;

  return (
    <div className="absolute bottom-0 left-0 right-0 z-20 bg-surface-1/95 backdrop-blur-sm border-t border-gray-700/80">
      <div className="flex items-center justify-between px-3 py-1.5 bg-surface-2 border-b border-gray-700/50">
        <div className="flex items-center gap-3 text-sm">
          <span className="font-semibold text-gray-200">
            {fr ? 'Profil de lien' : 'Path profile'}
          </span>
          {path && (() => {
            const maxObs = Math.max(0, ...(path.fresnel_obstruction_pct ?? [0]));
            return (
              <>
                <span className="text-gray-500">·</span>
                <span className="font-mono text-xs text-gray-300">
                  {path.stats.distance_km} km @ {path.stats.bearing_deg}°
                </span>
                <span className="text-gray-500">·</span>
                <span className={`font-mono text-xs ${path.stats.clear_path ? 'text-green-400' : 'text-orange-400'}`}>
                  {path.stats.clear_path
                    ? (fr ? 'LoS clair' : 'Clear LoS')
                    : `${path.stats.n_los_obstructions} LoS, ${path.stats.n_fresnel_obstructions} Fresnel`}
                </span>
                {maxObs > 0 && (
                  <>
                    <span className="text-gray-500">·</span>
                    <span className="font-mono text-xs text-orange-300" title={fr ? 'Obstruction max de la zone de Fresnel' : 'Max Fresnel zone obstruction'}>
                      {fr ? 'F max' : 'F max'}: {maxObs.toFixed(1)}%
                    </span>
                  </>
                )}
                <span className="text-gray-500">·</span>
                <span className="font-mono text-xs">
                  <span className="text-gray-400">{fr ? 'Signal RX' : 'RX Signal'}: </span>
                  <span className="text-gray-300" title="ITM only">ITM {path.stats.signal_at_rx_itm ?? path.stats.signal_at_rx} dBm</span>
                  <span className="text-gray-500"> / </span>
                  <span className="text-brand-400" title="With Fresnel diffraction loss">F {path.stats.signal_at_rx} dBm</span>
                </span>
              </>
            );
          })()}
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={() => setCollapsed(!collapsed)}
            className="p-1 rounded hover:bg-surface-3 text-gray-400"
            title={collapsed ? 'Expand' : 'Collapse'}
          >
            {collapsed ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
          </button>
          <button
            onClick={onClose}
            className="p-1 rounded hover:bg-surface-3 text-gray-400"
            title="Close"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      </div>

      {!collapsed && (
        <div className="p-3">
          {loading && !path && (
            <div className="h-48 flex items-center justify-center text-sm text-gray-400">
              <div className="w-6 h-6 border-2 border-brand-500 border-t-transparent rounded-full animate-spin mr-2" />
              {fr ? 'Calcul du profil...' : 'Computing profile...'}
            </div>
          )}
          {path && (
            <PathChart
              path={path}
              hover={hover}
              onHover={(d) => { setHover(d); onHoverDistance(d); }}
              fr={fr}
              svgRef={svgRef}
              tx={tx}
              rx={rx}
            />
          )}
        </div>
      )}
    </div>
  );
};

function PathChart({ path, hover, onHover, fr, svgRef, tx, rx }: {
  path: PathResponse;
  hover: number | null;
  onHover: (d: number | null) => void;
  fr: boolean;
  svgRef: React.RefObject<SVGSVGElement>;
  tx: { lat: number; lon: number };
  rx: { lat: number | null; lon: number | null };
}) {
  const W = 1000, H = 280;
  const M = { l: 60, r: 80, t: 10, b: 40 };

  const n = path.distances.length;
  const dMax = path.distances[n - 1];
  const ground = path.ground_elevations ?? path.elevations;
  const surface = path.surface_elevations ?? ground;
  const los = path.los_line ?? [];
  const fresnelR = path.fresnel_radius ?? [];

  const stats = path.stats;
  const txTop = stats.tx_elevation + (stats.tx_height_agl ?? 0);
  const rxTop = stats.rx_elevation + (stats.rx_height_agl ?? 0);

  // y-axis range
  let yMin = Math.min(stats.min_elevation, ...surface);
  let yMax = Math.max(stats.max_surface ?? stats.max_elevation, txTop, rxTop);
  // Include Fresnel zone envelope above LoS
  for (let i = 0; i < n; i++) {
    const up = (los[i] ?? 0) + (fresnelR[i] ?? 0);
    if (up > yMax) yMax = up;
    const dn = (los[i] ?? 0) - (fresnelR[i] ?? 0);
    if (dn < yMin) yMin = dn;
  }
  const pad = (yMax - yMin) * 0.08 || 5;
  yMin -= pad;
  yMax += pad;

  const xScale = (d: number) => M.l + (d / dMax) * (W - M.l - M.r);
  const yScale = (y: number) => M.t + (H - M.t - M.b) * (1 - (y - yMin) / (yMax - yMin));

  const toPath = (arr: number[]) =>
    arr.map((y, i) => `${i === 0 ? 'M' : 'L'}${xScale(path.distances[i])},${yScale(y)}`).join(' ');

  const groundArea = `M${xScale(0)},${yScale(yMin)} ` +
    ground.map((y, i) => `L${xScale(path.distances[i])},${yScale(y)}`).join(' ') +
    ` L${xScale(dMax)},${yScale(yMin)} Z`;

  const canopyArea = `M${xScale(0)},${yScale(ground[0])} ` +
    surface.map((y, i) => `L${xScale(path.distances[i])},${yScale(y)}`).join(' ') +
    ' ' + ground.slice().reverse().map((y, j) => {
      const i = n - 1 - j;
      return `L${xScale(path.distances[i])},${yScale(y)}`;
    }).join(' ') +
    ' Z';

  // Fresnel 1st zone envelope
  const fresnelPath = los.length === n ? (() => {
    const upper = los.map((y, i) => `${i === 0 ? 'M' : 'L'}${xScale(path.distances[i])},${yScale(y + (fresnelR[i] ?? 0))}`).join(' ');
    const lower = los.slice().reverse().map((y, j) => {
      const i = n - 1 - j;
      return `L${xScale(path.distances[i])},${yScale(y - (fresnelR[i] ?? 0))}`;
    }).join(' ');
    return upper + ' ' + lower + ' Z';
  })() : '';

  // X ticks
  const xTicks = [0, 0.25, 0.5, 0.75, 1].map(t => t * dMax);
  const yTicks = [0, 0.25, 0.5, 0.75, 1].map(t => yMin + t * (yMax - yMin));

  const hoverIdx = hover != null
    ? Math.max(0, Math.min(n - 1, Math.round((hover / dMax) * (n - 1))))
    : null;

  const handleMouseMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const svg = svgRef.current;
    if (!svg) return;
    const rect = svg.getBoundingClientRect();
    const x = ((e.clientX - rect.left) / rect.width) * W;
    if (x < M.l || x > W - M.r) { onHover(null); return; }
    const d = ((x - M.l) / (W - M.l - M.r)) * dMax;
    onHover(d);
  };

  return (
    <div className="text-xs">
      <svg
        ref={svgRef}
        viewBox={`0 0 ${W} ${H}`}
        className="w-full h-[280px] select-none cursor-crosshair"
        onMouseMove={handleMouseMove}
        onMouseLeave={() => onHover(null)}
      >
        <defs>
          <clipPath id="chart-clip">
            <rect x={M.l} y={M.t} width={W - M.l - M.r} height={H - M.t - M.b} />
          </clipPath>
        </defs>

        {/* grid */}
        {yTicks.map((v, i) => (
          <line key={i} x1={M.l} x2={W - M.r} y1={yScale(v)} y2={yScale(v)}
                stroke="#374151" strokeWidth="0.5" strokeDasharray="2 3" />
        ))}
        {xTicks.map((v, i) => (
          <line key={i} x1={xScale(v)} x2={xScale(v)} y1={M.t} y2={H - M.b}
                stroke="#374151" strokeWidth="0.5" strokeDasharray="2 3" />
        ))}

        {/* All data layers clipped to chart area */}
        <g clipPath="url(#chart-clip)">
          {/* Ground (brown) */}
          <path d={groundArea} fill="rgba(139, 69, 19, 0.75)" stroke="#8b4513" strokeWidth="1" />

          {/* Canopy/buildings (surface above ground) */}
          <path d={canopyArea} fill="rgba(34, 197, 94, 0.4)" stroke="rgba(34, 197, 94, 0.7)" strokeWidth="0.5" />

          {/* Surface line (DSM top) */}
          <path d={toPath(surface)} fill="none" stroke="#22c55e" strokeWidth="1" />

          {/* Fresnel zone — drawn on top so it's visible over terrain */}
          {fresnelPath && (
            <path d={fresnelPath} fill="rgba(251, 191, 36, 0.18)" stroke="rgba(251, 191, 36, 0.55)" strokeWidth="1" />
          )}

          {/* LoS line */}
          {los.length === n && (
            <path d={toPath(los)} fill="none" stroke="#fbbf24" strokeWidth="1.5" strokeDasharray="4 3" />
          )}

          {/* Obstruction regions */}
          {(path.obstructions ?? []).map((obs, i) => (
            <rect
              key={i}
              x={xScale(obs.start_m)}
              width={Math.max(2, xScale(obs.end_m) - xScale(obs.start_m))}
              y={M.t}
              height={H - M.t - M.b}
              fill={obs.type === 'los' ? 'rgba(239, 68, 68, 0.18)' : 'rgba(249, 115, 22, 0.14)'}
            />
          ))}
        </g>

        {/* TX / RX antennas (vertical bars) */}
        <line x1={xScale(0)} x2={xScale(0)} y1={yScale(stats.tx_elevation)} y2={yScale(txTop)}
              stroke="#f97316" strokeWidth="2" />
        <circle cx={xScale(0)} cy={yScale(txTop)} r={3} fill="#f97316" />
        <line x1={xScale(dMax)} x2={xScale(dMax)} y1={yScale(stats.rx_elevation)} y2={yScale(rxTop)}
              stroke="#3b82f6" strokeWidth="2" />
        <circle cx={xScale(dMax)} cy={yScale(rxTop)} r={3} fill="#3b82f6" />

        {/* Axes */}
        <line x1={M.l} x2={W - M.r} y1={H - M.b} y2={H - M.b} stroke="#6b7280" strokeWidth="1" />
        <line x1={M.l} x2={M.l} y1={M.t} y2={H - M.b} stroke="#6b7280" strokeWidth="1" />

        {/* Y tick labels (elevation) */}
        {yTicks.map((v, i) => (
          <text key={i} x={M.l - 6} y={yScale(v) + 3} fill="#9ca3af" fontSize="10" textAnchor="end" fontFamily="ui-monospace,monospace">
            {v.toFixed(0)} m
          </text>
        ))}

        {/* X tick labels (distance) */}
        {xTicks.map((v, i) => (
          <text key={i} x={xScale(v)} y={H - M.b + 14} fill="#9ca3af" fontSize="10" textAnchor="middle" fontFamily="ui-monospace,monospace">
            {(v / 1000).toFixed(2)} km
          </text>
        ))}

        {/* Right-axis: signal curve */}
        {path.signal_levels && path.signal_levels.length === n && (() => {
          const sMin = Math.min(...path.signal_levels);
          const sMax = Math.max(...path.signal_levels);
          const sYScale = (s: number) => M.t + (H - M.t - M.b) * (1 - (s - sMin) / Math.max(sMax - sMin, 1));
          const sPath = path.signal_levels.map((s, i) =>
            `${i === 0 ? 'M' : 'L'}${xScale(path.distances[i])},${sYScale(s)}`
          ).join(' ');
          const sTicks = [sMin, (sMin + sMax) / 2, sMax];
          return (
            <g>
              <path d={sPath} fill="none" stroke="#ec4899" strokeWidth="1.2" opacity={0.85} />
              {sTicks.map((v, i) => (
                <text key={i} x={W - M.r + 6} y={sYScale(v) + 3} fill="#ec4899" fontSize="10" fontFamily="ui-monospace,monospace">
                  {v.toFixed(0)} dBm
                </text>
              ))}
            </g>
          );
        })()}

        {/* Hover marker */}
        {hoverIdx != null && (() => {
          const hx = xScale(path.distances[hoverIdx]);
          return (
            <g>
              <line x1={hx} x2={hx} y1={M.t} y2={H - M.b} stroke="#22d3ee" strokeWidth="1" />
              <circle cx={hx} cy={yScale(surface[hoverIdx])} r={3} fill="#22d3ee" />
              {los[hoverIdx] != null && (
                <circle cx={hx} cy={yScale(los[hoverIdx])} r={3} fill="#fbbf24" />
              )}
            </g>
          );
        })()}
      </svg>

      {/* Legend + hover readout — fixed height so the pill appearing doesn't shift layout */}
      <div className="mt-1 relative flex items-center gap-4 flex-wrap text-[11px] font-mono min-h-[26px]">
        <Legend color="#8b4513" label={fr ? 'Sol (MNT)' : 'Ground (DTM)'} />
        <Legend color="#22c55e" label={fr ? 'Canopée / bâti' : 'Canopy / buildings'} />
        <Legend color="#fbbf24" label="LoS" dashed />
        <Legend color="rgba(251,191,36,0.5)" label={fr ? '1ère zone Fresnel' : '1st Fresnel zone'} fill />
        <Legend color="#ec4899" label={fr ? 'Signal (dBm)' : 'Signal (dBm)'} />
        <Legend color="#ef4444" label={fr ? 'Obstruction LoS' : 'LoS block'} fill />
        <Legend color="#f97316" label={fr ? 'Obstruction Fresnel' : 'Fresnel block'} fill />

        {hoverIdx != null && path.distances[hoverIdx] != null && (
          <div className="absolute right-0 top-0 px-2 py-1 rounded bg-surface-3 flex gap-3 shadow-lg whitespace-nowrap">
            <span>d={((path.distances[hoverIdx]) / 1000).toFixed(3)}km</span>
            <span>sol={ground[hoverIdx].toFixed(1)}m</span>
            <span>surface={surface[hoverIdx].toFixed(1)}m</span>
            {los[hoverIdx] != null && <span>LoS={los[hoverIdx].toFixed(1)}m</span>}
            {fresnelR[hoverIdx] != null && <span>F1={fresnelR[hoverIdx].toFixed(1)}m</span>}
            {path.fresnel_obstruction_pct?.[hoverIdx] != null && (
              <span className={path.fresnel_obstruction_pct[hoverIdx] > 40 ? 'text-orange-400' : path.fresnel_obstruction_pct[hoverIdx] > 0 ? 'text-yellow-400' : 'text-gray-500'}>
                obstr={path.fresnel_obstruction_pct[hoverIdx].toFixed(1)}%
              </span>
            )}
            <span className="text-pink-400">
              {path.signal_levels[hoverIdx].toFixed(1)}dBm
            </span>
          </div>
        )}
      </div>

      {/* Endpoints summary */}
      <div className="mt-2 flex gap-6 text-[11px] font-mono text-gray-400">
        <div>
          <span className="text-orange-400 font-semibold">TX</span>{' '}
          {tx.lat.toFixed(5)}, {tx.lon.toFixed(5)} · {stats.tx_elevation}m +{stats.tx_height_agl ?? 0}m
        </div>
        {rx.lat != null && rx.lon != null && (
          <div>
            <span className="text-blue-400 font-semibold">RX</span>{' '}
            {rx.lat.toFixed(5)}, {rx.lon.toFixed(5)} · {stats.rx_elevation}m +{stats.rx_height_agl ?? 0}m
          </div>
        )}
      </div>
    </div>
  );
}

function Legend({ color, label, dashed, fill }: { color: string; label: string; dashed?: boolean; fill?: boolean }) {
  return (
    <span className="inline-flex items-center gap-1">
      {fill ? (
        <span className="inline-block w-4 h-3 rounded-sm" style={{ backgroundColor: color }} />
      ) : (
        <svg width="16" height="8">
          <line x1="0" y1="4" x2="16" y2="4"
                stroke={color} strokeWidth="2"
                strokeDasharray={dashed ? '3 2' : undefined} />
        </svg>
      )}
      <span className="text-gray-400">{label}</span>
    </span>
  );
}
