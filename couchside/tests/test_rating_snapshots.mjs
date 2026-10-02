import assert from 'node:assert/strict';
import test from 'node:test';
import {planRatingSnapshot, renderRatingSnapshot, prepareRatingSnapshot, downloadRatingSnapshot,
  pngArchive, SNAPSHOT_LIMITS} from '../client/rating-snapshots.js';
import {comparisonOverlayPlan} from '../client/comparison-timeline.js';

const episodes = (count, annual=false) => Array.from({length:count}, (_, index) => ({
  id:index + 1, season:annual ? 1999 + Math.floor(index / 42) : 1,
  number:annual ? index % 42 + 1 : index + 1, name:'Episode ' + (index + 1),
  rating:index % 9 === 0 ? null : 6 + index % 9 / 2, airdate:'2026-01-01', runtime:30,
}));
const detail = (view, count=12, extra={}) => ({kind:'detail', id:16149, title:'Fleabag', year:2016,
  poster:'fleabag.jpg', season:'all', inverted:false, averages:true, sources:'TVmaze / TMDB',
  view, episodes:episodes(count), ...extra});
const compare = (inverted, count=11, episodeCount=401) => ({kind:'compare', mode:'single', inverted,
  averages:true, shows:Array.from({length:count}, (_, index) => ({id:index + 100, name:'Show ' + index,
    season:1, year:2026, poster:index % 3 === 0 ? null : `show-${index}.jpg`, sources:'TVmaze',
    episodes:episodes(episodeCount).map(episode => ({...episode, id:episode.id + 10000 * index})),
  }))});
const timelineCompare = (extra={}) => ({...compare(false, 5, 62), view:'timeline', mode:'all',
  timelineLayout:'row', pointStyle:'show', ...extra});
const artFor = model => new Map((model.kind === 'compare' ? model.shows : [model])
  .filter(show => show.poster).map(show => [show.poster, {naturalWidth:600, naturalHeight:900}]));

function harness(options={}) {
  const canvases = [];
  function createCanvas() {
    const canvas = {width:0, height:0, posters:[], texts:[], rectangles:[], paths:[], pathColors:[], dots:[]};
    let tx=0, ty=0; const states=[];
    const context = {
      font:'400 14px sans-serif', textAlign:'left', textBaseline:'alphabetic',
      save() { states.push({tx, ty, font:this.font, align:this.textAlign}); },
      restore() { const state=states.pop(); if (state) { tx=state.tx; ty=state.ty; this.font=state.font; this.textAlign=state.align; } },
      translate(x, y) { tx+=x; ty+=y; }, scale() {},
      measureText(value) { return {width:String(value).length * Number(this.font.match(/([\d.]+)px/)?.[1] || 14) * .52}; },
      fillText(value, x, y) {
        const width=this.measureText(value).width;
        const left=this.textAlign === 'center' ? x-width/2 : this.textAlign === 'right' ? x-width : x;
        canvas.texts.push({value, left:left+tx, right:left+tx+width, y:y+ty});
      },
      drawImage(image, ...geometry) { const [x, y, width, height]=geometry; canvas.posters.push({x:x+tx, y:y+ty, width, height, arguments:geometry.length}); },
      fillRect(x, y, width, height) { canvas.rectangles.push({x:x+tx, y:y+ty, width, height}); },
      roundRect(x, y, width, height) { this.fillRect(x, y, width, height); },
      createLinearGradient() { return {addColorStop() {}}; },
      stroke(path) { if (path) { canvas.paths.push(path.value); canvas.pathColors.push(this.strokeStyle); } },
      beginPath() { this.currentArc=null; }, clip() {},
      rect(x,y,width,height) { this.fillRect(x,y,width,height); },
      fill() { if (this.currentArc) canvas.dots.push({...this.currentArc, color:this.fillStyle}); },
      arc(x,y,radius) { this.currentArc={x:x+tx,y:y+ty,radius}; }, moveTo() {}, lineTo() {},
    };
    canvas.getContext = () => options.noContext ? null : context;
    canvas.toBlob = callback => {
      canvas.logicalWidth=canvas.width/2; canvas.logicalHeight=canvas.height/2;
      if (options.throwEncode) throw Error('SecurityError');
      callback(options.nullEncode ? null : new Blob([new Uint8Array([137,80,78,71,13,10,26,10])], {type:'image/png'}));
    };
    canvases.push(canvas); return canvas;
  }
  return {canvases, createCanvas, createPath:value => ({value})};
}

