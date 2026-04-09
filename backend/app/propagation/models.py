"""
RF Propagation Models.

All models return path loss in dB (positive number).
All functions accept numpy arrays for vectorized computation.

Models implemented:
1. Free Space (ITU-R P.525 / Friis)
2. Egli (VHF/UHF, 2-1500 MHz)
3. Okumura-Hata (Urban/Suburban/Open, 150-1500 MHz)
4. COST-231 Hata (150-2000 MHz)
5. SUI (Stanford University Interim, 1900-11000 MHz)
6. Ericsson 9999 (150-1900 MHz)
7. ITU-R P.1812 (simplified, 30-6000 MHz)
8. Egli VHF/UHF
9. Longley-Rice ITM (Irregular Terrain Model)
10. Line of Sight
11. Free Space + Terrain
"""
import numpy as np
from typing import Optional


# Speed of light
C = 299792458.0  # m/s


def _wavelength(freq_mhz: float) -> float:
    """Wavelength in meters."""
    return C / (freq_mhz * 1e6)


# ══════════════════════════════════════════════════════════════════════
# 1. FREE SPACE PATH LOSS (ITU-R P.525)
# ══════════════════════════════════════════════════════════════════════

def free_space(d_km, freq_mhz, tx_h=None, rx_h=None, **kw):
    """
    Free space path loss (Friis equation).
    FSPL = 32.44 + 20*log10(f_MHz) + 20*log10(d_km)
    Valid: all frequencies, reference model.
    """
    d_km = np.maximum(np.asarray(d_km, dtype=float), 0.001)
    return 32.44 + 20.0 * np.log10(freq_mhz) + 20.0 * np.log10(d_km)


# ══════════════════════════════════════════════════════════════════════
# 2. EGLI MODEL (VHF/UHF general purpose, 2-1500 MHz)
# ══════════════════════════════════════════════════════════════════════

def egli(d_km, freq_mhz, tx_h=30.0, rx_h=1.5, **kw):
    """
    Egli propagation model.
    Good for VHF/UHF over irregular terrain.
    Valid: 2-1500 MHz
    """
    d_km = np.maximum(np.asarray(d_km, dtype=float), 0.001)
    tx_h = max(tx_h, 1.0)
    rx_h = max(rx_h, 1.0)

    # Egli median path loss
    loss = (88.0
            + 40.0 * np.log10(d_km)
            + 20.0 * np.log10(freq_mhz)
            - 20.0 * np.log10(tx_h)
            - 20.0 * np.log10(rx_h))
    return loss


# ══════════════════════════════════════════════════════════════════════
# 3. OKUMURA-HATA (Cellular, 150-1500 MHz)
# ══════════════════════════════════════════════════════════════════════

def _hata_correction_factor(freq_mhz: float, rx_h: float, city_size: str = "medium") -> float:
    """Mobile antenna correction factor for Hata model."""
    if city_size == "large" and freq_mhz >= 400:
        return 3.2 * (np.log10(11.75 * rx_h)) ** 2 - 4.97
    else:
        return (1.1 * np.log10(freq_mhz) - 0.7) * rx_h - (1.56 * np.log10(freq_mhz) - 0.8)


def hata_urban(d_km, freq_mhz, tx_h=30.0, rx_h=1.5, city_size="medium", **kw):
    """
    Okumura-Hata urban model.
    Valid: 150-1500 MHz, tx_h: 30-200m, rx_h: 1-10m, d: 1-20km
    """
    d_km = np.maximum(np.asarray(d_km, dtype=float), 0.001)
    tx_h = max(tx_h, 30.0)
    rx_h = max(rx_h, 1.0)
    freq_mhz = np.clip(freq_mhz, 150, 1500)

    a_hm = _hata_correction_factor(freq_mhz, rx_h, city_size)

    loss = (69.55
            + 26.16 * np.log10(freq_mhz)
            - 13.82 * np.log10(tx_h)
            - a_hm
            + (44.9 - 6.55 * np.log10(tx_h)) * np.log10(d_km))
    return loss


def hata_suburban(d_km, freq_mhz, tx_h=30.0, rx_h=1.5, **kw):
    """Okumura-Hata suburban model."""
    urban = hata_urban(d_km, freq_mhz, tx_h, rx_h)
    correction = 2.0 * (np.log10(freq_mhz / 28.0)) ** 2 + 5.4
    return urban - correction


