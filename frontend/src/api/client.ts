import { AreaRequest, AreaResponse, PathResponse } from '../types';

const BASE = '/api';

export async function calculateArea(req: AreaRequest): Promise<AreaResponse> {
  const res = await fetch(`${BASE}/area`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function calculatePath(req: any): Promise<PathResponse> {
  const res = await fetch(`${BASE}/path`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getElevation(lat: number, lon: number): Promise<number> {
  const res = await fetch(`${BASE}/elevation?lat=${lat}&lon=${lon}`);
  const data = await res.json();
  return data.elevation_m;
}

export async function getHealth(): Promise<any> {
  const res = await fetch(`${BASE}/health`);
  return res.json();
}

export async function getModels(): Promise<any> {
  const res = await fetch(`${BASE}/models`);
  return res.json();
}