function checkCoverage(model, parts) {
  const actual=parts.flatMap(part => part.kind === 'matrix'
    ? part.rows.flatMap(row => row.cells.slice(part.columnStart, part.columnStart+part.headers.length)
      .filter(cell => cell?.episode).map(cell => cell.episode.id))
    : part.kind === 'comparison-timeline' ? part.groupIndex === 0
      ? part.plot.series.flatMap(series => series.points.map(point => point.id)) : []
    : part.kind === 'wrapped' ? part.sections.flatMap(section => section.episodes.map(episode => episode.id))
    : part.episodes.map(episode => episode.id));
  const expected=(model.kind === 'compare' ? model.shows.flatMap(show => show.episodes) : model.episodes).map(episode => episode.id);
  assert.deepEqual(actual.toSorted((a,b)=>a-b), expected.toSorted((a,b)=>a-b));
}

const longTitle='The unusually long title of a continuing dramatic television show '.repeat(6);
const cases=[];
for (const annual of [false, true]) for (const view of ['grid','wrapped','list','timeline']) {
  cases.push({name:`${annual ? '1,181 annual-season' : '2,048 single-season'} episodes in ${view}`,
    model:detail(view, 0, {title:longTitle, episodes:episodes(annual ? 1181 : 2048, annual)})});
}
cases.push({name:'inverted annual-season Grid', model:detail('grid', 0, {inverted:true, episodes:episodes(1181, true)})});
for (const inverted of [false,true]) cases.push({name:`11 shows and 401 episodes, shows in ${inverted ? 'columns' : 'rows'}`, model:compare(inverted)});
for (const view of ['grid','wrapped','list','timeline']) cases.push({name:`empty ${view}`, model:detail(view, 0, {poster:null})});
for (const timelineLayout of ['row','side','compact']) for (const averages of [false,true]) {
  const model=timelineCompare({timelineLayout, averages});
  model.shows=model.shows.map((show,index)=>({...show,
    episodes:episodes([62,12,5,1181,32][index],index===3).map(episode=>({...episode,id:episode.id+10000*index}))}));
  cases.push({name:`shared comparison timeline ${timelineLayout}, averages ${averages}`,model});
}

for (const {name,model} of cases) test(name, async () => {
  const before=structuredClone(model), parts=planRatingSnapshot(model), drawing=harness();
  checkCoverage(model, parts);
  assert.ok(parts.length);
  const pages=await renderRatingSnapshot(model, artFor(model), drawing);
  assert.equal(pages.length, parts.length); assert.deepEqual(model, before);
  for (const [index, page] of pages.entries()) {
    const canvas=drawing.canvases[index], {logicalWidth:width, logicalHeight:height}=canvas;
    assert.ok(width <= SNAPSHOT_LIMITS.width && height <= SNAPSHOT_LIMITS.height);
    assert.ok(width*height*4 <= SNAPSHOT_LIMITS.pixels);
    assert.deepEqual([canvas.width,canvas.height], [1,1], 'the backing bitmap is released after each part');
    assert.ok(page.blob instanceof Blob); assert.equal(page.blob.type,'image/png');
    for (const box of [...canvas.posters, ...canvas.rectangles])
      assert.ok(box.x >= 0 && box.y >= 0 && box.x+box.width <= width+.001 && box.y+box.height <= height+.001);
    for (const text of canvas.texts)
      assert.ok(text.left >= 0 && text.right <= width+.01 && text.y <= height, `Clipped text: ${text.value}`);
    if (model.kind === 'detail' && model.poster) {
      assert.ok(canvas.posters.some(box => box.width===160 && box.height===240), 'each continuation repeats its full-size poster');
    }
    if (parts.length>1) assert.match(page.label,new RegExp(`^Part ${index+1} of ${parts.length}`));
  }
});

