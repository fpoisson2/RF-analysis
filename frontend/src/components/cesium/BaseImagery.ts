import * as Cesium from 'cesium';

export function createBaseImagery(darkMode: boolean): Cesium.UrlTemplateImageryProvider {
  const url = darkMode
    ? 'https://basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png'
    : 'https://basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png';

  return new Cesium.UrlTemplateImageryProvider({
    url,
    minimumLevel: 0,
    maximumLevel: 18,
    credit: new Cesium.Credit('&copy; <a href="https://carto.com/">CARTO</a> &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'),
  });
}
