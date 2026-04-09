"""
Knife-edge diffraction models.

Models:
1. Single Knife Edge - Basic Huygens geometric formula
2. Bullington '77 - Fast multi-obstacle approximation
3. Deygout '94 - Advanced multi-obstacle with priority logic
"""
import numpy as np


def fresnel_parameter(h: float, d1: float, d2: float, wavelength: float) -> float:
    """
    Calculate Fresnel diffraction parameter v.
    h: obstacle height above LOS line (meters)
    d1: distance from TX to obstacle (meters)
    d2: distance from obstacle to RX (meters)
    wavelength: signal wavelength (meters)
    """
    if d1 <= 0 or d2 <= 0 or wavelength <= 0:
        return 0.0
    return h * np.sqrt(2.0 * (d1 + d2) / (wavelength * d1 * d2))


def knife_edge_loss(v: float) -> float:
    """
    Calculate knife-edge diffraction loss from Fresnel parameter v.
    Uses Lee's approximation.
    Returns loss in dB (positive = loss, negative = gain from constructive interference).
    """
    v = float(v)
    if v < -1.0:
        return 0.0
    elif v < 0:
        return 6.02 + 9.11 * v - 1.27 * v * v
    elif v < 1.0:
        return 6.02 + 9.11 * v - 1.27 * v * v
    elif v < 2.4:
        return 6.02 + 9.0 * v + 1.65 * v * v
    else:
        return 13.0 + 20.0 * np.log10(v)


# ══════════════════════════════════════════════════════════════════════
# 1. SINGLE KNIFE EDGE
# ══════════════════════════════════════════════════════════════════════

def single_knife_edge(d1_m: float, d2_m: float, h_m: float, freq_mhz: float) -> float:
    """
    Single knife-edge diffraction loss.

    Args:
        d1_m: Distance from TX to obstacle (meters)
        d2_m: Distance from obstacle to RX (meters)
        h_m: Obstacle height above LOS line (meters, positive = above)
        freq_mhz: Frequency in MHz

    Returns:
        Additional diffraction loss in dB
    """
    wavelength = 299792458.0 / (freq_mhz * 1e6)
    v = fresnel_parameter(h_m, d1_m, d2_m, wavelength)
    loss = knife_edge_loss(v)
    return max(0.0, loss)


# ══════════════════════════════════════════════════════════════════════
# 2. BULLINGTON '77
# ══════════════════════════════════════════════════════════════════════

def bullington(distances_m, heights_m, tx_h_m, rx_h_m, freq_mhz):
    """
    Bullington method for knife-edge diffraction over irregular terrain.

    Approximates all obstacles with a single equivalent knife edge.
    Fast but less accurate than Deygout for complex profiles.

    Args:
        distances_m: Array of distances along path (meters)
        heights_m: Array of terrain heights (meters)
        tx_h_m: Transmitter height AGL (meters)
        rx_h_m: Receiver height AGL (meters)
        freq_mhz: Frequency (MHz)

    Returns:
        Diffraction loss in dB
    """
    distances_m = np.asarray(distances_m, dtype=float)
    heights_m = np.asarray(heights_m, dtype=float)
    n = len(distances_m)

    if n < 3:
        return 0.0

    wavelength = 299792458.0 / (freq_mhz * 1e6)

    # TX and RX positions
    tx_elev = heights_m[0] + tx_h_m
    rx_elev = heights_m[-1] + rx_h_m
    d_total = distances_m[-1]

    # Earth curvature correction (4/3 earth)
    ae = 6371000.0 * 4.0 / 3.0
    earth_curve = distances_m * (d_total - distances_m) / (2.0 * ae)

    # Effective heights (terrain + earth curvature)
    eff_heights = heights_m + earth_curve

    # Find maximum angle from TX to each obstacle
    # slope = (h_obstacle - h_tx) / d
    slopes_from_tx = np.zeros(n)
    for i in range(1, n - 1):
        if distances_m[i] > 0:
            slopes_from_tx[i] = (eff_heights[i] - tx_elev) / distances_m[i]

    # Find maximum angle from RX to each obstacle
    slopes_from_rx = np.zeros(n)
    for i in range(1, n - 1):
        d_from_rx = d_total - distances_m[i]
        if d_from_rx > 0:
            slopes_from_rx[i] = (eff_heights[i] - rx_elev) / d_from_rx

    # Find the point with max slope from TX
    idx_tx = np.argmax(slopes_from_tx[1:-1]) + 1
    max_slope_tx = slopes_from_tx[idx_tx]

    # Find the point with max slope from RX
    idx_rx = np.argmax(slopes_from_rx[1:-1]) + 1
    max_slope_rx = slopes_from_rx[idx_rx]

    # LOS slope
    los_slope = (rx_elev - tx_elev) / d_total

    # If no obstruction above LOS, no diffraction loss
    if max_slope_tx <= los_slope:
        return 0.0

    # Bullington point: intersection of the two tangent lines
    # from TX and RX to their respective dominant obstacles
    if idx_tx == idx_rx:
        # Same obstacle dominates from both sides
        d_b = distances_m[idx_tx]
    else:
        # Find intersection
        # Line from TX: h = tx_elev + max_slope_tx * d
        # Line from RX: h = rx_elev + max_slope_rx * (d_total - d)
        # Solve: tx_elev + s_tx * d = rx_elev + s_rx * (d_total - d)
        denom = max_slope_tx + max_slope_rx
        if abs(denom) < 1e-10:
            d_b = d_total / 2.0
        else:
            d_b = (rx_elev + max_slope_rx * d_total - tx_elev) / denom
            d_b = np.clip(d_b, distances_m[1], distances_m[-2])

    # Bullington height
    h_b = tx_elev + max_slope_tx * d_b

    # LOS height at Bullington point
    h_los = tx_elev + los_slope * d_b

    # Effective obstacle height above LOS
    h_eff = h_b - h_los

    if h_eff <= 0:
        return 0.0

    # Distances from TX and RX to Bullington point
    d1 = d_b
    d2 = d_total - d_b

    # Fresnel parameter and loss
    v = fresnel_parameter(h_eff, d1, d2, wavelength)
    return max(0.0, knife_edge_loss(v))


