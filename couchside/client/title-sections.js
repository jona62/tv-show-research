// The title page's existing cards and faces, using the same reveal as its trailers.
let currentObserver;

export function mountTitleSections(t,{revealButton,paintReveal,unfold,busy,edges}) {
  currentObserver?.disconnect();
  const parts=new Map();
  const observer=new ResizeObserver(()=>{
    for(const part of parts.values())if(part.list.isConnected&&!busy(part.list))part.set(t.open[part.key]);
  });
  currentObserver=observer;
  t.sectionsDispose=()=>observer.disconnect();

  function attach(key,list,label,faces=false) {
    const previous=parts.get(key);
    if(previous?.list===list){previous.set(t.open[key]);return;}
    if(previous){observer.unobserve(previous.list);previous.button.parentElement.remove();parts.delete(key);}
    if(!list||list.querySelector('.skel-item')||!list.children.length)return;
    t.open[key]??=false;
    list.id=`ratings-title-${key}`;
    list.classList.add('ratings-title-list');
    list.setAttribute('aria-label',label);
    const part={key,list,button:null,set:open=>{
      const capacity=matchMedia('(min-width:760px)').matches?(faces?6:4):(faces?3:2);
      const clipped=list.children.length>capacity,rail=clipped&&!open;
      const turned=list.classList.contains('rail')!==rail;
      list.classList.toggle('rail',rail);
      if(turned)list.scrollLeft=0;
      part.button.parentElement.hidden=!clipped;
      paintReveal(part.button,open?'Show fewer':`Show all (${list.children.length})`,open);
      edges(list);
    }};
    part.button=revealButton(list,()=>{
      if(busy(list))return;
      t.open[key]=!t.open[key];
      unfold(list,part.set,t.open[key],part.button);
    });
    list.after(part.button.parentElement);
    list.addEventListener('scroll',()=>edges(list),{passive:true});
    parts.set(key,part);part.set(t.open[key]);observer.observe(list);
  }
  t.sectionsUpdate=()=>{
    attach('more',t.moreList,'More like this');
    attach('fans',t.fansList,'Fans also like');
    attach('cast',t.about.querySelector('.cast'),'Cast',true);
  };
}
