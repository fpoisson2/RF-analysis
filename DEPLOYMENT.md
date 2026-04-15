# Deployment

Tested setup: **Proxmox VE host** with an NVIDIA GPU passed through to an **unprivileged Debian/Ubuntu LXC container**. Data lives on a network share (Windows SMB).

The LXC is stateless except for `data/` — all installs are reproducible from this guide.

## 1. Proxmox host — GPU passthrough

Install the NVIDIA driver on the host (kernel module comes from here; userspace goes into the LXC). On Proxmox:

```bash
# Host
apt install -y pve-headers-$(uname -r) build-essential
sh NVIDIA-Linux-x86_64-<version>.run --dkms
nvidia-smi   # confirm driver version (e.g. 590.48.01)
```

Add device passthrough to `/etc/pve/lxc/<CTID>.conf`:

```
lxc.cgroup2.devices.allow: c 195:* rwm
lxc.cgroup2.devices.allow: c 243:* rwm
lxc.mount.entry: /dev/nvidia0 dev/nvidia0 none bind,optional,create=file
lxc.mount.entry: /dev/nvidiactl dev/nvidiactl none bind,optional,create=file
lxc.mount.entry: /dev/nvidia-uvm dev/nvidia-uvm none bind,optional,create=file
lxc.mount.entry: /dev/nvidia-uvm-tools dev/nvidia-uvm-tools none bind,optional,create=file
lxc.mount.entry: /dev/nvidia-caps dev/nvidia-caps none bind,optional,create=dir
```

Restart the container: `pct stop <CTID> && pct start <CTID>`.

**Disk size**: LiDAR tiles total ~13 GB and caches add a few more. Size the rootfs at **≥ 32 GB**, ideally 50 GB:

```bash
pct resize <CTID> rootfs +20G
```

## 2. Inside the LXC — userspace driver

Install the **same** NVIDIA driver version as the host, without the kernel module:

```bash
wget https://us.download.nvidia.com/XFree86/Linux-x86_64/<version>/NVIDIA-Linux-x86_64-<version>.run
chmod +x NVIDIA-Linux-x86_64-<version>.run
./NVIDIA-Linux-x86_64-<version>.run --no-kernel-module --silent --no-questions --accept-license
nvidia-smi   # must show the same version as host
```

## 3. Python environment

```bash
apt install -y python3-venv python3-pip
cd /root/RF-analysis/backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install opencv-python-headless         # required for LiDAR tree detection
pip install cupy-cuda12x                   # GPU acceleration
pip install nvidia-cuda-runtime-cu12 nvidia-cuda-nvrtc-cu12 \
            nvidia-cublas-cu12 nvidia-cusolver-cu12 nvidia-cusparse-cu12 \
            nvidia-cufft-cu12 nvidia-curand-cu12 nvidia-nvjitlink-cu12
```

Smoke-test:

```bash
python -c "import cupy as cp; print(cp.arange(10).sum())"
# → 45
```

## 4. Data: buildings

```bash
python scripts/fetch_data.py --from-release        # buildings GeoJSON from GitHub Release
# OR
python scripts/fetch_data.py --from-backup /path/to/backup
```

Expected: `data/buildings/quebec_city_batiments.geojson` (~165 MB).

## 5. Data: LiDAR (~13 GB)

LiDAR tiles are **not** hosted on GitHub. Options:

### A — Local backup via `fetch_data.py`

Layout expected under the backup root:

```
<backup>/lidar/quebec_city/{MNT,MHC}_21L1{3,4}{NE,NO,SE,SO}.tif
```

```bash
python scripts/fetch_data.py --from-backup /path/to/backup
```

### B — SMB share (Windows source)

Host `\\PC\share` has the tiles. In the LXC:

```bash
apt install -y smbclient
cd /root/RF-analysis/data/lidar/quebec_city
smbclient -U 'user%pass' //<IP>/<share> -c \
  'prompt OFF; cd path\to\lidar\quebec_city; mget *.tif'
```

