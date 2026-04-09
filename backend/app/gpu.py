"""
GPU acceleration module.
Uses CuPy (CUDA) when available, falls back to NumPy.
"""
import os
import logging

logger = logging.getLogger(__name__)

# Try to import CuPy for CUDA acceleration
GPU_AVAILABLE = False
GPU_DEVICE_NAME = "CPU"

try:
    import cupy as cp
    GPU_AVAILABLE = True
    device = cp.cuda.Device(0)
    free_mem, total_mem = device.mem_info
    try:
        props = cp.cuda.runtime.getDeviceProperties(device.id)
        GPU_DEVICE_NAME = props["name"].decode() if isinstance(props["name"], bytes) else str(props["name"])
    except Exception:
        GPU_DEVICE_NAME = f"CUDA GPU (compute {device.compute_capability})"
    logger.info(f"CUDA GPU detected: {GPU_DEVICE_NAME}")
    logger.info(f"CUDA memory: {total_mem / 1e9:.1f} GB ({free_mem / 1e9:.1f} GB free)")
except ImportError:
    logger.info("CuPy not installed. Using CPU (NumPy). Install cupy-cuda12x for GPU acceleration.")
except Exception as e:
    logger.info(f"CUDA not available: {e}. Using CPU (NumPy).")

# Unified array module - use xp everywhere instead of np
import numpy as np

if GPU_AVAILABLE:
    import cupy as cp
    xp = cp  # Use CuPy arrays (GPU)
else:
    xp = np  # Use NumPy arrays (CPU)


def to_numpy(arr):
    """Convert array to NumPy (CPU) regardless of backend."""
    if GPU_AVAILABLE and isinstance(arr, cp.ndarray):
        return cp.asnumpy(arr)
    return np.asarray(arr)


def to_gpu(arr):
    """Convert array to GPU if available, otherwise return as-is."""
    if GPU_AVAILABLE:
        return cp.asarray(arr)
    return arr


def gpu_status() -> dict:
    """Return GPU status information."""
    if GPU_AVAILABLE:
        device = cp.cuda.Device(0)
        free, total = device.mem_info
        return {
            "available": True,
            "device": GPU_DEVICE_NAME,
            "memory_total_gb": round(total / 1e9, 2),
            "memory_free_gb": round(free / 1e9, 2),
            "cuda_version": cp.cuda.runtime.runtimeGetVersion(),
        }
    return {
        "available": False,
        "device": "CPU (NumPy)",
        "message": "Install cupy-cuda12x for GPU acceleration",
    }
