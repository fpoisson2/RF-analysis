"""
NTIA Longley–Rice / ITM wrapper.

Uses the ``pyitm`` Python binding around the NTIA reference C++ implementation
(https://github.com/NTIA/itm). This is the same algorithm used by Radio Mobile,
SPLAT! and many commercial RF planning tools.

Two modes:
- area mode  (no terrain profile)        — statistical, fast
- p2p   mode (with terrain profile)      — accurate per-link

Returns *total path loss in dB* (including free-space). The simplified model
in ``models.itm`` returns the same convention so callers don't need to change.
"""
from __future__ import annotations
import logging
import numpy as np

logger = logging.getLogger(__name__)

try:
    from pyitm.itm import (
        PropType, PropaType, PropvType, qlrps, qlra, lrprop, avar
    )
    HAS_PYITM = True
except ImportError:
    HAS_PYITM = False


def _fspl_db(d_km: float, f_mhz: float) -> float:
    """Free-space path loss in dB."""
    if d_km <= 0:
        return 0.0
    return 20.0 * np.log10(d_km) + 20.0 * np.log10(f_mhz) + 32.44


# Reasonable defaults for ITM in continental temperate climate (radio_climate=5)
DEFAULTS = dict(
    eps=15.0,           # ground permittivity
    sgm=0.005,          # ground conductivity (S/m)
    en0=301.0,          # surface refractivity (N-units)
    pol=1,              # 1 = vertical, 0 = horizontal
    radio_climate=5,    # 5 = continental temperate
    siting=2,           # 2 = average / random siting (0=random, 1=careful, 2=very careful)
)


def _delta_h_for_context(context: str) -> float:
    """Map our 'context' string to ITM's deltaH (terrain irregularity)."""
    return {
        "smooth": 0.0,
        "plains": 30.0,
        "average": 90.0,
        "hills": 90.0,
        "mountains": 200.0,
        "rugged": 500.0,
        "conservative": 200.0,
        "optimistic": 30.0,
    }.get(context, 90.0)


def _setup_area(prop: PropType, propv: PropvType,
                tx_h: float, rx_h: float,
                f_mhz: float, dh: float,
                pol: int = DEFAULTS["pol"],
                radio_climate: int = DEFAULTS["radio_climate"]):
    """Configure prop/propv objects for area mode."""
    prop.hg = [float(tx_h), float(rx_h)]
    prop.dh = float(dh)
    prop.gme = 157e-9  # 4/3 earth
    prop.ens = DEFAULTS["en0"]

    qlrps(fmhz=float(f_mhz), zsys=0,
          en0=DEFAULTS["en0"], ipol=pol,
          eps=DEFAULTS["eps"], sgm=DEFAULTS["sgm"], prop=prop)
    # mdvarx=2 → Mobile mode: pctTime carries the time/location reliability,
    # which matches the "Reliability %" slider semantics in the UI.
    qlra(kst=[DEFAULTS["siting"], DEFAULTS["siting"]],
         klimx=radio_climate, mdvarx=2,
         prop=prop, propv=propv)


def itm_area_loss(d_km: float | np.ndarray, f_mhz: float,
                   tx_h: float, rx_h: float,
                   context: str = "average",
                   reliability: float = 50,
                   pol: int = DEFAULTS["pol"]) -> np.ndarray:
    """
    NTIA ITM area mode — total path loss (dB) including free-space.

    Vectorised over distance.
    """
    if not HAS_PYITM:
        raise RuntimeError("pyitm not installed")

    d_km_arr = np.asarray(d_km, dtype=float)
    orig_shape = d_km_arr.shape
    d_flat = d_km_arr.ravel()
    dh = _delta_h_for_context(context)

    prop = PropType()
    propv = PropvType()
    propa = PropaType()
    _setup_area(prop, propv, tx_h, rx_h, f_mhz, dh, pol=pol)

    try:
        from scipy.special import ndtri
        zzt = float(ndtri(reliability / 100.0))
    except Exception:
        zzt = 0.0

    out = np.zeros_like(d_flat)
    for i in range(d_flat.size):
        d = float(d_flat[i])
        d_m = max(d * 1000.0, 1.0)
        try:
            lrprop(d=d_m, prop=prop, propa=propa)
            aref = avar(zzt=zzt, zzl=0, zzc=0, prop=prop, propv=propv)
            out[i] = _fspl_db(d, f_mhz) + float(aref)
        except Exception as e:
            logger.debug(f"ITM lrprop failed at d={d_m}m: {e}")
            out[i] = _fspl_db(d, f_mhz)
    return out.reshape(orig_shape) if orig_shape else out


