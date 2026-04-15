import React from 'react';
import {
  Radio, Signal, Antenna, Smartphone, Globe, TreePine, Settings,
  Play, Loader2, ChevronLeft, ChevronRight, MapPin, Trash2, HelpCircle,
} from 'lucide-react';
import {
  Transmitter, Signal as SignalType, Feeder, Antenna as AntennaType,
  Receiver, PropagationModel, Environment, OutputConfig, TabId,
} from '../types';
import { Locale, t } from '../i18n';

const TABS: { id: TabId; icon: React.ElementType; labelKey: string }[] = [
  { id: 'tx', icon: Radio, labelKey: 'tab.tx' },
  { id: 'signal', icon: Signal, labelKey: 'tab.signal' },
  { id: 'antenna', icon: Antenna, labelKey: 'tab.antenna' },
  { id: 'rx', icon: Smartphone, labelKey: 'tab.rx' },
  { id: 'model', icon: Globe, labelKey: 'tab.model' },
  { id: 'environment', icon: TreePine, labelKey: 'tab.env' },
  { id: 'output', icon: Settings, labelKey: 'tab.output' },
];

interface SidebarProps {
  isOpen: boolean;
  onToggle: () => void;
  activeTab: TabId;
  onTabChange: (tab: TabId) => void;
  locale: Locale;
  tx: Transmitter; setTx: (v: Transmitter) => void;
  signal: SignalType; setSignal: (v: SignalType) => void;
  feeder: Feeder; setFeeder: (v: Feeder) => void;
  antenna: AntennaType; setAntenna: (v: AntennaType) => void;
  rx: Receiver; setRx: (v: Receiver) => void;
  model: PropagationModel; setModel: (v: PropagationModel) => void;
  env: Environment; setEnv: (v: Environment) => void;
  output: OutputConfig; setOutput: (v: OutputConfig) => void;
  onRun: () => void;
  loading: boolean;
  erp_w: number; erp_dbm: number;
  eirp_w: number; eirp_dbm: number;
  megapixels: number;
  placementMode: 'tx' | 'rx' | null;
  setPlacementMode: (m: 'tx' | 'rx' | null) => void;
  rxPositions: Array<{ id: string; lat: number; lon: number }>;
  selectedRxId: string | null;
  rxSignals: Record<string, { itm: number; fresnel: number; clear: boolean }>;
  onRxSelect: (id: string) => void;
  onRxRemove: (id: string) => void;
  onRxClearAll: () => void;
}

function HelpHint({ text }: { text: string }) {
  return (
    <span
      className="inline-flex items-center cursor-help text-gray-500 hover:text-gray-300"
      title={text}
    >
      <HelpCircle className="w-3 h-3" />
    </span>
  );
}

function Field({ label, unit, help, children }: {
  label: string;
  unit?: string;
  help?: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <div className="flex items-baseline justify-between mb-1 gap-2">
        <label className="label-text inline-flex items-center gap-1">
          {label}
          {help && <HelpHint text={help} />}
        </label>
        {unit && <span className="text-[10px] text-gray-500">{unit}</span>}
      </div>
      {children}
    </div>
  );
}

/**
 * NumberInput: controlled numeric field that lets the user clear the
 * text and type intermediate states (e.g. "", "-", "1.") without the
 * parent state snapping back to a fallback value. The committed numeric
 * value is only set on a valid parse; invalid values are normalised on
 * blur.
 */
