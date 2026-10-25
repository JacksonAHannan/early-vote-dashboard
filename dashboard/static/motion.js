'use strict';
// Action-driven motion. Final DOM values remain authoritative for analysis/export.
const Motion=window.Motion={
 preference:matchMedia('(prefers-reduced-motion: reduce)'),until:0,effects:new Set(),reveals:new WeakMap(),keys:new WeakMap(),flights:new Map(),entries:new Map(),
 active(){return !this.preference.matches&&performance.now()<this.until;},
 reveal(node,kind='section'){
  if(!node||!this.active()||!node.getClientRects().length||!node.animate)return;
  this.reveals.get(node)?.cancel();
  const effect=node.animate(kind==='chart'?[{opacity:.45},{opacity:1}]:[{opacity:.35,transform:'translateY(8px)'},{opacity:1,transform:'none'}],{duration:kind==='chart'?200:260,easing:'cubic-bezier(.2,.7,.2,1)'});
  this.effects.add(effect);this.reveals.set(node,effect);
  const cleanup=()=>{this.effects.delete(effect);if(this.reveals.get(node)===effect)this.reveals.delete(node);};effect.onfinish=cleanup;effect.oncancel=cleanup;
 },
 chart(node,key){if(!node)return;const previous=this.keys.get(node);this.keys.set(node,key);if(previous!==key)this.reveal(node,'chart');},
 fit(map,bounds,options={},animated=true,previous=null,intro=false){
  if(!bounds?.isValid()){previous?.remove();return;}
  map.invalidateSize({pan:false});this.stop(map);
  const node=map.getContainer(),box=node.getBoundingClientRect(),moving=animated&&!this.preference.matches&&node.getClientRects().length;
  if(moving&&(box.bottom<=0||box.top>=innerHeight)){
   map.fitBounds(bounds,{...options,animate:false});previous?.remove();
   const observer=new IntersectionObserver(records=>{if(records.some(r=>r.isIntersecting)){this.cancelEntry(map);this.fit(map,bounds,options,true,null,true);}},{threshold:.15});
   this.entries.set(map,observer);observer.observe(node);return;
  }
  if(!moving){map.fitBounds(bounds,{...options,animate:false});previous?.remove();return;}
  if(intro||!map._loaded)map.fitBounds(bounds.pad(.65),{...options,animate:false});
  previous?.eachLayer?.(layer=>{const node=layer.getElement?.();if(node){node.style.pointerEvents='none';node.setAttribute('tabindex','-1');}});
  const flight={bounds,options,done:()=>{previous?.remove();if(this.flights.get(map)===flight)this.flights.delete(map);}};
  this.flights.set(map,flight);map.once('moveend',flight.done);
  map.flyToBounds(bounds,{...options,duration:.7,easeLinearity:.25,animate:true});
 },
 stop(map){
  if(!map)return;this.cancelEntry(map);
  // Snap fractional flight zoom without starting Leaflet's separate CSS zoom.
  const flight=this.flights.get(map);if(flight)map.off('moveend',flight.done);
  if(map._loaded)map.setZoom(map.getZoom(),{animate:false});map.stop();flight?.done();
 },
 cancelEntry(map){this.entries.get(map)?.disconnect();this.entries.delete(map);},
 settleMap(map){this.cancelEntry(map);const flight=this.flights.get(map);if(!flight)return;this.stop(map);map.fitBounds(flight.bounds,{...flight.options,animate:false});},
 finish(){for(const map of new Set([...this.flights.keys(),...this.entries.keys()]))this.settleMap(map);for(const effect of document.getAnimations())if(Number.isFinite(effect.effect?.getComputedTiming().endTime))effect.finish();this.effects.clear();}
};
for(const event of ['click','change','keydown'])document.addEventListener(event,e=>{if(event!=='keydown'||['Enter',' ','ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(e.key))Motion.until=performance.now()+3000;},true);
Motion.preference.addEventListener('change',()=>{if(Motion.preference.matches)Motion.finish();});
