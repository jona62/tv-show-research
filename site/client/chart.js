const NS='http://www.w3.org/2000/svg';
function node(tag,attrs={},text=''){
  const el=document.createElementNS(NS,tag);
  for(const [k,v] of Object.entries(attrs))el.setAttribute(k,v);
  if(text)el.textContent=text;
  return el;
}
export function drawMap(svg,frame,tip,points,selected,onSelect,axes){
  const w=frame.clientWidth,h=w<500?320:345,m={l:48,r:15,t:22,b:60};
  if(!w)return;
  svg.setAttribute('viewBox',`0 0 ${w} ${h}`);svg.setAttribute('height',h);svg.replaceChildren();tip.style.display='none';
  svg.append(node('title',{},`Content similarity to ${axes.x} horizontally and ${axes.y} vertically. Use the show selector for accessible details.`));
  if(!points.length)return;
  const domain=key=>{const values=points.map(p=>p[key]);return [Math.max(0,Math.floor((Math.min(...values)-4)/10)*10),Math.min(100,Math.ceil((Math.max(...values)+4)/10)*10)];};
  const xd=domain('x'),yd=domain('y');
  const x=v=>m.l+8+(v-xd[0])/Math.max(1,xd[1]-xd[0])*(w-m.l-m.r-16);
  const y=v=>h-m.b-8-(v-yd[0])/Math.max(1,yd[1]-yd[0])*(h-m.b-m.t-16);
  const tick=(axis,lo,hi)=>{for(let v=lo;v<=hi;v+=20){
    if(axis==='x'){svg.append(node('line',{x1:x(v),x2:x(v),y1:m.t,y2:h-m.b,class:'grid'}));svg.append(node('text',{x:x(v),y:h-m.b+20,'text-anchor':'middle'},String(v)));}
    else{svg.append(node('line',{x1:m.l,x2:w-m.r,y1:y(v),y2:y(v),class:'grid'}));svg.append(node('text',{x:m.l-9,y:y(v)+4,'text-anchor':'end'},String(v)));}
  }};
  tick('x',...xd);tick('y',...yd);
  svg.append(node('text',{x:(w+m.l-m.r)/2,y:h-8,'text-anchor':'middle'},'Horizontal similarity (0–100)'));
  svg.append(node('text',{transform:`translate(13,${(h+m.t-m.b)/2}) rotate(-90)`,'text-anchor':'middle'},'Vertical similarity (0–100)'));
  const coords=points.map(p=>({...p,cx:x(p.x),cy:y(p.y)}));
  for(const p of coords.filter(p=>!p.seed))svg.append(node('circle',{cx:p.cx,cy:p.cy,r:p.id===selected?6:3.7,class:p.id===selected?'selected':'candidate'}));
  for(const p of coords.filter(p=>p.seed))svg.append(node('path',{d:`M${p.cx} ${p.cy-6}l4.7 6-4.7 6-4.7-6Z`,class:'favorite'}));
  const p=coords.find(p=>p.id===selected);
  if(p){
    const right=p.cx>w*.58;
    const label=node('text',{x:p.cx+(right?-10:10),y:p.cy-11,'text-anchor':right?'end':'start',class:'annotation'},p.name);svg.append(label);
    while(label.getBBox().width>w-m.l-m.r-8&&label.textContent.length>5)label.textContent=label.textContent.slice(0,-2)+'…';
    const box=label.getBBox();
    if(box.x<m.l){label.setAttribute('x',m.l+4);label.setAttribute('text-anchor','start');}
    if(box.x+box.width>w-m.r){label.setAttribute('x',w-m.r-4);label.setAttribute('text-anchor','end');}
    if(box.y<m.t)label.setAttribute('y',p.cy+23);
  }
  const overlay=node('rect',{x:m.l,y:m.t,width:w-m.l-m.r,height:h-m.t-m.b,fill:'transparent'});
  function nearest(event){const r=svg.getBoundingClientRect(),mx=(event.clientX-r.left)*w/r.width,my=(event.clientY-r.top)*h/r.height;return coords.reduce((a,b)=>(a.cx-mx)**2+(a.cy-my)**2<(b.cx-mx)**2+(b.cy-my)**2?a:b);}
  overlay.addEventListener('click',e=>onSelect(nearest(e).id));
  overlay.addEventListener('pointermove',e=>{if(e.pointerType==='touch')return;const p=nearest(e);tip.textContent=`${p.name} · horizontal ${p.x.toFixed(1)}, vertical ${p.y.toFixed(1)}`;tip.style.display='block';tip.style.left=Math.max(0,Math.min(w-245,p.cx+12))+'px';tip.style.top=Math.max(0,p.cy-36)+'px';});
  overlay.addEventListener('pointerleave',()=>tip.style.display='none');svg.append(overlay);
}