interface NumberInputProps extends Omit<React.InputHTMLAttributes<HTMLInputElement>, 'value' | 'onChange' | 'type'> {
  value: number;
  onChange: (v: number) => void;
  fallback?: number;
}
function NumberInput({ value, onChange, fallback = 0, ...rest }: NumberInputProps) {
  const [text, setText] = React.useState<string>(() => String(value));

  // If the upstream numeric value changes (e.g. dragged marker, preset
  // loaded) AND the local text doesn't already parse to that value, sync
  // the local text. This avoids clobbering the user's half-typed entry.
  React.useEffect(() => {
    const parsed = parseFloat(text);
    if (Number.isNaN(parsed) || parsed !== value) {
      setText(String(value));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  return (
    <input
      {...rest}
      type="number"
      value={text}
      onChange={e => {
        const next = e.target.value;
        setText(next);
        const n = parseFloat(next);
        if (!Number.isNaN(n)) onChange(n);
      }}
      onBlur={e => {
        const n = parseFloat(e.target.value);
        if (Number.isNaN(n)) {
          onChange(fallback);
          setText(String(fallback));
        } else {
          // Normalise the displayed text to canonical form
          setText(String(n));
        }
        rest.onBlur?.(e);
      }}
    />
  );
}

export function Sidebar(props: SidebarProps) {
  const { isOpen, onToggle, activeTab, onTabChange, locale, loading, onRun } = props;
  const i = (key: any) => t(key, locale);

  return (
    <div className="flex shrink-0 h-full">
      {/* Tab strip */}
      <div className="w-12 bg-surface-1 border-r border-gray-800 flex flex-col items-center py-2 gap-1">
        {TABS.map(({ id, icon: Icon, labelKey }) => (
          <button
            key={id}
            onClick={() => { onTabChange(id); if (!isOpen) onToggle(); }}
            className={`w-10 h-10 rounded-lg flex items-center justify-center transition-all group relative
              ${activeTab === id && isOpen
                ? 'bg-brand-600/20 text-brand-400'
                : 'text-gray-500 hover:text-gray-300 hover:bg-surface-3'}`}
            title={i(labelKey as any)}
          >
            <Icon className="w-4.5 h-4.5" />
            {/* Tooltip */}
            <span className="absolute left-12 bg-surface-3 text-gray-200 text-xs px-2 py-1 rounded shadow-lg
                            opacity-0 group-hover:opacity-100 pointer-events-none transition-opacity whitespace-nowrap z-50">
              {i(labelKey as any)}
            </span>
          </button>
        ))}

        <div className="flex-1" />

        {/* Collapse toggle */}
        <button onClick={onToggle}
                className="w-10 h-10 rounded-lg flex items-center justify-center text-gray-500 hover:text-gray-300 hover:bg-surface-3 transition-colors">
          {isOpen ? <ChevronLeft className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
        </button>
      </div>

      {/* Content panel */}
      {isOpen && (
        <div className="w-80 bg-surface-2 border-r border-gray-800 flex flex-col">
          <div className="flex-1 overflow-y-auto p-4 space-y-4">
            <PanelContent {...props} />
          </div>

          {/* Run button */}
          <div className="p-4 border-t border-gray-800">
            <button onClick={onRun} disabled={loading} className="btn-primary">
              {loading ? (
                <><Loader2 className="w-4 h-4 animate-spin" />{i('action.running')}</>
              ) : (
                <><Play className="w-4 h-4" />{i('action.run')}</>
              )}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function PanelContent(props: SidebarProps) {
  const { activeTab, locale } = props;
  const i = (key: any) => t(key, locale);

  switch (activeTab) {
    case 'tx':
      return <TxPanel {...props} i={i} />;
    case 'signal':
      return <SignalPanel {...props} i={i} />;
    case 'antenna':
      return <AntennaPanel {...props} i={i} />;
    case 'rx':
      return <RxPanel {...props} i={i} />;
    case 'model':
      return <ModelPanel {...props} i={i} />;
    case 'environment':
      return <EnvPanel {...props} i={i} />;
    case 'output':
      return <OutputPanel {...props} i={i} />;
  }
}

type PanelProps = SidebarProps & { i: (key: any) => string };

function TxPanel({ tx, setTx, i, placementMode, setPlacementMode }: PanelProps) {
  return (
    <>
      <h3 className="section-title">{i('tx.title')}</h3>
      <div className="space-y-3">
        <Field label={i('tx.name')}>
          <input type="text" className="input-field" value={tx.name}
                 onChange={e => setTx({ ...tx, name: e.target.value })} />
        </Field>
        <Field label={i('tx.network')}>
          <input type="text" className="input-field" value={tx.network}
                 onChange={e => setTx({ ...tx, network: e.target.value })} />
        </Field>
        <div className="panel-section space-y-2">
          <div className="label-text">{i('tx.coordinates')}</div>
          <div className="grid grid-cols-2 gap-3">
            <Field label={i('tx.latitude')} unit="D.D">
              <NumberInput step="0.000001" className="input-field font-mono"
                     value={tx.lat} fallback={0}
                     onChange={v => setTx({ ...tx, lat: v })} />
            </Field>
            <Field label={i('tx.longitude')} unit="D.D">
              <NumberInput step="0.000001" className="input-field font-mono"
                     value={tx.lon} fallback={0}
                     onChange={v => setTx({ ...tx, lon: v })} />
            </Field>
          </div>
          <button
            onClick={() => setPlacementMode(placementMode === 'tx' ? null : 'tx')}
            className={`w-full flex items-center justify-center gap-1 px-2 py-1.5 rounded text-xs font-semibold border transition-colors ${
              placementMode === 'tx'
                ? 'bg-orange-600 border-orange-500 text-white'
                : 'bg-surface-3 border-gray-700 text-gray-200 hover:bg-surface-2'
            }`}
          >
            <MapPin className="w-3.5 h-3.5" />
            {placementMode === 'tx' ? i('tx.placing') : i('tx.place')}
          </button>
        </div>
        <Field label={i('tx.height')} unit={i('tx.height_unit')}
               help={i('help.tx.height')}>
          <NumberInput step="1" min="0.1" max="60000" className="input-field"
                 value={tx.height} fallback={1}
                 onChange={v => setTx({ ...tx, height: v })} />
        </Field>
      </div>
    </>
  );
}

function SignalPanel({ signal, setSignal, feeder, setFeeder, erp_w, erp_dbm, eirp_w, eirp_dbm, i }: PanelProps) {
  const efficiency = erp_w / Math.max(signal.power, 0.001) * 100;
  return (
    <>
      <h3 className="section-title">{i('sig.title')}</h3>
      <div className="space-y-3">
        <Field label={i('sig.frequency')} unit="MHz" help={i('help.sig.frequency')}>
          <NumberInput step="0.1" min="2" max="90000" className="input-field"
                 value={signal.frequency} fallback={155}
                 onChange={v => setSignal({ ...signal, frequency: v })} />
        </Field>
        <Field label={i('sig.power')} unit="W" help={i('help.sig.power')}>
          <NumberInput step="0.1" min="0.001" max="10000" className="input-field"
                 value={signal.power} fallback={1}
                 onChange={v => setSignal({ ...signal, power: v })} />
        </Field>
        <Field label={i('sig.bandwidth')} unit="MHz" help={i('help.sig.bandwidth')}>
          <NumberInput step="0.01" min="0.001" max="200" className="input-field"
                 value={signal.bandwidth} fallback={0.25}
                 onChange={v => setSignal({ ...signal, bandwidth: v })} />
        </Field>
      </div>

      <div className="panel-section mt-4">
        <div className="label-text mb-2">{i('feed.title')}</div>
        <Field label={i('feed.loss')} unit="dB" help={i('help.feed.loss')}>
          <NumberInput step="0.1" min="0" max="30" className="input-field"
                 value={feeder.loss} fallback={0}
                 onChange={v => setFeeder({ loss: v })} />
        </Field>
      </div>

      {/* Computed values */}
      <div className="bg-surface-3 rounded-lg p-3 space-y-2">
        <div className="flex justify-between text-xs">
          <span className="text-gray-400">{i('sig.erp')}</span>
          <span className="value-badge">{erp_w.toFixed(3)}W / {erp_dbm.toFixed(1)}dBm</span>
        </div>
        <div className="flex justify-between text-xs">
          <span className="text-gray-400">{i('sig.eirp')}</span>
          <span className="value-badge">{eirp_w.toFixed(3)}W / {eirp_dbm.toFixed(1)}dBm</span>
        </div>
        <div className="flex justify-between text-xs">
          <span className="text-gray-400">{i('feed.efficiency')}</span>
          <span className={`value-badge ${efficiency < 50 ? 'text-red-400' : efficiency < 80 ? 'text-yellow-400' : 'text-brand-400'}`}>
            {efficiency.toFixed(0)}%
          </span>
        </div>
      </div>
    </>
  );
}

function AntennaPanel({ antenna, setAntenna, i, locale }: PanelProps) {
  const fr = locale === 'fr';
  return (
    <>
      <h3 className="section-title">{i('ant.title')}</h3>
      <div className="space-y-3">
        <Field label={i('ant.pattern')} help={i('help.ant.pattern')}>
          <select className="select-field" value={antenna.pattern_type}
                  onChange={e => setAntenna({ ...antenna, pattern_type: e.target.value })}>
            <option value="dipole">{i('ant.pattern_dipole')}</option>
            <option value="isotropic">{i('ant.pattern_isotropic')}</option>
            <option value="custom">{i('ant.pattern_custom')}</option>
            <option value="sector">{i('ant.pattern_sector')}</option>
            <option value="yagi">{i('ant.pattern_yagi')}</option>
          </select>
        </Field>
        <Field label={i('ant.gain')} unit="dBi" help={i('help.ant.gain')}>
          <NumberInput step="0.1" min="-30" max="50" className="input-field"
                 value={antenna.gain} fallback={0}
                 onChange={v => setAntenna({ ...antenna, gain: v })} />
        </Field>
        <Field label={fr ? 'Polarisation' : 'Polarization'}>
          <select className="select-field" value={antenna.polarization || 'V'}
                  onChange={e => setAntenna({ ...antenna, polarization: e.target.value })}>
            <option value="V">{fr ? 'Verticale (V)' : 'Vertical (V)'}</option>
            <option value="H">{fr ? 'Horizontale (H)' : 'Horizontal (H)'}</option>
          </select>
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label={i('ant.azimuth')} unit="deg" help={i('help.ant.azimuth')}>
            <NumberInput step="1" min="0" max="360" className="input-field"
                   value={antenna.azimuth} fallback={0}
                   onChange={v => setAntenna({ ...antenna, azimuth: v })} />
          </Field>
          <Field label={i('ant.tilt')} unit="deg" help={i('help.ant.tilt')}>
            <NumberInput step="0.5" min="-90" max="90" className="input-field"
                   value={antenna.tilt} fallback={0}
                   onChange={v => setAntenna({ ...antenna, tilt: v })} />
          </Field>
        </div>
        {antenna.pattern_type === 'custom' && (
          <div className="grid grid-cols-2 gap-3">
            <Field label={i('ant.h_beamwidth')} unit="deg" help={i('help.ant.hbw')}>
              <NumberInput step="1" min="1" max="360" className="input-field"
                     value={antenna.h_beamwidth} fallback={360}
                     onChange={v => setAntenna({ ...antenna, h_beamwidth: v })} />
            </Field>
            <Field label={i('ant.v_beamwidth')} unit="deg" help={i('help.ant.vbw')}>
              <NumberInput step="1" min="1" max="180" className="input-field"
                     value={antenna.v_beamwidth} fallback={90}
                     onChange={v => setAntenna({ ...antenna, v_beamwidth: v })} />
            </Field>
          </div>
        )}
      </div>
    </>
  );
}

function signalClass(dbm: number): string {
  if (dbm >= -70) return 'text-green-400';
  if (dbm >= -90) return 'text-yellow-400';
  if (dbm >= -110) return 'text-orange-400';
  return 'text-red-400';
}

function RxPanel({ rx, setRx, i, placementMode, setPlacementMode,
                  rxPositions, selectedRxId, rxSignals, onRxSelect, onRxRemove, onRxClearAll }: PanelProps) {
  return (
    <>
      <h3 className="section-title">{i('rx.title')}</h3>
      <div className="space-y-3">
        <div className="panel-section space-y-2">
          <div className="flex items-center justify-between">
            <div className="label-text">
              {i('rx.position')} {rxPositions.length > 0 && <span className="text-gray-500">({rxPositions.length})</span>}
            </div>
            {rxPositions.length > 1 && (
              <button
                onClick={onRxClearAll}
                className="text-[10px] text-red-400 hover:underline"
              >
                Clear all
              </button>
            )}
          </div>

          {rxPositions.length > 0 && (
            <div className="space-y-1 max-h-60 overflow-y-auto pr-1">
              {rxPositions.map((p, idx) => {
                const sig = rxSignals[p.id];
                return (
                  <div
                    key={p.id}
                    onClick={() => onRxSelect(p.id)}
                    className={`px-2 py-1 rounded cursor-pointer text-[11px] font-mono ${
                      selectedRxId === p.id
                        ? 'bg-blue-600/30 border border-blue-500/50'
                        : 'hover:bg-surface-3 border border-transparent'
                    }`}
                  >
                    <div className="flex items-center gap-2">
                      <span className="text-blue-400 font-bold w-6">RX{idx + 1}</span>
                      <span className="flex-1 text-gray-200 truncate">
                        {p.lat.toFixed(5)}, {p.lon.toFixed(5)}
                      </span>
                      <button
                        onClick={(e) => { e.stopPropagation(); onRxRemove(p.id); }}
                        className="opacity-50 hover:opacity-100 text-red-400"
                        title={i('rx.remove')}
                      >
                        <Trash2 className="w-3 h-3" />
                      </button>
                    </div>
                    {sig && (
                      <div className="ml-8 mt-0.5 flex gap-3 text-[10px]">
                        <span title="ITM only (model loss only)">
                          <span className="text-gray-500">ITM </span>
                          <span className={signalClass(sig.itm)}>{sig.itm.toFixed(1)} dBm</span>
                        </span>
                        <span title="With Fresnel/diffraction loss">
                          <span className="text-gray-500">F </span>
                          <span className={signalClass(sig.fresnel)}>{sig.fresnel.toFixed(1)} dBm</span>
                        </span>
                        {!sig.clear && <span className="text-orange-400">⚠</span>}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}

          <button
            onClick={() => setPlacementMode(placementMode === 'rx' ? null : 'rx')}
            className={`w-full flex items-center justify-center gap-1 px-2 py-1.5 rounded text-xs font-semibold border transition-colors ${
              placementMode === 'rx'
                ? 'bg-blue-600 border-blue-500 text-white'
                : 'bg-surface-3 border-gray-700 text-gray-200 hover:bg-surface-2'
            }`}
          >
            <MapPin className="w-3.5 h-3.5" />
            {placementMode === 'rx' ? i('rx.placing') : (rxPositions.length > 0 ? '+ ' + i('rx.place') : i('rx.place'))}
          </button>
        </div>
        <Field label={i('rx.height')} unit="m" help={i('help.rx.height')}>
          <NumberInput step="0.5" min="0.1" max="60000" className="input-field"
                 value={rx.height} fallback={1.5}
                 onChange={v => setRx({ ...rx, height: v })} />
        </Field>
        <Field label={i('rx.gain')} unit="dBi" help={i('help.rx.gain')}>
          <NumberInput step="0.5" min="-30" max="50" className="input-field"
                 value={rx.gain} fallback={0}
                 onChange={v => setRx({ ...rx, gain: v })} />
        </Field>
        <Field label={i('rx.sensitivity')} unit="dBm" help={i('help.rx.sensitivity')}>
          <NumberInput step="1" min="-200" max="0" className="input-field"
                 value={rx.sensitivity} fallback={-90}
                 onChange={v => setRx({ ...rx, sensitivity: v })} />
        </Field>
      </div>
    </>
  );
}

function ModelPanel({ model, setModel, i }: PanelProps) {
  const models = [
    { id: 'itm_ntia', label: 'model.itm_ntia' },
    { id: 'itm', label: 'model.itm' },
    { id: 'general_purpose', label: 'model.general_purpose' },
    { id: 'free_space', label: 'model.free_space' },
    { id: 'egli', label: 'model.egli' },
    { id: 'hata_urban', label: 'model.hata_urban' },
    { id: 'hata_suburban', label: 'model.hata_suburban' },
    { id: 'hata_open', label: 'model.hata_open' },
    { id: 'cost231', label: 'model.cost231' },
    { id: 'sui', label: 'model.sui' },
    { id: 'ericsson9999', label: 'model.ericsson9999' },
    { id: 'itu_p1812', label: 'model.itu_p1812' },
    { id: 'los', label: 'model.los' },
  ];

  return (
    <>
      <h3 className="section-title">{i('mdl.title')}</h3>
      <div className="space-y-3">
        <Field label={i('mdl.model')} help={i('help.mdl.model')}>
          <select className="select-field" value={model.name}
                  onChange={e => setModel({ ...model, name: e.target.value })}>
            {models.map(m => (
              <option key={m.id} value={m.id}>{i(m.label as any)}</option>
            ))}
          </select>
        </Field>
        <Field label={i('mdl.reliability')} unit="%" help={i('help.mdl.reliability')}>
          <div className="flex items-center gap-3">
            <input type="range" min="1" max="99" value={model.reliability}
                   onChange={e => setModel({ ...model, reliability: parseInt(e.target.value) })} />
            <span className="value-badge w-14 text-center">{model.reliability}%</span>
          </div>
        </Field>
        <Field label={i('mdl.diffraction')} help={i('help.mdl.diffraction')}>
          <select className="select-field" value={model.diffraction}
                  onChange={e => setModel({ ...model, diffraction: e.target.value })}>
            <option value="none">{i('mdl.diff_none')}</option>
            <option value="knife_edge">{i('mdl.diff_knife')}</option>
            <option value="bullington">{i('mdl.diff_bullington')}</option>
            <option value="deygout94">{i('mdl.diff_deygout')}</option>
          </select>
        </Field>
      </div>
    </>
  );
}

function EnvPanel({ env, setEnv, i }: PanelProps) {
  return (
    <>
      <h3 className="section-title">{i('env.title')}</h3>
      <div className="space-y-3">
        <Field label={i('env.elevation')} help={i('help.env.elevation')}>
          <select className="select-field" value={env.elevation_model}
                  onChange={e => setEnv({ ...env, elevation_model: e.target.value })}>
            <option value="dtm">{i('env.elevation_dtm')}</option>
            <option value="dsm">{i('env.elevation_dsm')}</option>
          </select>
        </Field>
        <Field label={i('env.noise_floor')} unit="dBm" help={i('help.env.noise')}>
          <NumberInput step="1" min="-174" max="0" className="input-field"
                 value={env.noise_floor} fallback={-100}
                 onChange={v => setEnv({ ...env, noise_floor: v })} />
        </Field>
      </div>
    </>
  );
}

function OutputPanel({ output, setOutput, megapixels, i, locale }: PanelProps) {
  return (
    <>
      <h3 className="section-title">{i('out.title')}</h3>
      <div className="space-y-3">
        <Field label={i('out.resolution')} unit="m" help={i('help.out.resolution')}>
          <select className="select-field" value={output.resolution}
                  onChange={e => setOutput({ ...output, resolution: parseInt(e.target.value) })}>
            <option value="2">2m</option>
            <option value="5">5m</option>
            <option value="10">10m</option>
            <option value="20">20m</option>
            <option value="30">30m</option>
            <option value="50">50m</option>
            <option value="100">100m</option>
            <option value="200">200m</option>
          </select>
        </Field>
        <Field label={i('out.radius')} unit="km" help={i('help.out.radius')}>
          <NumberInput step="1" min="0.1" max="500" className="input-field"
                 value={output.radius} fallback={10}
                 onChange={v => setOutput({ ...output, radius: v })} />
        </Field>
        <Field label={i('rx.units')} help={i('help.out.units')}>
          <select className="select-field" value={output.units}
                  onChange={e => setOutput({ ...output, units: e.target.value })}>
            <option value="dBm">{i('rx.unit_dbm')}</option>
            <option value="dB">{i('rx.unit_snr')}</option>
            <option value="dBuV">{i('rx.unit_dbuv')}</option>
          </select>
        </Field>
      </div>

      {/* Computed megapixels */}
      <div className="bg-surface-3 rounded-lg p-3 mt-4">
        <div className="flex justify-between text-xs">
          <span className="text-gray-400">{i('out.megapixels')}</span>
          <span className={`value-badge ${megapixels > 16 ? 'text-red-400' : megapixels > 4 ? 'text-yellow-400' : 'text-brand-400'}`}>
            {megapixels.toFixed(2)} MP
          </span>
        </div>
      </div>
    </>
  );
}
