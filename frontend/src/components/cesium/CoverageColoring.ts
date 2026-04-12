import { ParsedBuilding } from './SceneLoader';

export async function sampleBuildingSignals(
  buildings: ParsedBuilding[],
): Promise<Map<number, number>> {
  const signalMap = new Map<number, number>();
  const points: number[][] = [];
  const indices: number[] = [];

  for (let i = 0; i < buildings.length; i++) {
    const b = buildings[i];
    if (b.centroidLat && b.centroidLon) {
      points.push([b.centroidLat, b.centroidLon]);
      indices.push(i);
    }
  }

  if (points.length === 0) return signalMap;

  const chunkSize = 50000;
  for (let start = 0; start < points.length; start += chunkSize) {
    try {
      const resp = await fetch('/api/coverage/sample', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ points: points.slice(start, start + chunkSize) }),
      });
      if (!resp.ok) continue;
      const { values } = await resp.json();
      for (let j = 0; j < values.length; j++) {
        if (values[j] != null) {
          signalMap.set(indices[start + j], values[j]);
        }
      }
    } catch (e) {
      console.warn('Coverage sample failed:', e);
    }
  }

  return signalMap;
}
