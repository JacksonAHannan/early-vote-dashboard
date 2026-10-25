'use strict';
// A viewport policy only. Fits and exports retain their complete input cohort.
window.RegressionScale={
 calculate(values,mode='auto'){
  const sorted=values.filter(v=>Number.isFinite(v)&&v>=0).slice().sort((a,b)=>a-b);
  const quantile=q=>{const p=(sorted.length-1)*q,i=Math.floor(p);return sorted[i]+(sorted[Math.min(i+1,sorted.length-1)]-sorted[i])*(p-i);};
  let core=sorted.length?sorted:[100];
  if(mode==='auto'&&sorted.length>=5){
   const q1=quantile(.25),q3=quantile(.75),spread=Math.max(1,q3-q1);
   core=sorted.filter(v=>v>=q1-1.5*spread&&v<=q3+1.5*spread);
  }
  let min,max,step;
  if(mode==='focus'){min=60;max=150;step=10;}
  else{
   if(mode==='full'){min=0;max=Math.max(100,sorted.at(-1)||0)*1.06;}
   else{
    const low=core[0],high=core.at(-1),center=low+(high-low)/2,span=Math.max(10,center*.1,high-low);
    min=Math.max(0,center-span*.58);max=min+span*1.16;
   }
   const rough=(max-min)/5,power=10**Math.floor(Math.log10(rough));
   step=[1,2,5,10].map(v=>v*power).find(v=>v>=rough);
   min=Math.floor(min/step)*step;max=Math.ceil(max/step)*step;
  }
  const clean=v=>Number(v.toPrecision(12));min=clean(min);max=clean(max);step=clean(step);
  const ticks=Array.from({length:Math.round((max-min)/step)+1},(_,i)=>clean(min+i*step));
  return {mode,min,max,step,ticks,below:sorted.filter(v=>v<min).length,above:sorted.filter(v=>v>max).length};
 }
};