def hata_open(d_km, freq_mhz, tx_h=30.0, rx_h=1.5, **kw):
    """Okumura-Hata open area model."""
    urban = hata_urban(d_km, freq_mhz, tx_h, rx_h)
    correction = (4.78 * (np.log10(freq_mhz)) ** 2
                  - 18.33 * np.log10(freq_mhz) + 40.94)
    return urban - correction


# ══════════════════════════════════════════════════════════════════════
# 4. COST-231 HATA (150-2000 MHz)
# ══════════════════════════════════════════════════════════════════════

def cost231(d_km, freq_mhz, tx_h=30.0, rx_h=1.5, environment="urban", **kw):
    """
    COST-231 Hata model (extension of Hata to 2000 MHz).
    Valid: 150-2000 MHz, tx_h: 30-200m, rx_h: 1-10m
    """
    d_km = np.maximum(np.asarray(d_km, dtype=float), 0.001)
    tx_h = max(tx_h, 30.0)
    rx_h = max(rx_h, 1.0)
    freq_mhz = np.clip(freq_mhz, 150, 2000)

    a_hm = _hata_correction_factor(freq_mhz, rx_h)
    cm = 3.0 if environment == "urban" else 0.0  # Metropolitan correction

    loss = (46.3
            + 33.9 * np.log10(freq_mhz)
            - 13.82 * np.log10(tx_h)
            - a_hm
            + (44.9 - 6.55 * np.log10(tx_h)) * np.log10(d_km)
            + cm)
    return loss


# ══════════════════════════════════════════════════════════════════════
# 5. SUI MODEL (Stanford University Interim, 1900-11000 MHz)
# ══════════════════════════════════════════════════════════════════════

def sui(d_km, freq_mhz, tx_h=30.0, rx_h=1.5, terrain_type="B", **kw):
    """
    SUI (Stanford University Interim) microwave model.
    Valid: 1900-11000 MHz, tx_h > 10m
    Terrain types: A (hilly/heavy tree), B (moderate), C (flat/light tree)
    """
    d_km = np.maximum(np.asarray(d_km, dtype=float), 0.001)
    tx_h = max(tx_h, 10.0)
    rx_h = max(rx_h, 1.0)

    # SUI parameters by terrain type
    params = {
        "A": {"a": 4.6, "b": 0.0075, "c": 12.6, "s": 10.6, "mu": 0.64},
        "B": {"a": 4.0, "b": 0.0065, "c": 17.1, "s": 9.6, "mu": 0.75},
        "C": {"a": 3.6, "b": 0.005, "c": 20.0, "s": 8.2, "mu": 0.59},
    }
    p = params.get(terrain_type, params["B"])

    # Path loss exponent
    d0 = 0.1  # 100m reference
    gamma = p["a"] - p["b"] * tx_h + p["c"] / tx_h

    # Frequency correction (reference: 2000 MHz)
    x_f = 6.0 * np.log10(freq_mhz / 2000.0)

    # Receiver height correction
    x_h = -10.8 * np.log10(rx_h / 2.0) if terrain_type in ("A", "B") else -20.0 * np.log10(rx_h / 2.0)

    # Path loss
    A = 20.0 * np.log10(4.0 * np.pi * d0 * 1000.0 / _wavelength(freq_mhz))
    loss = A + 10.0 * gamma * np.log10(d_km / d0) + x_f + x_h + p["s"]
    return loss


# ══════════════════════════════════════════════════════════════════════
# 6. ERICSSON 9999 (150-1900 MHz)
# ══════════════════════════════════════════════════════════════════════

def ericsson9999(d_km, freq_mhz, tx_h=30.0, rx_h=1.5, **kw):
    """
    Ericsson 9999 model.
    Valid: 150-1900 MHz
    """
    d_km = np.maximum(np.asarray(d_km, dtype=float), 0.001)
    tx_h = max(tx_h, 3.0)
    rx_h = max(rx_h, 1.0)

    a0 = 36.2
    a1 = 30.2
    a2 = -12.0
    a3 = 0.1

    g_f = 44.49 * np.log10(freq_mhz) - 4.78 * (np.log10(freq_mhz)) ** 2

    loss = (a0 + a1 * np.log10(d_km) + a2 * np.log10(tx_h)
            + a3 * np.log10(tx_h) * np.log10(d_km) - 3.2 * (np.log10(11.75 * rx_h)) ** 2
            + g_f + 44.49)
    return loss


# ══════════════════════════════════════════════════════════════════════
# 7. ITU-R P.1812 (simplified, 30-6000 MHz)
# ══════════════════════════════════════════════════════════════════════

