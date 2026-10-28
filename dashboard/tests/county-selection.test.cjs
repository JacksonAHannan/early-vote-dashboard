const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {test} = require('node:test');
const source = fs.readFileSync(path.join(__dirname, '../static/app.js'), 'utf8').split("$('county').onchange=")[0];
function context(counties) {
 const ctx = vm.createContext({document: {}, Intl, URLSearchParams});
 vm.runInContext(source, ctx);
 ctx.fixture = counties;
 vm.runInContext("data={counties:fixture};day=1;mode='partisan';cohort='matched';",ctx);
 return ctx;
}
function county(id,old,current,groups=1) {
 const b={label:'bucket',groups,votes_2024:old,votes_2026:current,ratio:old>0?current/old:null};
 return {id,name:id,reference_groups:[{new:['1','2']}],periods:[{day:1,county_2024:old,county_2026:current,matched:b,unchanged:b,buckets:[{matched:b,unchanged:b}],coverage:{available_groups:groups,available_precincts:1,total_precincts:2,baseline_votes_2024:old+100,available_baseline_votes_2024:old}}]};
}
test('selected turnout is the ratio of vote sums, not the average county ratio',()=>{
 const ctx=context([county('a',10,20),county('b',90,45)]);
 const result=vm.runInContext("matrixAggregate(data.counties,['bucket'])",ctx);
 assert.equal(result.bins[0].ratio,.65);
 assert.equal(result.bins[0].groups,2);
 assert.equal(result.period.county_ratio,.65);
 assert.equal(result.period.coverage.available_precincts,2);
 assert.equal(result.period.coverage.total_precincts,4);
 assert.equal(result.period.coverage.baseline_votes_2024,300);
});
test('unavailable counties remain in the coverage denominator, never contribute votes',()=>{
 const a=county('a',10,20),b=county('b',900,900);b.periods[0].coverage.available_groups=0;
 const ctx=context([a,b]);
 const result=vm.runInContext("matrixAggregate(data.counties,['bucket'])",ctx);
 assert.equal(result.bins[0].votes_2024,10);
 assert.equal(result.bins[0].votes_2026,20);
 assert.equal(result.period.coverage.available_precincts,1);
 assert.equal(result.period.coverage.total_precincts,4);
});
test('empty selections and zero baselines produce unknown ratios, not zero percent',()=>{
 const ctx=context([county('a',0,20)]);
 const empty=vm.runInContext("matrixAggregate([],['bucket'])",ctx);
 assert.equal(empty.period,null);assert.equal(empty.bins[0].ratio,null);
 const zero=vm.runInContext("matrixAggregate(data.counties,['bucket'])",ctx);
 assert.equal(zero.bins[0].ratio,null);assert.equal(zero.period.county_ratio,null);
});
test('membership ignores pagination and uses the selected measure source',()=>{
 const ctx=context([county('a',10,20),county('b',90,45)]);
 const ids=()=>Array.from(vm.runInContext('matrixSelectedCounties().map(c=>c.id)',ctx));
 vm.runInContext("matrixSelected=new Set(['b','unadmitted']);matrixPage=10;",ctx);
 assert.deepEqual(ids(),['b']);
 vm.runInContext("matrixMeasure='daily';matrixDaily={counties:[fixture[1]]};matrixDailyKey=matrixDailySignature();",ctx);
 assert.deepEqual(ids(),['b']);
 vm.runInContext("matrixSelected=null;",ctx);assert.deepEqual(ids(),['b']);
 vm.runInContext("matrixDailyKey='not-ready';matrixDaily=null;",ctx);assert.deepEqual(ids(),['a','b']);
});
