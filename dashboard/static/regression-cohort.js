'use strict';
// Cohort selection changes the observations and fit; axis clipping never does.
window.RegressionCohort = {
 select(points, winner = 'all') {
  if (winner !== 'trump' && winner !== 'harris') return points.slice();
  return points.filter(point => {
   const share = point.harrisShare ?? point.harris_share;
   return Number.isFinite(share) && (winner === 'trump' ? share < 50 : share > 50);
  });
 },
 fit(points) {
  if (points.length < 2 || points.some(point => !Number.isFinite(point.x) || !Number.isFinite(point.y))) return null;
  let x_min = Infinity, x_max = -Infinity;
  for (const point of points) {
   x_min = Math.min(x_min, point.x);
   x_max = Math.max(x_max, point.x);
  }
  if (x_min === x_max) return null;
  if (points.every(point => point.y === points[0].y)) {
   return {intercept: points[0].y, slope: 0, r_squared: null, x_min, x_max};
  }
  const meanX = points.reduce((sum, point) => sum + point.x, 0) / points.length;
  const meanY = points.reduce((sum, point) => sum + point.y, 0) / points.length;
  let sxx = 0, sxy = 0, sst = 0;
  for (const point of points) {
   const dx = point.x - meanX, dy = point.y - meanY;
   sxx += dx * dx;
   sxy += dx * dy;
   sst += dy * dy;
  }
  if (!(sxx > 0) || !Number.isFinite(sxx)) return null;
  const slope = sxy / sxx, intercept = meanY - slope * meanX;
  const sse = points.reduce((sum, point) => sum + (point.y - intercept - slope * point.x) ** 2, 0);
  if (!Number.isFinite(slope) || !Number.isFinite(intercept) || !Number.isFinite(sse) || !Number.isFinite(sst)) return null;
  return {intercept, slope, r_squared: sst > 0 ? Math.max(0, Math.min(1, 1 - sse / sst)) : null, x_min, x_max};
 },
 label(winner = 'all', unit = 'precincts') {
  return `${winner === 'trump' ? 'Trump-won' : winner === 'harris' ? 'Harris-won' : 'All'} ${unit}`;
 }
};
