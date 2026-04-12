import * as Cesium from 'cesium';

const TILE_SIZE = 256;
const MAX_TERRARIUM_LEVEL = 15;
const MIN_REQUEST_LEVEL = 6;
const FLAT_TILE = new Float32Array(TILE_SIZE * TILE_SIZE);
const heightmapCache = new Map<string, Float32Array>();

/**
 * Decode a Terrarium-encoded PNG:
 *   elevation = (R * 256 + G + B / 256) - 32768
 */
async function decodeTerrarium(url: string): Promise<Float32Array> {
  const cached = heightmapCache.get(url);
  if (cached) return cached;

  try {
    const response = await fetch(url, { mode: 'cors' });
    if (!response.ok) return FLAT_TILE;

    const blob = await response.blob();
    if (blob.size === 0) return FLAT_TILE;

    const bitmap = await createImageBitmap(blob);
    const canvas = document.createElement('canvas');
    canvas.width = TILE_SIZE;
    canvas.height = TILE_SIZE;
    const ctx = canvas.getContext('2d', { willReadFrequently: true })!;
    ctx.drawImage(bitmap, 0, 0, TILE_SIZE, TILE_SIZE);
    bitmap.close();

    let pixels: Uint8ClampedArray;
    try {
      pixels = ctx.getImageData(0, 0, TILE_SIZE, TILE_SIZE).data;
    } catch {
      return FLAT_TILE;
    }

    const h = new Float32Array(TILE_SIZE * TILE_SIZE);
    for (let i = 0; i < h.length; i++) {
      const r = pixels[i * 4];
      const g = pixels[i * 4 + 1];
      const b = pixels[i * 4 + 2];
      h[i] = (r * 256 + g + b / 256) - 32768;
    }

    if (heightmapCache.size > 500) {
      const first = heightmapCache.keys().next().value!;
      heightmapCache.delete(first);
    }
    heightmapCache.set(url, h);
    return h;
  } catch {
    return FLAT_TILE;
  }
}

/**
 * Upsample: get a sub-region of a parent tile, bilinear-filtered to TILE_SIZE x TILE_SIZE.
 * Used when the requested level > MAX_TERRARIUM_LEVEL.
 */
async function getUpsampledTile(x: number, y: number, level: number): Promise<Float32Array> {
  const levelDiff = level - MAX_TERRARIUM_LEVEL;
  const scale = 1 << levelDiff;           // 2^levelDiff
  const parentX = Math.floor(x / scale);
  const parentY = Math.floor(y / scale);
  const subX = x - parentX * scale;       // 0..scale-1
  const subY = y - parentY * scale;

  const url = `https://s3.amazonaws.com/elevation-tiles-prod/terrarium/${MAX_TERRARIUM_LEVEL}/${parentX}/${parentY}.png`;
  const parentHeights = await decodeTerrarium(url);
  if (parentHeights === FLAT_TILE) return FLAT_TILE;

  // Sub-region in parent tile pixels
  const regionSize = TILE_SIZE / scale;   // pixels of parent that cover the child tile
  const startX = subX * regionSize;
  const startY = subY * regionSize;

  const result = new Float32Array(TILE_SIZE * TILE_SIZE);
  // Bilinear upsample the regionSize x regionSize region to TILE_SIZE x TILE_SIZE
  for (let iy = 0; iy < TILE_SIZE; iy++) {
    const srcY = startY + (iy / TILE_SIZE) * regionSize;
    const y0 = Math.floor(srcY);
    const y1 = Math.min(y0 + 1, TILE_SIZE - 1);
    const ty = srcY - y0;
    for (let ix = 0; ix < TILE_SIZE; ix++) {
      const srcX = startX + (ix / TILE_SIZE) * regionSize;
      const x0 = Math.floor(srcX);
      const x1 = Math.min(x0 + 1, TILE_SIZE - 1);
      const tx = srcX - x0;

      const h00 = parentHeights[y0 * TILE_SIZE + x0];
      const h10 = parentHeights[y0 * TILE_SIZE + x1];
      const h01 = parentHeights[y1 * TILE_SIZE + x0];
      const h11 = parentHeights[y1 * TILE_SIZE + x1];
      const h0 = h00 * (1 - tx) + h10 * tx;
      const h1 = h01 * (1 - tx) + h11 * tx;
      result[iy * TILE_SIZE + ix] = h0 * (1 - ty) + h1 * ty;
    }
  }
  return result;
}

export function createTerrainProvider(): Cesium.CustomHeightmapTerrainProvider {
  return new Cesium.CustomHeightmapTerrainProvider({
    width: TILE_SIZE,
    height: TILE_SIZE,
    tilingScheme: new Cesium.WebMercatorTilingScheme(),
    callback: (x: number, y: number, level: number) => {
      if (level < MIN_REQUEST_LEVEL) {
        return Promise.resolve(FLAT_TILE);
      }
      if (level <= MAX_TERRARIUM_LEVEL) {
        const url = `https://s3.amazonaws.com/elevation-tiles-prod/terrarium/${level}/${x}/${y}.png`;
        return decodeTerrarium(url);
      }
      // Higher zoom — upsample from level 15 parent tile
      return getUpsampledTile(x, y, level);
    },
  } as any);
}
