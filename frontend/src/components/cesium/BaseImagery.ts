import * as Cesium from 'cesium';

export function createBaseImagery(darkMode: boolean): Cesium.ImageryProvider {
  if (darkMode) {
    // CARTO dark_all with subdomains for load balancing
    return new Cesium.UrlTemplateImageryProvider({
      url: 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png',
      subdomains: ['a', 'b', 'c', 'd'],
      minimumLevel: 0,
      maximumLevel: 19,
      credit: new Cesium.Credit('&copy; <a href="https://carto.com/">CARTO</a>'),
    });
  }
  // Light mode: use OpenStreetMap directly
  return new Cesium.OpenStreetMapImageryProvider({
    url: 'https://tile.openstreetmap.org/',
    maximumLevel: 19,
  });
}
