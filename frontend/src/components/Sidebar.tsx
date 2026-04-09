import React from 'react';
import {
  Radio, Signal, Antenna, Smartphone, Globe, TreePine, Settings,
  Play, Loader2, ChevronLeft, ChevronRight,
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
}

function Field({ label, unit, children }: { label: string; unit?: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="flex items-baseline justify-between mb-1">
        <label className="label-text">{label}</label>
        {unit && <span className="text-[10px] text-gray-500">{unit}</span>}
      </div>
      {children}
    </div>
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

function TxPanel({ tx, setTx, i }: PanelProps) {
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
        <div className="panel-section">
          <div className="label-text mb-2">{i('tx.coordinates')}</div>
          <div className="grid grid-cols-2 gap-3">
            <Field label={i('tx.latitude')} unit="D.D">
              <input type="number" step="0.000001" className="input-field font-mono"
                     value={tx.lat} onChange={e => setTx({ ...tx, lat: parseFloat(e.target.value) || 0 })} />
            </Field>
            <Field label={i('tx.longitude')} unit="D.D">
              <input type="number" step="0.000001" className="input-field font-mono"
                     value={tx.lon} onChange={e => setTx({ ...tx, lon: parseFloat(e.target.value) || 0 })} />
            </Field>
          </div>
        </div>
        <Field label={i('tx.height')} unit={i('tx.height_unit')}>
          <input type="number" step="1" min="0.1" max="60000" className="input-field"
                 value={tx.height} onChange={e => setTx({ ...tx, height: parseFloat(e.target.value) || 1 })} />
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
        <Field label={i('sig.frequency')} unit="MHz">
          <input type="number" step="0.1" min="2" max="90000" className="input-field"
                 value={signal.frequency} onChange={e => setSignal({ ...signal, frequency: parseFloat(e.target.value) || 155 })} />
        </Field>
        <Field label={i('sig.power')} unit="W">
          <input type="number" step="0.1" min="0.001" max="10000" className="input-field"
                 value={signal.power} onChange={e => setSignal({ ...signal, power: parseFloat(e.target.value) || 1 })} />
        </Field>
        <Field label={i('sig.bandwidth')} unit="MHz">
          <input type="number" step="0.01" min="0.001" max="200" className="input-field"
                 value={signal.bandwidth} onChange={e => setSignal({ ...signal, bandwidth: parseFloat(e.target.value) || 0.25 })} />
        </Field>
      </div>

      <div className="panel-section mt-4">
        <div className="label-text mb-2">{i('feed.title')}</div>
        <Field label={i('feed.loss')} unit="dB">
          <input type="number" step="0.1" min="0" max="30" className="input-field"
                 value={feeder.loss} onChange={e => setFeeder({ loss: parseFloat(e.target.value) || 0 })} />
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

function AntennaPanel({ antenna, setAntenna, i }: PanelProps) {
  return (
    <>
      <h3 className="section-title">{i('ant.title')}</h3>
      <div className="space-y-3">
        <Field label={i('ant.pattern')}>
          <select className="select-field" value={antenna.pattern_type}
                  onChange={e => setAntenna({ ...antenna, pattern_type: e.target.value })}>
            <option value="dipole">{i('ant.pattern_dipole')}</option>
            <option value="isotropic">{i('ant.pattern_isotropic')}</option>
            <option value="custom">{i('ant.pattern_custom')}</option>
            <option value="sector">{i('ant.pattern_sector')}</option>
            <option value="yagi">{i('ant.pattern_yagi')}</option>
          </select>
        </Field>
        <Field label={i('ant.gain')} unit="dBi">
          <input type="number" step="0.1" min="-30" max="50" className="input-field"
                 value={antenna.gain} onChange={e => setAntenna({ ...antenna, gain: parseFloat(e.target.value) || 0 })} />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label={i('ant.azimuth')} unit="deg">
            <input type="number" step="1" min="0" max="360" className="input-field"
                   value={antenna.azimuth} onChange={e => setAntenna({ ...antenna, azimuth: parseFloat(e.target.value) || 0 })} />
          </Field>
          <Field label={i('ant.tilt')} unit="deg">
            <input type="number" step="0.5" min="-90" max="90" className="input-field"
                   value={antenna.tilt} onChange={e => setAntenna({ ...antenna, tilt: parseFloat(e.target.value) || 0 })} />
          </Field>
        </div>
        {antenna.pattern_type === 'custom' && (
          <div className="grid grid-cols-2 gap-3">
            <Field label={i('ant.h_beamwidth')} unit="deg">
              <input type="number" step="1" min="1" max="360" className="input-field"
                     value={antenna.h_beamwidth} onChange={e => setAntenna({ ...antenna, h_beamwidth: parseFloat(e.target.value) || 360 })} />
            </Field>
            <Field label={i('ant.v_beamwidth')} unit="deg">
              <input type="number" step="1" min="1" max="180" className="input-field"
                     value={antenna.v_beamwidth} onChange={e => setAntenna({ ...antenna, v_beamwidth: parseFloat(e.target.value) || 90 })} />
            </Field>
          </div>
        )}
      </div>
    </>
  );
}

function RxPanel({ rx, setRx, i }: PanelProps) {
  return (
    <>
      <h3 className="section-title">{i('rx.title')}</h3>
      <div className="space-y-3">
        <Field label={i('rx.height')} unit="m">
          <input type="number" step="0.5" min="0.1" max="60000" className="input-field"
                 value={rx.height} onChange={e => setRx({ ...rx, height: parseFloat(e.target.value) || 1.5 })} />
        </Field>
        <Field label={i('rx.gain')} unit="dBi">
          <input type="number" step="0.5" min="-30" max="50" className="input-field"
                 value={rx.gain} onChange={e => setRx({ ...rx, gain: parseFloat(e.target.value) || 0 })} />
        </Field>
        <Field label={i('rx.sensitivity')} unit="dBm">
          <input type="number" step="1" min="-200" max="0" className="input-field"
                 value={rx.sensitivity} onChange={e => setRx({ ...rx, sensitivity: parseFloat(e.target.value) || -90 })} />
        </Field>
      </div>
    </>
  );
}

function ModelPanel({ model, setModel, i }: PanelProps) {
  const models = [
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
        <Field label={i('mdl.model')}>
          <select className="select-field" value={model.name}
                  onChange={e => setModel({ ...model, name: e.target.value })}>
            {models.map(m => (
              <option key={m.id} value={m.id}>{i(m.label as any)}</option>
            ))}
          </select>
        </Field>
        <Field label={i('mdl.reliability')} unit="%">
          <div className="flex items-center gap-3">
            <input type="range" min="1" max="99" value={model.reliability}
                   onChange={e => setModel({ ...model, reliability: parseInt(e.target.value) })} />
            <span className="value-badge w-14 text-center">{model.reliability}%</span>
          </div>
        </Field>
        <Field label={i('mdl.diffraction')}>
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
        <Field label={i('env.elevation')}>
          <select className="select-field" value={env.elevation_model}
                  onChange={e => setEnv({ ...env, elevation_model: e.target.value })}>
            <option value="dtm">{i('env.elevation_dtm')}</option>
            <option value="dsm">{i('env.elevation_dsm')}</option>
          </select>
        </Field>
        <Field label={i('env.noise_floor')} unit="dBm">
          <input type="number" step="1" min="-174" max="0" className="input-field"
                 value={env.noise_floor} onChange={e => setEnv({ ...env, noise_floor: parseFloat(e.target.value) || -100 })} />
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
        <Field label={i('out.resolution')} unit="m">
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
        <Field label={i('out.radius')} unit="km">
          <input type="number" step="1" min="0.1" max="500" className="input-field"
                 value={output.radius} onChange={e => setOutput({ ...output, radius: parseFloat(e.target.value) || 10 })} />
        </Field>
        <Field label={i('rx.units')}>
          <select className="select-field" value={output.units}
                  onChange={e => setOutput({ ...output, units: e.target.value })}>
            <option value="dBm">{i('rx.unit_dbm')}</option>
            <option value="dB">{i('rx.unit_snr')}</option>
            <option value="dBuV">{i('rx.unit_dbuv')}</option>
          </select>
        </Field>
      </div>

      {/* Color schema */}
      <Field label={i('out.color_schema')}>
        <select className="select-field" value={output.color_schema}
                onChange={e => setOutput({ ...output, color_schema: e.target.value })}>
          <option value="signal_strength">{locale === 'fr' ? 'Force du signal' : 'Signal Strength'}</option>
          <option value="snr">{locale === 'fr' ? 'Rapport S/B' : 'SNR'}</option>
          <option value="path_loss">{locale === 'fr' ? 'Affaiblissement' : 'Path Loss'}</option>
        </select>
      </Field>

      {/* Color preview - gradient with 5dB steps */}
      <div className="mt-3">
        <div className="label-text mb-1">{locale === 'fr' ? 'Aperçu couleurs (pas de 5 dB)' : 'Color Preview (5 dB steps)'}</div>
        <div className="h-4 rounded-md overflow-hidden flex">
          {['#003c00','#006400','#008c00','#00b400','#00d200','#50dc00',
            '#a0e600','#d2e600','#ffe600','#ffc800','#ffa500','#ff7800',
            '#ff5000','#ff2800','#e60000','#c80028','#aa0050','#8c0078',
            '#640088','#460082','#320064'].map((c, i) => (
            <div key={i} className="flex-1" style={{ background: c }} />
          ))}
        </div>
        <div className="flex justify-between text-[9px] text-gray-500 mt-0.5 font-mono">
          <span>-30 dBm</span>
          <span>-80</span>
          <span>-130 dBm</span>
        </div>
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