test('the full portrait and landscape images are contained, never cropped', async () => {
  for (const [naturalWidth,naturalHeight] of [[600,900],[900,600]]) {
    const model=detail('timeline'), drawing=harness();
    await renderRatingSnapshot(model,new Map([[model.poster,{naturalWidth,naturalHeight}]]),drawing);
    const [poster]=drawing.canvases[0].posters;
    assert.equal(poster.arguments,4,'drawImage receives the entire source image');
    assert.equal(poster.width/poster.height,naturalWidth/naturalHeight);
    assert.ok(poster.width<=160 && poster.height<=240);
    assert.equal(poster.x+poster.width/2,116); assert.equal(poster.y+poster.height/2,186);
  }
});

test('comparison poster arrangements repeat full art, ordered show colors and the captured scopes', async () => {
  for (const timelineLayout of ['row','side','compact']) {
    const model=timelineCompare({timelineLayout}), drawing=harness(), parts=planRatingSnapshot(model);
    await renderRatingSnapshot(model,artFor(model),drawing);
    const part=parts[0], canvas=drawing.canvases[0], posterWidth=timelineLayout==='compact'?120:160;
    assert.deepEqual(part.cards.map(card=>card.series.show.id),model.shows.map(show=>show.id));
    assert.deepEqual(part.plot.series.map(series=>series.colour),comparisonOverlayPlan(model).series.map(series=>series.colour));
    assert.ok(canvas.posters.every(poster=>poster.width===posterWidth && poster.height===posterWidth*1.5));
    assert.ok(canvas.texts.some(text=>text.value==='Each show ends at its last episode'));
    assert.ok(canvas.texts.some(text=>text.value==='Episode ratings'));
    assert.ok(canvas.texts.some(text=>text.value==='5-episode average'));
    assert.ok(!canvas.texts.some(text=>text.value.startsWith('Absolute cinema ')), 'default show colors omit the rating-color legend');
    const expectedColors=new Set(part.plot.series.map(series=>series.colour));
    assert.ok(canvas.pathColors.every(color=>expectedColors.has(color)));
  }
  const three=timelineCompare({timelineLayout:'side',shows:timelineCompare().shows.slice(0,3)}), part=planRatingSnapshot(three)[0];
  assert.equal(part.cards[0].y,part.cards[1].y);
  assert.notEqual(part.cards[0].x,part.cards[1].x);
  assert.ok(part.cards[2].y>part.cards[0].y);
  assert.ok(part.height<1200,'three-show side arrangement uses two poster rows');
});

test('all point styles retain show-colored raw/average paths; average-off hides the second plot and mean labels', async () => {
  for (const pointStyle of ['show','rating','none']) for (const averages of [false,true]) {
    const model=timelineCompare({pointStyle,averages}), drawing=harness();
    await renderRatingSnapshot(model,artFor(model),drawing);
    const canvas=drawing.canvases[0], part=planRatingSnapshot(model)[0];
    assert.equal(canvas.texts.some(text=>text.value==='5-episode average'),averages);
    assert.equal(canvas.texts.some(text=>text.value.startsWith('Avg. ')),averages);
    assert.equal(canvas.texts.some(text=>text.value.startsWith('Absolute cinema ')),pointStyle==='rating');
    assert.ok(!canvas.dots.some(dot=>dot.y>=part.chartY+338),'ordinary average samples stay line-only');
    if(pointStyle==='none')assert.equal(canvas.dots.length,0);
    assert.ok(canvas.pathColors.every(color=>part.plot.series.some(series=>series.colour===color)));
  }
});

