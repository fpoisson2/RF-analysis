"""
Native CUDA kernels for coverage computation.

Uses CuPy RawKernel to run per-pixel knife-edge diffraction at native
resolution. One CUDA thread = one output pixel. Each thread walks the
terrain profile from the transmitter to its destination pixel, finds the
dominant obstacle (worst Fresnel parameter), and computes the resulting
knife-edge diffraction loss with 4/3 earth curvature correction.

This replaces the old radial sweep that quantised profiles into ~15
distance buckets and produced a low-detail disc around the transmitter.
"""
import logging
import numpy as np

from ..gpu import GPU_AVAILABLE

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# CUDA kernel source
# ═══════════════════════════════════════════════════════════════
#
# Inputs
# ------
# elev_grid   : (terrain_h, terrain_w) float32, row-major, row 0 = lat_max
# tx_ground   : terrain elevation at TX (pre-computed on host)
# tx_h_agl    : TX antenna height above ground
# rx_h_agl    : RX antenna height above ground
# freq_mhz    : carrier frequency
# n_cells     : output grid size (square)
# radius_m    : coverage radius
# cos_lat     : cos(tx_lat) for lon→m conversion
#
# Output
# ------
# diff_out    : (n_cells, n_cells) float32, diffraction loss in dB
#
# Sampling is adaptive: ~1 sample per 20 m of TX→pixel distance, clamped
# to [16, 256]. Terrain is read with bilinear interpolation.
DIFFRACTION_KERNEL_SRC = r"""
extern "C" __global__
void diffraction_dominant_obstacle(
    const float* __restrict__ elev_grid,
    const int   terrain_h,
    const int   terrain_w,
    const float lat_min,
    const float lat_max,
    const float lon_min,
    const float lon_max,
    const float tx_lat,
    const float tx_lon,
    const float tx_ground,
    const float tx_h_agl,
    const float rx_h_agl,
    const float freq_mhz,
    const int   n_cells,
    const float radius_m,
    const float cos_lat,
    float* __restrict__ diff_out)
{
    const int col = blockIdx.x * blockDim.x + threadIdx.x;
    const int row = blockIdx.y * blockDim.y + threadIdx.y;
    if (col >= n_cells || row >= n_cells) return;

    const size_t out_idx = (size_t)row * (size_t)n_cells + (size_t)col;

    // Pixel geographic coordinates (cell center)
    const float inv_cells = 1.0f / (float)n_cells;
    const float pixel_lat = lat_max - ((float)row + 0.5f) * (lat_max - lat_min) * inv_cells;
    const float pixel_lon = lon_min + ((float)col + 0.5f) * (lon_max - lon_min) * inv_cells;

    // Equirectangular ground distance TX -> pixel
    const float dy_m = (pixel_lat - tx_lat) * 111320.0f;
    const float dx_m = (pixel_lon - tx_lon) * 111320.0f * cos_lat;
    const float dist_m = sqrtf(dx_m * dx_m + dy_m * dy_m);

    if (dist_m < 1.0f || dist_m > radius_m) {
        diff_out[out_idx] = 0.0f;
        return;
    }

    const float tw_f = (float)(terrain_w - 1);
    const float th_f = (float)(terrain_h - 1);

    // RX ground elevation via bilinear interpolation
    const float rx_r_f = fminf(fmaxf((lat_max - pixel_lat) / (lat_max - lat_min) * th_f, 0.0f), th_f);
    const float rx_c_f = fminf(fmaxf((pixel_lon - lon_min) / (lon_max - lon_min) * tw_f, 0.0f), tw_f);
    const int rx_r0 = (int)floorf(rx_r_f);
    const int rx_c0 = (int)floorf(rx_c_f);
    const int rx_r1 = min(rx_r0 + 1, terrain_h - 1);
    const int rx_c1 = min(rx_c0 + 1, terrain_w - 1);
    const float rx_fr = rx_r_f - (float)rx_r0;
    const float rx_fc = rx_c_f - (float)rx_c0;
    const float rx_h00 = elev_grid[rx_r0 * terrain_w + rx_c0];
    const float rx_h01 = elev_grid[rx_r0 * terrain_w + rx_c1];
    const float rx_h10 = elev_grid[rx_r1 * terrain_w + rx_c0];
    const float rx_h11 = elev_grid[rx_r1 * terrain_w + rx_c1];
    const float rx_ground =
        rx_h00 * (1.0f - rx_fr) * (1.0f - rx_fc) +
        rx_h01 * (1.0f - rx_fr) * rx_fc +
        rx_h10 * rx_fr * (1.0f - rx_fc) +
        rx_h11 * rx_fr * rx_fc;

    const float tx_elev = tx_ground + tx_h_agl;
    const float rx_elev = rx_ground + rx_h_agl;

    // Wavelength in meters (c = 299.792458 Mm/s)
    const float wavelength = 299.792458f / freq_mhz;

    // Adaptive sampling: ~one sample per 10 m of path, clamped to [32, 384]
    int n_samples = (int)(dist_m / 10.0f);
    if (n_samples < 32)  n_samples = 32;
    if (n_samples > 384) n_samples = 384;

    // 4/3 effective earth radius (6371000 * 4/3)
    const float AE = 8494666.0f;

    const float inv_n = 1.0f / (float)n_samples;
    const float d_lat_step = (pixel_lat - tx_lat) * inv_n;
    const float d_lon_step = (pixel_lon - tx_lon) * inv_n;

    // Track the worst Fresnel parameter along the path (positive OR
    // negative). Negative v within [-0.78, 0] yields up to 6 dB of
    // partial-clearance loss which produces visible texture on clear
    // links whose first Fresnel zone grazes terrain.
    float max_v = -1.0e30f;

    // Running stats for terrain along the path (for dh roughness term)
    float sum_h   = 0.0f;
    float sum_h2  = 0.0f;
    int   n_stats = 0;

    #pragma unroll 4
    for (int i = 1; i < n_samples; ++i) {
        const float frac      = (float)i * inv_n;
        const float d_from_tx = dist_m * frac;
        const float d_from_rx = dist_m - d_from_tx;

        // Sample position along TX->pixel ray (flat-earth approx)
        const float s_lat = tx_lat + d_lat_step * (float)i;
        const float s_lon = tx_lon + d_lon_step * (float)i;

        // Bilinear terrain lookup
        const float r_f = fminf(fmaxf((lat_max - s_lat) / (lat_max - lat_min) * th_f, 0.0f), th_f);
        const float c_f = fminf(fmaxf((s_lon - lon_min) / (lon_max - lon_min) * tw_f, 0.0f), tw_f);
        const int r0 = (int)floorf(r_f);
        const int c0 = (int)floorf(c_f);
        const int r1 = min(r0 + 1, terrain_h - 1);
        const int c1 = min(c0 + 1, terrain_w - 1);
        const float fr = r_f - (float)r0;
        const float fc = c_f - (float)c0;
        const float h00 = elev_grid[r0 * terrain_w + c0];
        const float h01 = elev_grid[r0 * terrain_w + c1];
        const float h10 = elev_grid[r1 * terrain_w + c0];
        const float h11 = elev_grid[r1 * terrain_w + c1];
        const float h_terrain =
            h00 * (1.0f - fr) * (1.0f - fc) +
            h01 * (1.0f - fr) * fc +
            h10 * fr * (1.0f - fc) +
            h11 * fr * fc;

        // Roughness accumulators
        sum_h  += h_terrain;
        sum_h2 += h_terrain * h_terrain;
        n_stats++;

        // Earth curvature bulge (adds to effective obstacle height)
        const float earth_curve = d_from_tx * d_from_rx / (2.0f * AE);
        const float h_eff = h_terrain + earth_curve;

        // LOS line height at this sample (straight line TX->RX antenna)
        const float h_los = tx_elev + (rx_elev - tx_elev) * frac;
        const float h_above = h_eff - h_los;

        // Fresnel parameter v = h_above * sqrt(2*(d1+d2) / (lambda*d1*d2))
        // Valid for h_above > 0 (obstruction) AND h_above < 0 (partial
        // Fresnel clearance). We must NOT skip negative h_above samples:
        // that was the bug that left the centre blank.
        const float denom = wavelength * d_from_tx * d_from_rx;
        if (denom <= 0.0f) continue;
        const float v = h_above * sqrtf(2.0f * dist_m / denom);

        if (v > max_v) max_v = v;
    }

    // Knife-edge loss (Lee / ITU-R P.526 piecewise approximation).
    // Now fires for partial Fresnel clearance (v in [-0.78, 0]) as well.
    float loss = 0.0f;
    if (max_v > -0.78f) {
        if (max_v < 0.0f) {
            loss = 6.02f + 9.11f * max_v - 1.27f * max_v * max_v;
        } else if (max_v < 2.4f) {
            loss = 6.02f + 9.0f * max_v + 1.65f * max_v * max_v;
        } else {
            loss = 13.0f + 20.0f * log10f(max_v);
        }
        if (loss < 0.0f) loss = 0.0f;
    }

    // Terrain roughness loss (ITM-style clutter term).
    // dh = std(profile), capped at ~100 m. Short rays with stats are
    // dominated by local terrain variance and create the fine-grained
    // texture near the TX that was missing.
    if (n_stats > 3) {
        const float inv_ns = 1.0f / (float)n_stats;
        const float mean_h = sum_h * inv_ns;
        const float var_h  = fmaxf(sum_h2 * inv_ns - mean_h * mean_h, 0.0f);
        const float dh     = fminf(sqrtf(var_h), 120.0f);
        // Roughness loss: ITM/Egli-style, grows slowly with dh
        const float rough  = 4.0f * log10f(1.0f + dh * 0.2f);
        loss += rough;
    }

    diff_out[out_idx] = loss;
}
"""