def itu_p1812(d_km, freq_mhz, tx_h=30.0, rx_h=1.5, **kw):
    """
    Simplified ITU-R P.1812 model for terrestrial paths.
    Valid: 30-6000 MHz
    This is a simplified version - full P.1812 requires terrain profile.
    """
    d_km = np.maximum(np.asarray(d_km, dtype=float), 0.001)

    # Free space base
    fspl = free_space(d_km, freq_mhz)

    # Additional loss factors (simplified)
    # Diffraction loss approximation based on earth curvature
    ae = 8500.0  # Effective earth radius in km (4/3 earth)
    d_los = 3.57 * (np.sqrt(tx_h) + np.sqrt(rx_h))  # LOS distance in km

    extra_loss = np.where(
        d_km <= d_los,
        0.0,  # Within LOS
        20.0 * np.log10(d_km / d_los) + 10.0 * (d_km - d_los) / d_los
    )

    return fspl + extra_loss


# ══════════════════════════════════════════════════════════════════════
# 8. LONGLEY-RICE ITM (Irregular Terrain Model)
# ══════════════════════════════════════════════════════════════════════

def itm(d_km, freq_mhz, tx_h=30.0, rx_h=1.5,
        terrain_profile=None, reliability=50, context="average", **kw):
    """
    Longley-Rice Irregular Terrain Model (ITM).

    This implements the point-to-point mode of ITM.
    For area mode (without terrain profile), uses statistical terrain parameters.

    Args:
        d_km: Distance(s) in km
        freq_mhz: Frequency in MHz (2-20000)
        tx_h: Transmitter height AGL in meters
        rx_h: Receiver height AGL in meters
        terrain_profile: Optional terrain elevation profile (array of heights in m)
        reliability: Time/location/situation reliability percentage (1-99)
        context: "conservative", "average", or "optimistic"
    """
    d_km = np.maximum(np.asarray(d_km, dtype=float), 0.001)
    d_m = d_km * 1000.0

    # Effective earth radius (4/3 model for standard atmosphere)
    RE = 6371000.0  # Earth radius in meters
    K = 4.0 / 3.0  # Effective earth radius factor
    AE = RE * K

    # Wavelength
    wl = _wavelength(freq_mhz)
    k = 2.0 * np.pi / wl  # Wave number

    # ── Free space reference loss ──
    fspl = free_space(d_km, freq_mhz)

    if terrain_profile is not None and len(terrain_profile) > 2:
        # ── Point-to-point mode with terrain ──
        return _itm_p2p(d_km, freq_mhz, tx_h, rx_h, terrain_profile,
                        reliability, context, AE, wl, k, fspl)
    else:
        # ── Area mode (statistical) ──
        return _itm_area(d_km, freq_mhz, tx_h, rx_h,
                         reliability, context, AE, wl, k, fspl)


def _itm_p2p(d_km, freq_mhz, tx_h, rx_h, profile, reliability, context, AE, wl, k, fspl):
    """ITM point-to-point mode with terrain profile."""
    d_m = np.atleast_1d(d_km * 1000.0)
    n_points = len(profile)
    profile = np.asarray(profile, dtype=float)

    # For single distance with full profile
    if d_m.size == 1:
        d_total = float(d_m[0])
        step = d_total / (n_points - 1) if n_points > 1 else d_total

        # TX and RX effective heights
        tx_elev = profile[0] + tx_h
        rx_elev = profile[-1] + rx_h

        # Line of sight between TX and RX
        los_heights = np.linspace(tx_elev, rx_elev, n_points)

        # Earth curvature correction
        distances = np.linspace(0, d_total, n_points)
        earth_curve = distances * (d_total - distances) / (2.0 * AE)
        effective_profile = profile + earth_curve

        # Find obstacles above LOS
        clearance = los_heights - effective_profile
        min_clearance = np.min(clearance[1:-1]) if n_points > 2 else 100.0

        # First Fresnel zone radius at each point
        fresnel1 = np.sqrt(wl * distances * (d_total - distances) / d_total)
        fresnel1[0] = 0
        fresnel1[-1] = 0

        # Normalized clearance (relative to Fresnel zone)
        with np.errstate(divide='ignore', invalid='ignore'):
            norm_clearance = np.where(fresnel1 > 0, clearance / fresnel1, 100.0)

        min_norm = np.min(norm_clearance[1:-1]) if n_points > 2 else 100.0

        # Diffraction loss
        if min_norm > 1.0:
            # Clear LOS with Fresnel clearance
            diff_loss = 0.0
        elif min_norm > -0.5:
            # Partial Fresnel blockage
            v = -min_norm * np.sqrt(2)
            diff_loss = 6.02 + 9.11 * v - 1.27 * v * v
            diff_loss = max(0, diff_loss)
        else:
            # Significant obstruction - use knife-edge
            v = -min_norm * np.sqrt(2)
            diff_loss = 6.02 + 9.11 * v - 1.27 * v * v
            diff_loss = max(0, min(diff_loss, 30))

        # Terrain irregularity factor
        dh = np.std(profile) if n_points > 2 else 0
        terrain_factor = 0.0
        if dh > 10:
            terrain_factor = min(10.0, 2.0 * np.log10(dh / 10.0))

        # Reliability adjustment
        reliability_margin = _reliability_margin(reliability)

        # Context adjustment
        context_adj = {"conservative": 3.0, "average": 0.0, "optimistic": -3.0}
        ctx_margin = context_adj.get(context, 0.0)

        total_loss = fspl + diff_loss + terrain_factor + reliability_margin + ctx_margin
        return total_loss
    else:
        # Multiple distances - compute for each
        # Use interpolated profiles for each distance
        results = np.zeros_like(d_m)
        for i, d in enumerate(d_m):
            if d <= 0.001:
                results[i] = 0
                continue
            # Interpolate profile to this distance
            n_interp = min(n_points, max(10, int(d / 30)))
            profile_distances = np.linspace(0, float(d), n_interp)
            full_distances = np.linspace(0, d_m.max(), n_points)
            interp_profile = np.interp(profile_distances, full_distances, profile)
            results[i] = float(_itm_p2p(
                np.array([d / 1000.0]), freq_mhz, tx_h, rx_h,
                interp_profile, reliability, context, AE, wl, k,
                free_space(d / 1000.0, freq_mhz)
            ))
        return results


