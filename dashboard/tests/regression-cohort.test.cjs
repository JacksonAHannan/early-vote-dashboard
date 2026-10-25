const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {test} = require('node:test');
const context = {window: {}};
vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../static/regression-cohort.js'), 'utf8'), context);
const {select, fit, label} = context.window.RegressionCohort;
const close = (actual, expected, tolerance = 1e-12) => assert(Math.abs(actual - expected) < tolerance, `${actual} differs from ${expected}`);

test('winner selection uses the presidential share, strictly excluding ties and unknowns', () => {
 const shares = [0, 49.9, 50, 50.1, 100, null, undefined, NaN, Infinity, '20'];
 const points = shares.map((harrisShare, i) => ({x: i, y: 100, harrisShare}));
 assert.deepEqual(Array.from(select(points, 'trump'), point => point.harrisShare), [0, 49.9]);
 assert.deepEqual(Array.from(select(points, 'harris'), point => point.harrisShare), [50.1, 100]);
 const all = select(points);
 assert.equal(all.length, shares.length);
 assert.notEqual(all, points);
 assert.equal(all[0], points[0]);
 assert.equal(points.length, shares.length);
});

test('state snake-case presidential shares are supported without coercing nulls', () => {
 const points = [{x: 0, y: 2, harris_share: 40}, {x: 1, y: 4, harris_share: 60}, {x: 2, y: 0, harris_share: null}];
 assert.equal(select(points, 'trump').length, 1);
 assert.equal(select(points, 'harris').length, 1);
 assert.equal(select(points, 'trump')[0], points[0]);
 assert.equal(select(points, 'harris')[0], points[1]);
});

test('descriptive unweighted OLS matches the Rust noisy-fit fixture', () => {
 const points = Object.freeze([Object.freeze({x: 0, y: 1}), Object.freeze({x: 1, y: 2}), Object.freeze({x: 2, y: 2})]);
 const result = fit(points);
 close(result.intercept, 7 / 6);
 close(result.slope, .5);
 close(result.r_squared, .75);
 assert.equal(result.x_min, 0);
 assert.equal(result.x_max, 2);
});

test('centering preserves a slope when predictor values have a large common offset', () => {
 const result = fit([{x: 1e9, y: 5}, {x: 1e9 + 1, y: 7}, {x: 1e9 + 2, y: 9}]);
 close(result.slope, 2);
 close(result.intercept, 5 - 2e9);
 close(result.r_squared, 1);
});

test('insufficient, constant predictor and non-finite observations have no fit', () => {
 for (const points of [[], [{x: 1, y: 2}], [{x: 1, y: 2}, {x: 1, y: 3}], [{x: NaN, y: 1}, {x: 2, y: 2}], [{x: 0, y: Infinity}, {x: 1, y: 2}], [{x: null, y: 1}, {x: 1, y: 2}], [{x: 0, y: '1'}, {x: 1, y: 2}]]) {
  assert.equal(fit(points), null);
 }
});

test('constant response has a horizontal fit and undefined R squared', () => {
 const result = fit([{x: 0, y: .1}, {x: 50, y: .1}, {x: 100, y: .1}]);
 assert.equal(result.intercept, .1);
 assert.equal(result.slope, 0);
 assert.equal(result.r_squared, null);
});

test('each winner cohort has its own sample size and fit, retaining extreme turnout', () => {
 const points = [
  {x: 0, y: 10, harrisShare: 20}, {x: 1, y: 20, harrisShare: 30},
  {x: 0, y: 100, harrisShare: 60}, {x: 1, y: 90, harrisShare: 70},
  {x: 2, y: 10000, harrisShare: 50}
 ];
 const trump = select(points, 'trump'), harris = select(points, 'harris'), all = select(points);
 assert.equal(trump.length, 2);
 assert.equal(harris.length, 2);
 assert.equal(all.length, 5);
 close(fit(trump).slope, 10);
 close(fit(harris).slope, -10);
 assert(fit(all).slope > 1000);
 assert.equal(fit(all).x_max, 2);
 assert.equal(points.length, 5);
});

test('labels identify the selected unit and default to all precincts', () => {
 assert.equal(label(), 'All precincts');
 assert.equal(label('trump'), 'Trump-won precincts');
 assert.equal(label('harris', 'counties'), 'Harris-won counties');
});
