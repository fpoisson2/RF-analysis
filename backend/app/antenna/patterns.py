"""
Antenna pattern generation and gain calculation.

Supports:
- Isotropic
- Half-wave dipole (V/H polarization)
- Custom pattern from beamwidth parameters
- Yagi approximation
- Sector/panel antenna
"""
import numpy as np
from typing import Tuple


def isotropic() -> np.ndarray:
    """Isotropic antenna - 0 dBi in all directions."""
    return np.zeros((361, 181), dtype=np.float32)


def dipole(polarization: str = "V", gain_dbi: float = 2.15) -> np.ndarray:
    """
    Half-wave dipole pattern.

    Args:
        polarization: "V" (vertical) or "H" (horizontal)
        gain_dbi: Peak gain in dBi (default: 2.15)

    Returns:
        2D array [azimuth 0-360][elevation -90 to +90] of gain in dBi
    """
    pattern = np.zeros((361, 181), dtype=np.float32)

    for az in range(361):
        for el in range(181):
            elev_rad = np.radians(el - 90)

            if polarization == "V":
                # Vertical dipole: omnidirectional in azimuth, null at zenith/nadir
                gain_factor = np.cos(elev_rad)
            else:
                # Horizontal dipole: figure-8 in azimuth
                az_rad = np.radians(az)
                gain_factor = np.cos(elev_rad) * abs(np.sin(az_rad))

            gain_factor = max(gain_factor, 0.001)  # Avoid -inf
            pattern[az, el] = gain_dbi + 20 * np.log10(gain_factor)

    return pattern


def custom_pattern(h_beamwidth: float = 360, v_beamwidth: float = 90,
                    gain_dbi: float = 2.15, front_to_back: float = 15) -> np.ndarray:
    """
    Generate custom antenna pattern from beamwidth parameters.

    Uses Gaussian beam approximation.

    Args:
        h_beamwidth: Horizontal -3dB beamwidth in degrees
        v_beamwidth: Vertical -3dB beamwidth in degrees
        gain_dbi: Peak gain in dBi
        front_to_back: Front-to-back ratio in dB

    Returns:
        2D pattern array [azimuth 0-360][elevation -90 to +90]
    """
    pattern = np.zeros((361, 181), dtype=np.float32)

    # Gaussian beam shape: G = G0 * exp(-2.773 * (theta/bw)^2)
    # -3dB at theta = bw/2

    h_sigma = h_beamwidth / (2.0 * np.sqrt(2.0 * np.log(2.0))) if h_beamwidth < 360 else 9999
    v_sigma = v_beamwidth / (2.0 * np.sqrt(2.0 * np.log(2.0)))

    for az in range(361):
        for el in range(181):
            elev = el - 90  # -90 to +90

            # Horizontal angle relative to boresight (0 degrees)
            h_angle = az if az <= 180 else 360 - az

            # Gaussian roll-off
            if h_beamwidth >= 360:
                h_atten = 0.0  # Omnidirectional
            else:
                h_atten = 2.773 * (h_angle / (h_beamwidth / 2.0)) ** 2
                h_atten = min(h_atten, front_to_back)

            v_atten = 2.773 * (elev / (v_beamwidth / 2.0)) ** 2
            v_atten = min(v_atten, 30.0)

            pattern[az, el] = gain_dbi - h_atten - v_atten

    return pattern


def sector_panel(h_beamwidth: float = 120, v_beamwidth: float = 30,
                  gain_dbi: float = 15, front_to_back: float = 25) -> np.ndarray:
    """Typical cellular sector panel antenna."""
    return custom_pattern(h_beamwidth, v_beamwidth, gain_dbi, front_to_back)


def yagi(num_elements: int = 5, gain_dbi: float = 10) -> np.ndarray:
    """
    Approximate Yagi-Uda antenna pattern.
    Beamwidth estimated from number of elements.
    """
    # Approximate beamwidth from element count
    h_bw = max(20, 180 / num_elements)
    v_bw = h_bw * 1.2  # Slightly wider vertical
    f2b = 10 + 3 * num_elements  # F/B improves with elements
    return custom_pattern(h_bw, v_bw, gain_dbi, f2b)


# ═══════════════════════════════════════════════════════════════
# Gain lookup with antenna orientation
# ═══════════════════════════════════════════════════════════════

def get_antenna_gain(pattern: np.ndarray, azimuth_deg: float, elevation_deg: float,
                      antenna_azimuth: float = 0, antenna_tilt: float = 0) -> float:
    """
    Get antenna gain at a specific direction, considering antenna orientation.

    Args:
        pattern: 2D pattern array [361 x 181]
        azimuth_deg: Direction azimuth (0-360, true north)
        elevation_deg: Direction elevation (-90 to +90)
        antenna_azimuth: Antenna pointing azimuth (0-360)
        antenna_tilt: Antenna downtilt (positive = toward ground)

    Returns:
        Gain in dBi
    """
    # Relative azimuth (direction relative to antenna boresight)
    rel_az = (azimuth_deg - antenna_azimuth + 360) % 360

    # Relative elevation (adjusted for tilt)
    rel_el = elevation_deg + antenna_tilt

    # Clamp and lookup
    az_idx = int(round(rel_az)) % 361
    el_idx = int(round(rel_el + 90))
    el_idx = max(0, min(180, el_idx))

    return float(pattern[az_idx, el_idx])


def get_pattern_by_type(pattern_type: str, **kwargs) -> np.ndarray:
    """Get an antenna pattern by type name."""
    patterns = {
        "isotropic": isotropic,
        "dipole": dipole,
        "custom": custom_pattern,
        "sector": sector_panel,
        "yagi": yagi,
    }
    fn = patterns.get(pattern_type, dipole)
    return fn(**{k: v for k, v in kwargs.items() if k in fn.__code__.co_varnames})