test('shared continuation indices preserve complete data, contextual connections and full-season mean windows', () => {
  const model=timelineCompare({shows:timelineCompare().shows.slice(0,2)});
  model.shows[0].episodes=episodes(10000,true).map((episode,index)=>({...episode,
    rating:index>=1090&&index<=1110?null:episode.rating}));
  model.shows[1].episodes=episodes(12).map(episode=>({...episode,id:episode.id+20000}));
  const original=comparisonOverlayPlan(model), means=new Map(original.series[0].trendPoints.map(point=>[point.id,point.rating]));
  const parts=planRatingSnapshot(model); checkCoverage(model,parts);
  assert.ok(parts.length>1);
  for(const part of parts) {
    const series=part.plot.series[0];
    assert.ok(part.plot.spacing>=1);
    assert.ok(part.plot.axis.labels.every(label=>label.episodeIndex>=part.plot.start+1&&label.episodeIndex<=part.plot.end));
    for(const point of series.trendPoints)assert.equal(point.rating,means.get(point.id));
    if(part.plot.start)assert.ok(series.runs[0].some(point=>point.sampleIndex<part.plot.start));
    if(part.plot.end<10000)assert.ok(series.trend[0].some(point=>point.sampleIndex>=part.plot.end));
    if(part.plot.start>=12)assert.equal(part.plot.series[1].points.length,0,'short show never expands to later episode positions');
    assert.ok(part.cards.every(card=>card.posterWidth===160&&card.posterHeight===240));
  }
});

test('forty-show overlays paginate full posters without omitting lines or overflowing any canvas', async () => {
  for (const timelineLayout of ['row','side','compact']) for (const rated of [false,true]) {
    const model=timelineCompare({...compare(false,40,16),view:'timeline',mode:'all',timelineLayout,
      shows:compare(false,40,16).shows.map((show,index)=>({...show,
        episodes:show.episodes.map(episode=>({...episode,rating:rated&&index%3===0?episode.rating:null}))}))});
    const parts=planRatingSnapshot(model), drawing=harness(); checkCoverage(model,parts);
    const pages=await renderRatingSnapshot(model,artFor(model),drawing);
    assert.equal(pages.length,parts.length);
    assert.deepEqual(parts.flatMap(part=>part.cards.map(card=>card.series.show.id)),model.shows.map(show=>show.id));
    for(const [index,part] of parts.entries()) {
      assert.equal(part.plot.series.length,40);
      assert.ok(part.width<=1600&&part.height<=1800&&part.width*part.height*4<=SNAPSHOT_LIMITS.pixels);
      for(const text of drawing.canvases[index].texts)assert.ok(text.left>=0&&text.right<=part.width+.01&&text.y<=part.height);
      assert.deepEqual([drawing.canvases[index].width,drawing.canvases[index].height],[1,1]);
    }
  }
});

test('single selected scopes, year numbering, missing ratings and one-sample timeline exports stay truthful', async () => {
  for(const ratings of [[],[null],[8.3],[null,null]]) {
    const show={id:100, name:'Annual show', season:2001, year:1999, poster:'annual.jpg',sources:'TVmaze',
      episodes:ratings.map((rating,index)=>({id:index+1,season:2001,number:index+1,rating}))};
    const model=timelineCompare({mode:'single',pointStyle:'none',shows:[show]}), drawing=harness();
    const parts=planRatingSnapshot(model); checkCoverage(model,parts);
    await renderRatingSnapshot(model,artFor(model),drawing);
    assert.ok(drawing.canvases[0].texts.some(text=>text.value==='1999 · 2001 season'));
    assert.ok(parts[0].plot.series[0].points.every(point=>Number.isFinite(point.x)));
    if(ratings[0]===8.3) {
      assert.equal(drawing.canvases[0].dots.length,1,'Lines only retains a single real mean, no raw dot');
      assert.ok(drawing.canvases[0].dots[0].y>=parts[0].chartY+338);
    }
  }
});