_kernel = None


def _get_kernel():
    """Lazy-compile the CUDA kernel on first call."""
    global _kernel
    if _kernel is None:
        import cupy as cp
        _kernel = cp.RawKernel(
            DIFFRACTION_KERNEL_SRC,
            "diffraction_dominant_obstacle",
            options=("--use_fast_math",),
        )
        logger.info("CUDA diffraction kernel compiled")
    return _kernel


def compute_diffraction_grid_gpu(
    elev_grid: np.ndarray,
    lat_min: float,
    lat_max: float,
    lon_min: float,
    lon_max: float,
    tx_lat: float,
    tx_lon: float,
    tx_ground: float,
    tx_h_agl: float,
    rx_h_agl: float,
    freq_mhz: float,
    n_cells: int,
    radius_m: float,
    cos_lat: float,
) -> np.ndarray:
    """
    Compute per-pixel knife-edge diffraction loss on GPU.

    Returns a NumPy (n_cells, n_cells) float32 array of loss in dB.
    """
    if not GPU_AVAILABLE:
        raise RuntimeError("CUDA/CuPy not available")

    import cupy as cp

    terrain_h, terrain_w = elev_grid.shape

    # Upload terrain to device (one-shot)
    elev_gpu = cp.asarray(elev_grid, dtype=cp.float32)
    diff_out = cp.zeros((n_cells, n_cells), dtype=cp.float32)

    # Block / grid dimensions (16x16 = 256 threads per block)
    block = (16, 16, 1)
    grid = (
        (n_cells + block[0] - 1) // block[0],
        (n_cells + block[1] - 1) // block[1],
        1,
    )

    kernel = _get_kernel()
    kernel(
        grid,
        block,
        (
            elev_gpu,
            np.int32(terrain_h),
            np.int32(terrain_w),
            np.float32(lat_min),
            np.float32(lat_max),
            np.float32(lon_min),
            np.float32(lon_max),
            np.float32(tx_lat),
            np.float32(tx_lon),
            np.float32(tx_ground),
            np.float32(tx_h_agl),
            np.float32(rx_h_agl),
            np.float32(freq_mhz),
            np.int32(n_cells),
            np.float32(radius_m),
            np.float32(cos_lat),
            diff_out,
        ),
    )
    cp.cuda.Stream.null.synchronize()

    return cp.asnumpy(diff_out)


