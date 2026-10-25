const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const {test}=require('node:test');
const context={window:{}};
vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../static/regression-scale.js'),'utf8'),context);
const scale=context.window.RegressionScale.calculate;

test('an extreme turnout ratio does not flatten the central pattern',()=>{
 const values=Array.from({length:100},(_,i)=>80+i/5).concat([0,10000]);
 const result=scale(values);
 assert(result.min>0&&result.max<120);
 assert.equal(result.above,1);assert.equal(result.below,1);
 assert(values.slice(0,100).every(v=>v>=result.min&&v<=result.max));
 assert.equal(values.length,102);
});
test('automatic domains can sit entirely below or above the 100% reference',()=>{
 const below=scale([10,12,14,16,18,20,22,24]);
 const above=scale([160,162,164,166,168,170,172,174]);
 assert(below.max<100);assert(above.min>100);
});
test('a constant cluster remains legible despite outliers and equal quartiles',()=>{
 const result=scale(Array(100).fill(80).concat([0,10000]));
 assert(result.min<80&&result.max>80&&result.max-result.min>=10);
 assert(result.max<100&&result.min>0);
 assert.equal(result.above+result.below,2);
});
test('small samples retain all observations',()=>{
 const result=scale([80,81,10000]);
 assert(result.min<=80&&result.max>=10000);
 assert.equal(result.above+result.below,0);
});
test('full range reveals every observation and fixed focus remains available',()=>{
 const result=scale([0,80,10000],'full');
 assert.equal(result.min,0);assert(result.max>10000);
 assert.equal(result.above+result.below,0);
 const fixed=scale([0,80,10000],'focus');
 assert.equal(fixed.min,60);assert.equal(fixed.max,150);assert.equal(fixed.step,10);
});
test('empty, zero, single and invalid inputs yield finite usable ticks',()=>{
 for(const values of [[],[0],[80],[Infinity,NaN,-1,80],Array(5).fill(0)]){
  const result=scale(values);
  assert(Number.isFinite(result.min)&&Number.isFinite(result.max)&&result.min>=0);
  assert(result.max>result.min&&result.step>0);
  assert(result.ticks.length>=2&&result.ticks.length<=12);
  assert.equal(result.ticks[0],result.min);assert.equal(result.ticks.at(-1),result.max);
  assert(result.ticks.every(Number.isFinite));
 }
});