test('low-rated comparisons retain readable y-label spacing at both endpoints in both panels', async () => {
  const show={id:100,name:'Low ratings',season:1,poster:null,sources:'TVmaze',
    episodes:[2.4,9].map((rating,index)=>({id:index+1,season:1,number:index+1,rating}))};
  const model=timelineCompare({shows:[show]}), drawing=harness(), part=planRatingSnapshot(model)[0];
  await renderRatingSnapshot(model,artFor(model),drawing);
  for(const row of [{top:36,bottom:244},{top:338,bottom:426}]) {
    const labels=drawing.canvases[0].texts.filter(text=>text.right===part.chartX-12&&/^\d+\.\d+$/.test(text.value)&&
      text.y>=part.chartY+row.top+4&&text.y<=part.chartY+row.bottom+4).toSorted((left,right)=>left.y-right.y);
    assert.ok(labels.length>=2);
    for(let index=1;index<labels.length;index++)assert.ok(labels[index].y-labels[index-1].y>=18-1e-8);
  }
});

test('the pending download freezes selected view, ratings, show order and season before images arrive', async () => {
  const model=compare(true,2,8), drawing=harness(); let resolveImages, requested;
  const expected=structuredClone(model);
  const preparing=prepareRatingSnapshot(model, {...drawing,loadImages:captured => {
    requested=captured; return new Promise(resolve => {resolveImages=resolve;});
  }});
  model.inverted=false; model.mode='all'; model.shows.reverse(); model.shows[0].season=8;
  model.shows[0].episodes[0].rating=1; model.shows[0].poster='changed.jpg';
  assert.deepEqual(requested,expected); resolveImages(artFor(expected));
  const result=await preparing;
  assert.deepEqual(result.model,expected); assert.match(result.filename,/single-season\.png$/);
  assert.equal(result.pages.length,1); assert.equal(result.blob,result.pages[0].blob);
});

test('pending comparison timeline export freezes layout, point mode, averages and independent selected seasons', async () => {
  const model=timelineCompare({mode:'single',timelineLayout:'compact',pointStyle:'rating',averages:false,
    shows:timelineCompare().shows.slice(0,2).map((show,index)=>({...show,season:index+2,colour:index?'#d47e6e':'#56ec55'}))});
  const expected=structuredClone(model), drawing=harness(); let resolveImages, requested;
  const pending=prepareRatingSnapshot(model,{...drawing,loadImages:captured=>{
    requested=captured;return new Promise(resolve=>{resolveImages=resolve;});
  }});
  model.view='grid';model.timelineLayout='side';model.pointStyle='none';model.averages=true;model.mode='all';
  model.shows.reverse();model.shows[0].season=1999;model.shows[0].episodes[0].rating=1;model.shows[0].poster='new.jpg';
  model.shows[0].colour='#123456';model.shows[1].colour='#abcdef';
  assert.deepEqual(requested,expected);resolveImages(artFor(expected));
  const result=await pending;
  assert.deepEqual(result.model,expected);assert.match(result.filename,/-timeline-single-season\.png$/);
  assert.ok(!drawing.canvases[0].texts.some(text=>text.value==='5-episode average'));
  assert.ok(drawing.canvases[0].posters.every(poster=>poster.width===120&&poster.height===180));
  assert.deepEqual(new Set(drawing.canvases[0].pathColors),new Set(['#56ec55','#d47e6e']), 'The exported lines retain the colors captured before images finish loading');
});

test('PNG encoding failures release the canvas and explicitly reject the snapshot', async () => {
  for (const options of [{nullEncode:true},{throwEncode:true},{noContext:true}]) {
    const drawing=harness(options), model=detail('grid');
    await assert.rejects(renderRatingSnapshot(model,artFor(model),drawing),/could not save|could not be saved|unavailable/);
    assert.deepEqual([drawing.canvases[0].width,drawing.canvases[0].height],[1,1]);
  }
});