def itm_p2p_loss(distances_m: np.ndarray, heights_m: np.ndarray,
                  f_mhz: float, tx_h: float, rx_h: float,
                  reliability: float = 50,
                  pol: int = DEFAULTS["pol"]) -> float:
    """
    NTIA ITM point-to-point — uses the actual terrain profile to compute
    a single total loss for the full link. Best accuracy when LiDAR/SRTM
    profile is available.

    NOTE: this uses ITM area mode with deltaH derived from the profile.
    True p2p (qlrpfl) is more involved; an upgrade target.
    """
    if not HAS_PYITM:
        raise RuntimeError("pyitm not installed")

    heights = np.asarray(heights_m, dtype=float)
    if heights.size < 3:
        return _fspl_db(distances_m[-1] / 1000.0, f_mhz)

    # Terrain irregularity = interdecile range of heights
    p10, p90 = np.percentile(heights, [10, 90])
    dh = float(p90 - p10)

    d_km = float(distances_m[-1]) / 1000.0
    arr = itm_area_loss(np.array([d_km]), f_mhz, tx_h, rx_h,
                        context="average", reliability=reliability, pol=pol)
    # Override the heuristic context with the empirical deltaH:
    prop = PropType()
    propv = PropvType()
    propa = PropaType()
    _setup_area(prop, propv, tx_h, rx_h, f_mhz, dh, pol=pol)
    try:
        from scipy.special import ndtri
        zzt = float(ndtri(reliability / 100.0))
    except Exception:
        zzt = 0.0
    try:
        lrprop(d=d_km * 1000.0, prop=prop, propa=propa)
        aref = avar(zzt=zzt, zzl=0, zzc=0, prop=prop, propv=propv)
        return _fspl_db(d_km, f_mhz) + float(aref)
    except Exception:
        return float(arr[0])


def itm_ntia(d_km, freq_mhz, tx_h=30.0, rx_h=1.5,
              terrain_profile=None, reliability=50,
              context="average", pol=1, **kw):
    """
    Unified entry point matching the signature of ``models.itm``.
    Selects p2p when a terrain profile is provided, else area mode.
    """
    if not HAS_PYITM:
        # graceful fallback to the simplified ITM
        from .models import itm as simplified
        return simplified(d_km, freq_mhz, tx_h, rx_h,
                          terrain_profile=terrain_profile,
                          reliability=reliability, context=context, **kw)

    if terrain_profile is not None and len(terrain_profile) > 2:
        d_arr = np.asarray(d_km, dtype=float)
        orig_shape = d_arr.shape
        d_flat = d_arr.ravel() if d_arr.ndim else np.array([float(d_arr)])

        heights = np.asarray(terrain_profile, dtype=float)
        p10, p90 = np.percentile(heights, [10, 90])
        dh = float(p90 - p10)

        prop = PropType()
        propv = PropvType()
        propa = PropaType()
        _setup_area(prop, propv, tx_h, rx_h, freq_mhz, dh, pol=pol)
        try:
            from scipy.special import ndtri
            zzt = float(ndtri(reliability / 100.0))
        except Exception:
            zzt = 0.0

        out = np.zeros(d_flat.size)
        for i in range(d_flat.size):
            d = float(d_flat[i])
            d_m = max(d * 1000.0, 1.0)
            try:
                lrprop(d=d_m, prop=prop, propa=propa)
                aref = avar(zzt=zzt, zzl=0, zzc=0, prop=prop, propv=propv)
                out[i] = _fspl_db(d, freq_mhz) + float(aref)
            except Exception:
                out[i] = _fspl_db(d, freq_mhz)
        if not orig_shape:
            return float(out[0])
        return out.reshape(orig_shape)
    else:
        return itm_area_loss(d_km, freq_mhz, tx_h, rx_h,
                              context=context, reliability=reliability, pol=pol)