def compute_diffraction_grid_cpu(
    elev_grid: np.ndarray,
    lat_min: float,
    lat_max: float,
    lon_min: float,
    lon_max: float,
    tx_lat: float,
    tx_lon: float,
    tx_ground: float,
    tx_h_agl: float,
    rx_h_agl: float,
    freq_mhz: float,
    n_cells: int,
    radius_m: float,
    cos_lat: float,
    pixel_lats: np.ndarray,
    pixel_lons: np.ndarray,
    dist_m: np.ndarray,
) -> np.ndarray:
    """
    Vectorized NumPy fallback: same algorithm as the CUDA kernel but with
    a fixed sample count. Slower than GPU but still per-pixel and correct.
    """
    terrain_h, terrain_w = elev_grid.shape

    # RX ground elevation (nearest-neighbor)
    rx_r = np.clip(
        ((lat_max - pixel_lats) / (lat_max - lat_min) * (terrain_h - 1)).astype(np.int32),
        0, terrain_h - 1,
    )
    rx_c = np.clip(
        ((pixel_lons - lon_min) / (lon_max - lon_min) * (terrain_w - 1)).astype(np.int32),
        0, terrain_w - 1,
    )
    rx_ground = elev_grid[rx_r, rx_c].astype(np.float32)
    tx_elev = np.float32(tx_ground + tx_h_agl)
    rx_elev = rx_ground + np.float32(rx_h_agl)

    wavelength = np.float32(299.792458 / freq_mhz)
    AE = np.float32(8494666.0)
    dist_m_f = dist_m.astype(np.float32)

    # Fixed sample count (good balance speed/quality on CPU)
    n_samples = 64

    max_v = np.full(dist_m.shape, -1.0e30, dtype=np.float32)
    sum_h = np.zeros(dist_m.shape, dtype=np.float32)
    sum_h2 = np.zeros(dist_m.shape, dtype=np.float32)

    in_disc = (dist_m_f > 1.0) & (dist_m_f <= radius_m)

    for i in range(1, n_samples):
        frac = np.float32(i / n_samples)
        d_from_tx = dist_m_f * frac
        d_from_rx = dist_m_f - d_from_tx

        s_lat = tx_lat + (pixel_lats - tx_lat) * frac
        s_lon = tx_lon + (pixel_lons - tx_lon) * frac

        r_i = np.clip(
            ((lat_max - s_lat) / (lat_max - lat_min) * (terrain_h - 1)).astype(np.int32),
            0, terrain_h - 1,
        )
        c_i = np.clip(
            ((s_lon - lon_min) / (lon_max - lon_min) * (terrain_w - 1)).astype(np.int32),
            0, terrain_w - 1,
        )
        h_terrain = elev_grid[r_i, c_i].astype(np.float32)

        sum_h += h_terrain
        sum_h2 += h_terrain * h_terrain

        earth_curve = d_from_tx * d_from_rx / (2.0 * AE)
        h_eff = h_terrain + earth_curve
        h_los = tx_elev + (rx_elev - tx_elev) * frac
        h_above = h_eff - h_los

        # Track Fresnel parameter for ALL samples (positive and negative
        # h_above) so partial Fresnel clearance produces texture.
        denom = wavelength * d_from_tx * d_from_rx
        with np.errstate(invalid="ignore", divide="ignore"):
            v = np.where(
                (denom > 1e-9) & in_disc,
                h_above * np.sqrt(2.0 * dist_m_f / np.maximum(denom, 1e-9)),
                -1.0e30,
            ).astype(np.float32)
        np.maximum(max_v, v, out=max_v)

    # Knife-edge loss (piecewise) including partial Fresnel clearance
    valid = max_v > -0.78
    v = np.where(valid, max_v, 0.0).astype(np.float32)
    loss = np.where(
        v < 0,
        6.02 + 9.11 * v - 1.27 * v * v,
        np.where(
            v < 2.4,
            6.02 + 9.0 * v + 1.65 * v * v,
            13.0 + 20.0 * np.log10(np.maximum(v, 0.01)),
        ),
    )
    loss = np.where(valid, np.maximum(loss, 0.0), 0.0).astype(np.float32)

    # Roughness / clutter term from terrain std along each path
    n_stats = max(1, n_samples - 1)
    mean_h = sum_h / n_stats
    var_h = np.maximum(sum_h2 / n_stats - mean_h * mean_h, 0.0)
    dh = np.minimum(np.sqrt(var_h), 120.0)
    rough = 4.0 * np.log10(1.0 + dh * 0.2)
    loss = loss + rough.astype(np.float32)
    loss = np.where(in_disc, loss, 0.0).astype(np.float32)
    return loss
