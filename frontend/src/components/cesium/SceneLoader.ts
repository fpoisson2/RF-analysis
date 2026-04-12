export interface ParsedBuilding {
  ring: number[];       // flat [lon0, lat0, lon1, lat1, ...] pairs
  nVerts: number;
  height: number;
  groundZ: number;      // terrain elevation at centroid (meters)
  centroidLat: number;
  centroidLon: number;
}

export interface ParsedTree {
  lon: number;
  lat: number;
  height: number;
  groundZ: number;
}

export interface ParsedScene {
  buildings: ParsedBuilding[];
  trees: ParsedTree[];
  serverMs: number;
  byteLength: number;
}

export function parseScene(buffer: ArrayBuffer): ParsedScene {
  const view = new DataView(buffer);
  let off = 4; // skip "SC3D" magic
  const nBldg = view.getUint32(off, true); off += 4;
  const nTrees = view.getUint32(off, true); off += 4;
  const serverMs = view.getFloat32(off, true); off += 4;

  const buildings: ParsedBuilding[] = new Array(nBldg);
  for (let i = 0; i < nBldg; i++) {
    const nVerts = view.getUint16(off, true); off += 2;
    const height = view.getFloat32(off, true); off += 4;
    const groundZ = view.getFloat32(off, true); off += 4;
    const ring: number[] = new Array(nVerts * 2);
    let cLat = 0, cLon = 0;
    for (let v = 0; v < nVerts; v++) {
      const lng = view.getFloat32(off, true); off += 4;
      const lat = view.getFloat32(off, true); off += 4;
      ring[v * 2] = lng;
      ring[v * 2 + 1] = lat;
      cLon += lng;
      cLat += lat;
    }
    buildings[i] = {
      ring,
      nVerts,
      height,
      groundZ,
      centroidLat: cLat / nVerts,
      centroidLon: cLon / nVerts,
    };
  }

  const trees: ParsedTree[] = new Array(nTrees);
  for (let i = 0; i < nTrees; i++) {
    const lon = view.getFloat32(off, true); off += 4;
    const lat = view.getFloat32(off, true); off += 4;
    const height = view.getFloat32(off, true); off += 4;
    const groundZ = view.getFloat32(off, true); off += 4;
    trees[i] = { lon, lat, height, groundZ };
  }

  return { buildings, trees, serverMs, byteLength: buffer.byteLength };
}

export function shouldReloadScene(
  prev: { lat: number; lon: number; radius: number } | null,
  lat: number,
  lon: number,
  radius: number,
): boolean {
  if (!prev) return true;
  const dlat = (lat - prev.lat) * 111320;
  const dlon = (lon - prev.lon) * 111320 * Math.cos(lat * Math.PI / 180);
  if (Math.sqrt(dlat * dlat + dlon * dlon) < 500 && Math.abs(radius - prev.radius) < 0.5) {
    return false;
  }
  return true;
}