def _itm_area(d_km, freq_mhz, tx_h, rx_h, reliability, context, AE, wl, k, fspl):
    """ITM area mode (statistical terrain parameters)."""
    d_km = np.asarray(d_km, dtype=float)

    # Terrain irregularity parameter (default: rolling hills)
    context_dh = {"conservative": 120, "average": 80, "optimistic": 30}
    dh = context_dh.get(context, 80)

    # Effective antenna heights considering terrain
    he_tx = tx_h
    he_rx = rx_h

    # LOS distance (radio horizon)
    d_los = 3.57 * (np.sqrt(he_tx) + np.sqrt(he_rx))

    # Two-ray ground reflection distance
    d_bp = 4.0 * he_tx * he_rx / wl  # Breakpoint distance in meters
    d_bp_km = d_bp / 1000.0

    # Beyond-horizon diffraction loss
    excess = np.maximum(d_km - d_los, 0)
    diff_loss = np.where(
        d_km <= d_los,
        0.0,
        np.minimum(
            6.0 + 12.0 * np.log10(excess / d_los + 1) + 0.1 * dh * np.sqrt(excess / d_los),
            40.0
        )
    )

    # Tropospheric scatter (very long distances)
    tropo_loss = np.where(
        d_km > 100,
        0.05 * (d_km - 100),
        0.0
    )

    # Terrain clutter loss
    clutter = np.minimum(5.0 * np.log10(1 + dh / 50.0), 15.0)

    # Reliability margin
    rel_margin = _reliability_margin(reliability)

    total = fspl + diff_loss + tropo_loss + clutter + rel_margin
    return total


def _reliability_margin(reliability: float) -> float:
    """Convert reliability percentage to dB margin."""
    if reliability <= 50:
        return 0.0
    # Approximate inverse normal distribution
    p = reliability / 100.0
    # Using approximation for z-score
    t = np.sqrt(-2.0 * np.log(1.0 - p))
    z = t - (2.515517 + 0.802853 * t + 0.010328 * t * t) / \
        (1.0 + 1.432788 * t + 0.189269 * t * t + 0.001308 * t * t * t)
    return float(z * 3.0)  # ~3dB per sigma


# ══════════════════════════════════════════════════════════════════════
# 9. LINE OF SIGHT
# ══════════════════════════════════════════════════════════════════════

