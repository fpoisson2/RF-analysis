import * as Cesium from 'cesium';

const TILE_SIZE = 256;
const FLAT_TILE = new Float32Array(TILE_SIZE * TILE_SIZE);
const heightmapCache = new Map<string, Float32Array>();

async function decodeTerrarium(url: string): Promise<Float32Array> {
  const cached = heightmapCache.get(url);
  if (cached) return cached;

  try {
    const response = await fetch(url);
    if (!response.ok) return FLAT_TILE;

    const blob = await response.blob();
    if (blob.size === 0) return FLAT_TILE;

    // Decode PNG to pixel data via Image element (more compatible than OffscreenCanvas)
    const imgUrl = URL.createObjectURL(blob);
    const heights = await new Promise<Float32Array>((resolve) => {
      const img = new Image();
      img.crossOrigin = 'anonymous';
      img.onload = () => {
        const canvas = document.createElement('canvas');
        canvas.width = TILE_SIZE;
        canvas.height = TILE_SIZE;
        const ctx = canvas.getContext('2d')!;
        ctx.drawImage(img, 0, 0, TILE_SIZE, TILE_SIZE);

        let pixels: Uint8ClampedArray;
        try {
          pixels = ctx.getImageData(0, 0, TILE_SIZE, TILE_SIZE).data;
        } catch {
          // CORS / tainted canvas
          resolve(FLAT_TILE);
          return;
        }

        const h = new Float32Array(TILE_SIZE * TILE_SIZE);
        for (let i = 0; i < h.length; i++) {
          const r = pixels[i * 4];
          const g = pixels[i * 4 + 1];
          const b = pixels[i * 4 + 2];
          // Terrarium encoding: height = (R * 256 + G + B / 256) - 32768
          h[i] = (r * 256 + g + b / 256) - 32768;
        }
        resolve(h);
      };
      img.onerror = () => resolve(FLAT_TILE);
      img.src = imgUrl;
    });

    URL.revokeObjectURL(imgUrl);

    // Keep cache bounded
    if (heightmapCache.size > 500) {
      const first = heightmapCache.keys().next().value!;
      heightmapCache.delete(first);
    }
    heightmapCache.set(url, heights);
    return heights;
  } catch {
    return FLAT_TILE;
  }
}

export function createTerrainProvider(): Cesium.CustomHeightmapTerrainProvider {
  return new Cesium.CustomHeightmapTerrainProvider({
    width: TILE_SIZE,
    height: TILE_SIZE,
    tilingScheme: new Cesium.WebMercatorTilingScheme(),
    callback: (x: number, y: number, level: number) => {
      if (level > 15) {
        return Promise.resolve(FLAT_TILE);
      }
      const url = `https://s3.amazonaws.com/elevation-tiles-prod/terrarium/${level}/${x}/${y}.png`;
      return decodeTerrarium(url);
    },
  } as any);
}