# ══════════════════════════════════════════════════════════════════════
# 3. DEYGOUT '94
# ══════════════════════════════════════════════════════════════════════

def deygout94(distances_m, heights_m, tx_h_m, rx_h_m, freq_mhz, max_obstacles=3):
    """
    Deygout '94 method for multi-obstacle diffraction.

    Advanced method that finds the dominant obstacle first, then recursively
    analyzes sub-paths. Recognized as the most accurate method for
    multi-obstacle terrain profiles.

    Args:
        distances_m: Array of distances along path (meters)
        heights_m: Array of terrain heights (meters)
        tx_h_m: Transmitter height AGL (meters)
        rx_h_m: Receiver height AGL (meters)
        freq_mhz: Frequency (MHz)
        max_obstacles: Maximum number of obstacles to consider (default: 3)

    Returns:
        Diffraction loss in dB
    """
    distances_m = np.asarray(distances_m, dtype=float)
    heights_m = np.asarray(heights_m, dtype=float)
    n = len(distances_m)

    if n < 3:
        return 0.0

    wavelength = 299792458.0 / (freq_mhz * 1e6)

    # Apply earth curvature correction
    d_total = distances_m[-1]
    ae = 6371000.0 * 4.0 / 3.0
    earth_curve = distances_m * (d_total - distances_m) / (2.0 * ae)
    eff_heights = heights_m + earth_curve

    tx_elev = eff_heights[0] + tx_h_m
    rx_elev = eff_heights[-1] + rx_h_m

    return _deygout_recursive(
        distances_m, eff_heights, tx_elev, rx_elev,
        0, n - 1, wavelength, max_obstacles, 0
    )


def _deygout_recursive(distances, heights, h_tx, h_rx,
                        idx_start, idx_end, wavelength,
                        max_obstacles, depth):
    """Recursive Deygout obstacle analysis."""
    if depth >= max_obstacles or idx_end - idx_start < 2:
        return 0.0

    d_start = distances[idx_start]
    d_end = distances[idx_end]
    d_span = d_end - d_start

    if d_span <= 0:
        return 0.0

    # LOS line between current TX and RX points
    max_v = -999.0
    max_idx = -1

    for i in range(idx_start + 1, idx_end):
        d_from_tx = distances[i] - d_start
        d_from_rx = d_end - distances[i]

        if d_from_tx <= 0 or d_from_rx <= 0:
            continue

        # Height of LOS at this point
        h_los = h_tx + (h_rx - h_tx) * d_from_tx / d_span

        # Height above LOS
        h_above = heights[i] - h_los

        if h_above <= 0:
            continue

        # Fresnel parameter
        v = fresnel_parameter(h_above, d_from_tx, d_from_rx, wavelength)

        if v > max_v:
            max_v = v
            max_idx = i

    if max_idx < 0 or max_v < -0.5:
        return 0.0

    # Dominant obstacle loss
    main_loss = knife_edge_loss(max_v)

    # Height of dominant obstacle
    h_obstacle = heights[max_idx]

    # Recursively analyze sub-paths
    # Left sub-path: TX to obstacle
    left_loss = _deygout_recursive(
        distances, heights, h_tx, h_obstacle,
        idx_start, max_idx, wavelength, max_obstacles, depth + 1
    )

    # Right sub-path: obstacle to RX
    right_loss = _deygout_recursive(
        distances, heights, h_obstacle, h_rx,
        max_idx, idx_end, wavelength, max_obstacles, depth + 1
    )

    return max(0.0, main_loss + left_loss + right_loss)


# ══════════════════════════════════════════════════════════════════════
# CONVENIENCE FUNCTIONS
# ══════════════════════════════════════════════════════════════════════

DIFFRACTION_MODELS = {
    "none": lambda *a, **kw: 0.0,
    "knife_edge": single_knife_edge,
    "bullington": bullington,
    "deygout94": deygout94,
}


def get_diffraction_model(name: str):
    """Get a diffraction model function by name."""
    model = DIFFRACTION_MODELS.get(name)
    if model is None:
        raise ValueError(f"Unknown diffraction model: {name}. Available: {list(DIFFRACTION_MODELS.keys())}")
    return model


def fresnel_zone_radius(d1_m: float, d2_m: float, freq_mhz: float, n: int = 1) -> float:
    """
    Calculate nth Fresnel zone radius.
    d1: distance from TX to point (meters)
    d2: distance from point to RX (meters)
    """
    wavelength = 299792458.0 / (freq_mhz * 1e6)
    d_total = d1_m + d2_m
    if d_total <= 0:
        return 0.0
    return np.sqrt(n * wavelength * d1_m * d2_m / d_total)
