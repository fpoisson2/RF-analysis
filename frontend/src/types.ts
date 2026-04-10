export interface Transmitter {
  lat: number;
  lon: number;
  height: number;
  name: string;
  network: string;
}

export interface Signal {
  frequency: number;
  power: number;
  bandwidth: number;
}

export interface Feeder {
  loss: number;
}

export interface Antenna {
  gain: number;
  azimuth: number;
  tilt: number;
  h_beamwidth: number;
  v_beamwidth: number;
  pattern_type: string;
  polarization: string;  // "V" (vertical), "H" (horizontal)
}

export interface Receiver {
  lat: number | null;
  lon: number | null;
  height: number;
  gain: number;
  sensitivity: number;
}

export interface PropagationModel {
  name: string;
  reliability: number;
  diffraction: string;
}

export interface Environment {
  elevation_model: string;
  noise_floor: number;
}

export interface OutputConfig {
  resolution: number;
  radius: number;
  units: string;
  color_schema: string;
}

export interface AreaRequest {
  transmitter: Transmitter;
  signal: Signal;
  feeder: Feeder;
  antenna: Antenna;
  receiver: Receiver;
  model: PropagationModel;
  environment: Environment;
  output: OutputConfig;
}

export interface AreaResponse {
  image_url: string;
  bounds: { north: number; south: number; east: number; west: number };
  stats: Record<string, any>;
  erp_w: number;
  erp_dbm: number;
  eirp_w: number;
  eirp_dbm: number;
  computation_time_ms: number;
}

export interface PathResponse {
  distances: number[];
  elevations: number[];
  signal_levels: number[];
  fresnel_clearance: number[];
  los_clearance: number[];
  stats: Record<string, any>;
}

export type TabId = 'tx' | 'signal' | 'antenna' | 'rx' | 'model' | 'environment' | 'output';