Notes from experience:
- **CIFS mount in unprivileged LXC fails** (`Operation not permitted`) — use `smbclient` directly, not `mount -t cifs`.
- If your LXC sits on a **different VLAN/subnet** than the SMB host, add a firewall pass rule on your router (OPNsense/pfSense) for `<LXC_IP> → <SMB_HOST>:445 TCP`.
- If the Windows user is a **Microsoft account**, `net user <name> *` returns error 8646. Create a dedicated local account for SMB:
  ```powershell
  net user rfshare <password> /add
  net localgroup "Users" rfshare /add
  Grant-SmbShareAccess -Name "<share>" -AccountName "rfshare" -AccessRight Read -Force
  Enable-NetFirewallRule -DisplayGroup "File and Printer Sharing"
  ```

### C — Source (MERN Québec)

<https://www.foretouverte.gouv.qc.ca/> — feuillets `21L13` and `21L14`, MNT + MHC.

### Verify integrity

After transfer, confirm all 16 tiles parse:

```bash
cd backend && for f in ../data/lidar/quebec_city/*.tif; do
  venv/bin/python -c "import rasterio; rasterio.open('$f').read(1, window=((0,512),(0,512)))" \
    && echo "$f OK" || echo "$f BAD"
done
```

A truncated or ZIP-corrupted tile causes `TIFFReadEncodedTile() failed` / `ZIPDecode error` at runtime — re-fetch that specific file.

## 6. Frontend

```bash
cd /root/RF-analysis/frontend
npm install
npm run dev   # :3000, proxies /api → backend
```

For reverse-proxy or custom domains, add the hostname to `server.allowedHosts` in `vite.config.ts`:

```ts
server: {
  port: 3000,
  host: true,
  allowedHosts: ['rf.example.com', 'localhost'],
}
```

## 7. Running the backend as a service

Foreground (development):

```bash
cd backend && venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Detached (no TTY):

```bash
cd backend && setsid venv/bin/python -m uvicorn app.main:app \
  --host 0.0.0.0 --port 8000 > backend.log 2>&1 < /dev/null &
```

Startup takes ~90 s on first run (indexes 285k buildings, detects 666k trees from LiDAR). Subsequent restarts are faster thanks to `data/output/*_cache/`.

Systemd unit example — `/etc/systemd/system/rf-backend.service`:

```ini
[Unit]
Description=RF Coverage backend
After=network.target

[Service]
Type=simple
WorkingDirectory=/root/RF-analysis/backend
ExecStart=/root/RF-analysis/backend/venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload
systemctl enable --now rf-backend
journalctl -u rf-backend -f
```

## 8. Cache invalidation

When you change the binary scene format or data sources, clear caches:

```bash
rm -rf data/output/scene_cache data/output/buildings_cache \
       data/output/trees_cache data/output/dem_cache
```

Then restart the backend and **hard-reload** the frontend (Ctrl+Shift+R) — the scene endpoint has `Cache-Control: max-age=300`.

## 9. Health checks

```bash
curl http://localhost:8000/api/health | jq
```

Expected:

```json
{
  "gpu":  {"available": true, "device": "NVIDIA GeForce ...", "cuda_version": 12090},
  "lidar":{"available": true, "mnt_tiles": 8, "mhc_tiles": 8}
}
```

If `gpu.available=false` despite CuPy install: missing CUDA runtime libs — re-run the `nvidia-*-cu12` pip block.
If `lidar.available=false`: tiles missing or corrupted — verify with the integrity check in §5.

## 10. Troubleshooting checklist

| Symptom                                           | Likely cause                                                         |
| ------------------------------------------------- | -------------------------------------------------------------------- |
| `nvidia-smi` fails in LXC                         | Driver version mismatch host vs container, or cgroup passthrough off |
| `libnvrtc.so not found`                           | Missing `nvidia-cuda-nvrtc-cu12`                                     |
| `TIFFReadEncodedTile / ZIPDecode` in logs         | Corrupted LiDAR tile — re-fetch and verify                           |
| Frontend `Blocked request. This host ... not allowed` | Add host to `server.allowedHosts` in `vite.config.ts`           |
| DataView out-of-bounds on scene load              | Stale `scene_cache` after format change — delete and restart         |
| `No module named 'cv2'`                           | `pip install opencv-python-headless`                                 |
| `NT_STATUS_DISK_FULL` during SMB fetch            | LXC rootfs too small — `pct resize <CTID> rootfs +20G`               |
| SMB `NT_STATUS_LOGON_FAILURE`                     | Microsoft account user — create dedicated local SMB account          |