def line_of_sight(d_km, freq_mhz, tx_h=30.0, rx_h=1.5, terrain_profile=None, **kw):
    """
    Line of sight / viewshed model.
    Returns 0 dB if LOS exists, very high loss if obstructed.
    """
    if terrain_profile is None:
        # Without terrain, use free space + earth curvature
        d_los = 3.57 * (np.sqrt(tx_h) + np.sqrt(rx_h))
        d_km = np.asarray(d_km, dtype=float)
        return np.where(d_km <= d_los, free_space(d_km, freq_mhz), 999.0)

    d_km = np.atleast_1d(np.asarray(d_km, dtype=float))
    profile = np.asarray(terrain_profile, dtype=float)
    n = len(profile)

    AE = 6371000.0 * 4.0 / 3.0
    d_m = float(d_km[0]) * 1000.0 if d_km.size == 1 else d_km.max() * 1000.0

    tx_elev = profile[0] + tx_h
    rx_elev = profile[-1] + rx_h
    distances = np.linspace(0, d_m, n)

    # Earth curvature
    earth_curve = distances * (d_m - distances) / (2.0 * AE)

    # LOS line
    los_line = np.linspace(tx_elev, rx_elev, n)
    effective = profile + earth_curve

    has_los = np.all(los_line[1:-1] >= effective[1:-1])

    if has_los:
        return free_space(d_km, freq_mhz)
    else:
        return np.full_like(d_km, 999.0)


# ══════════════════════════════════════════════════════════════════════
# 10. GENERAL PURPOSE (CloudRF-style combined model)
# ══════════════════════════════════════════════════════════════════════

def general_purpose(d_km, freq_mhz, tx_h=30.0, rx_h=1.5, **kw):
    """
    General purpose VHF/UHF/SHF model.
    Automatically selects best sub-model based on frequency.
    """
    if freq_mhz < 150:
        return egli(d_km, freq_mhz, tx_h, rx_h, **kw)
    elif freq_mhz < 1500:
        return hata_suburban(d_km, freq_mhz, tx_h, rx_h, **kw)
    elif freq_mhz < 2000:
        return cost231(d_km, freq_mhz, tx_h, rx_h, **kw)
    else:
        return sui(d_km, freq_mhz, tx_h, rx_h, **kw)


# ══════════════════════════════════════════════════════════════════════
# MODEL REGISTRY
# ══════════════════════════════════════════════════════════════════════

MODELS = {
    "free_space": {
        "fn": free_space,
        "name": "Free Space (ITU-R P.525)",
        "freq_range": (2, 90000),
        "description": "Reference model - line of sight only",
    },
    "egli": {
        "fn": egli,
        "name": "Egli VHF/UHF",
        "freq_range": (2, 1500),
        "description": "General purpose VHF/UHF over irregular terrain",
    },
    "hata_urban": {
        "fn": hata_urban,
        "name": "Okumura-Hata (Urban)",
        "freq_range": (150, 1500),
        "description": "Cellular planning - urban areas",
    },
    "hata_suburban": {
        "fn": hata_suburban,
        "name": "Okumura-Hata (Suburban)",
        "freq_range": (150, 1500),
        "description": "Cellular planning - suburban areas",
    },
    "hata_open": {
        "fn": hata_open,
        "name": "Okumura-Hata (Open)",
        "freq_range": (150, 1500),
        "description": "Cellular planning - open/rural areas",
    },
    "cost231": {
        "fn": cost231,
        "name": "COST-231 Hata",
        "freq_range": (150, 2000),
        "description": "Extended Hata model for higher frequencies",
    },
    "sui": {
        "fn": sui,
        "name": "SUI Microwave",
        "freq_range": (1900, 11000),
        "description": "Microwave/SHF planning",
    },
    "ericsson9999": {
        "fn": ericsson9999,
        "name": "Ericsson 9999",
        "freq_range": (150, 1900),
        "description": "Ericsson cellular model",
    },
    "itu_p1812": {
        "fn": itu_p1812,
        "name": "ITU-R P.1812",
        "freq_range": (30, 6000),
        "description": "ITU terrestrial path model",
    },
    "itm": {
        "fn": itm,
        "name": "Longley-Rice ITM",
        "freq_range": (2, 20000),
        "description": "Irregular Terrain Model - general purpose with terrain awareness",
    },
    "los": {
        "fn": line_of_sight,
        "name": "Line of Sight",
        "freq_range": (2, 90000),
        "description": "Visibility testing / viewshed analysis",
    },
    "general_purpose": {
        "fn": general_purpose,
        "name": "General Purpose",
        "freq_range": (2, 90000),
        "description": "Auto-selects best model based on frequency",
    },
}


def get_model(name: str):
    """Get a propagation model function by name."""
    model = MODELS.get(name)
    if model is None:
        raise ValueError(f"Unknown model: {name}. Available: {list(MODELS.keys())}")
    return model["fn"]


def list_models() -> list[dict]:
    """List all available propagation models."""
    return [
        {"id": k, "name": v["name"], "freq_range": v["freq_range"],
         "description": v["description"]}
        for k, v in MODELS.items()
    ]
