"""Pydantic schemas for the RF Planner API."""
from pydantic import BaseModel, Field
from typing import Optional


class Transmitter(BaseModel):
    lat: float = Field(default=46.83035, ge=-90, le=90)
    lon: float = Field(default=-71.227008, ge=-180, le=180)
    height: float = Field(default=30, ge=0.1, le=60000, description="Height AGL in meters")
    name: str = Field(default="Site")
    network: str = Field(default="My Network")


class Signal(BaseModel):
    frequency: float = Field(default=155, ge=2, le=90000, description="MHz")
    power: float = Field(default=5, ge=0.001, le=10000, description="Watts")
    bandwidth: float = Field(default=0.25, ge=0.001, le=200, description="MHz")


class Feeder(BaseModel):
    loss: float = Field(default=3, ge=0, le=30, description="Total feeder loss in dB")


class Antenna(BaseModel):
    gain: float = Field(default=2.15, ge=-30, le=50, description="dBi")
    azimuth: float = Field(default=0, ge=0, le=360)
    tilt: float = Field(default=0, ge=-90, le=90)
    h_beamwidth: float = Field(default=360, ge=1, le=360)
    v_beamwidth: float = Field(default=90, ge=1, le=180)
    pattern_type: str = Field(default="dipole")


class Receiver(BaseModel):
    lat: Optional[float] = None
    lon: Optional[float] = None
    height: float = Field(default=1.5, ge=0.1, le=60000)
    gain: float = Field(default=2, ge=-30, le=50, description="dBi")
    sensitivity: float = Field(default=-90, ge=-200, le=0)


class PropagationModel(BaseModel):
    name: str = Field(default="itm")
    reliability: float = Field(default=50, ge=1, le=99)
    diffraction: str = Field(default="deygout94")


class Environment(BaseModel):
    elevation_model: str = Field(default="dtm")
    noise_floor: float = Field(default=-100, description="dBm")


class OutputConfig(BaseModel):
    resolution: float = Field(default=30, ge=1, le=1000, description="meters")
    radius: float = Field(default=10, ge=0.1, le=500, description="km")
    units: str = Field(default="dBm")
    color_schema: str = Field(default="signal_strength")


class AreaRequest(BaseModel):
    transmitter: Transmitter = Field(default_factory=Transmitter)
    signal: Signal = Field(default_factory=Signal)
    feeder: Feeder = Field(default_factory=Feeder)
    antenna: Antenna = Field(default_factory=Antenna)
    receiver: Receiver = Field(default_factory=Receiver)
    model: PropagationModel = Field(default_factory=PropagationModel)
    environment: Environment = Field(default_factory=Environment)
    output: OutputConfig = Field(default_factory=OutputConfig)


class PathRequest(BaseModel):
    transmitter: Transmitter = Field(default_factory=Transmitter)
    receiver: Receiver = Field(default_factory=Receiver)
    signal: Signal = Field(default_factory=Signal)
    feeder: Feeder = Field(default_factory=Feeder)
    antenna: Antenna = Field(default_factory=Antenna)
    model: PropagationModel = Field(default_factory=PropagationModel)
    environment: Environment = Field(default_factory=Environment)


class AreaResponse(BaseModel):
    image_url: str
    bounds: dict
    stats: dict
    erp_w: float
    erp_dbm: float
    eirp_w: float
    eirp_dbm: float
    computation_time_ms: float


class PathObstruction(BaseModel):
    type: str                    # "los" or "fresnel"
    start_m: float
    end_m: float
    peak_m: float
    peak_elevation: float
    penetration_m: float
    canopy_height: float
    obstruction_pct: float = 0.0


class PathResponse(BaseModel):
    distances: list[float]
    elevations: list[float]                  # alias for ground_elevations
    ground_elevations: list[float] = []
    surface_elevations: list[float] = []     # ground + canopy/buildings (MHC)
    surface_detect: list[float] = []         # max surface within Fresnel cross-section
    fresnel_obstruction_pct: list[float] = [] # % of Fresnel zone area obstructed, per sample
    canopy_heights: list[float] = []
    los_line: list[float] = []
    fresnel_radius: list[float] = []
    signal_levels: list[float]
    path_loss: list[float] = []
    fresnel_clearance: list[float]
    los_clearance: list[float]
    obstructions: list[PathObstruction] = []
    stats: dict