test('the ZIP contains each complete PNG and a valid central directory with matching CRC and offsets', async () => {
  const files=[{filename:'couchside-first-part-01.png',blob:new Blob(['123456789'])},
    {filename:'couchside-second-part-02.png',blob:new Blob([new Uint8Array([137,80,78,71])])}];
  const blob=await pngArchive(files,new Date(2026,9,2,12,34,56));
  assert.equal(blob.type,'application/zip');
  const data=new Uint8Array(await blob.arrayBuffer()), view=new DataView(data.buffer), decoder=new TextDecoder();
  const end=data.length-22;
  assert.equal(view.getUint32(end,true),0x06054b50);
  assert.equal(view.getUint16(end+8,true),2); assert.equal(view.getUint16(end+10,true),2);
  const centralStart=view.getUint32(end+16,true), centralSize=view.getUint32(end+12,true);
  assert.equal(centralStart+centralSize,end);
  let directory=centralStart;
  for (const [index,file] of files.entries()) {
    assert.equal(view.getUint32(directory,true),0x02014b50);
    const length=view.getUint16(directory+28,true), offset=view.getUint32(directory+42,true);
    assert.equal(view.getUint32(offset,true),0x04034b50);
    assert.equal(view.getUint16(offset+8,true),0,'PNG data is stored without another compression layer');
    assert.equal(decoder.decode(data.slice(directory+46,directory+46+length)),file.filename);
    assert.equal(decoder.decode(data.slice(offset+30,offset+30+length)),file.filename);
    const bytes=new Uint8Array(await file.blob.arrayBuffer()), size=view.getUint32(offset+18,true);
    assert.equal(size,bytes.length);
    assert.deepEqual(data.slice(offset+30+length,offset+30+length+size),bytes);
    assert.equal(view.getUint32(offset+14,true),view.getUint32(directory+16,true));
    if (!index) assert.equal(view.getUint32(offset+14,true),0xcbf43926,'the standard CRC32 test vector is correct');
    directory+=46+length;
  }
  assert.equal(directory,end);
});

test('large prepared snapshots package all labeled continuation PNG files', async () => {
  const model=detail('wrapped',2048), drawing=harness();
  const result=await prepareRatingSnapshot(model,{...drawing,loadImages:async () => artFor(model)});
  assert.ok(result.pages.length>1); assert.equal(result.blob.type,'application/zip');
  assert.match(result.filename,/-all-parts\.zip$/);
  assert.ok(result.pages.every((page,index)=>page.filename.endsWith(`-part-${String(index+1).padStart(2,'0')}.png`)));
});

test('downloads use an attached anchor and keep the Blob URL available for Safari', async () => {
  const previous={document:globalThis.document,Path2D:globalThis.Path2D,setTimeout:globalThis.setTimeout,
    create:URL.createObjectURL,revoke:URL.revokeObjectURL};
  const drawing=harness(), events=[]; let cleanup;
  const link={click(){events.push('click');},remove(){events.push('remove');}};
  globalThis.document={createElement:type => type==='canvas' ? drawing.createCanvas() : link,
    body:{append(node){assert.equal(node,link);events.push('append');}}};
  globalThis.Path2D=class {constructor(value){this.value=value;}};
  URL.createObjectURL=blob=>{assert.equal(blob.type,'image/png');return 'blob:rating-test';};
  URL.revokeObjectURL=url=>{assert.equal(url,'blob:rating-test');events.push('revoke');};
  globalThis.setTimeout=(callback,delay)=>{assert.equal(delay,60000);cleanup=callback;return 1;};
  try {
    const result=await downloadRatingSnapshot(detail('grid',12,{poster:null}));
    assert.deepEqual(events,['append','click','remove']); assert.equal(link.href,'blob:rating-test');
    assert.equal(link.download,result.filename); cleanup(); assert.deepEqual(events,['append','click','remove','revoke']);
  } finally {
    globalThis.document=previous.document; globalThis.Path2D=previous.Path2D; globalThis.setTimeout=previous.setTimeout;
    URL.createObjectURL=previous.create; URL.revokeObjectURL=previous.revoke;
  }
});
