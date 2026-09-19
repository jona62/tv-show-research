// The "how it relates" chart: your weighted taste profile against one pick.
const NS = 'http://www.w3.org/2000/svg';
const node = (tag, attrs = {}) => {
  const el = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  return el;
};
const short = name => name.split(' / ')[0];

// Weighted share of your liked shows carrying each signal, next to the pick's own signals.
export function fitRows(liked, pick, kind, themes, genres) {
  const families = kind === 'both' ? ['themes', 'genres'] : [kind];
  const rows = [];
  for (const group of families) {
    const known = liked.filter(s => (group === 'themes' ? s.has_plot : s.genres.length));
    const total = known.reduce((n, s) => n + s.weight, 0);
    for (const name of group === 'themes' ? themes : genres) {
      const hit = known.reduce((n, s) => n + (s[group].includes(name) ? s.weight : 0), 0);
      rows.push({
        name, group,
        you: total ? Math.round(hit / total * 100) : 0,
        them: pick && pick[group].includes(name) ? 100 : 0,
      });
    }
  }
  return rows;
}

// Eight spokes that actually say something: shared ground first, then each side's strongest.
export function chooseSpokes(rows, count = 8) {
  const rank = r => (r.them && r.you >= 25 ? 400 : 0) + (r.them ? 200 : 0) + r.you;
  const ordered = [...rows].filter(r => r.you || r.them).sort((a, b) => rank(b) - rank(a) || a.name.localeCompare(b.name));
  const seen = new Set(), spokes = [];
  for (const row of ordered) {
    const label = short(row.name).toLowerCase();
    if (seen.has(label)) continue;   // a theme and a genre can share a short name
    seen.add(label);
    spokes.push(row);
    if (spokes.length === count) break;
  }
  return spokes;
}

export function drawFit(svg, frame, keyList, spokes) {
  const w = frame.clientWidth;
  if (!w || spokes.length < 3) { svg.replaceChildren(); keyList.replaceChildren(); return; }
  const tight = w < 520;
  const h = tight ? 300 : 380;
  const cx = w / 2, cy = h / 2;
  const r = tight ? Math.min(w / 2 - 30, 112) : 140;
  svg.replaceChildren();
  svg.setAttribute('viewBox', `0 0 ${w} ${h}`);
  svg.setAttribute('height', h);

  const at = (i, v, pad = 0) => {
    const a = i / spokes.length * Math.PI * 2 - Math.PI / 2;
    return [cx + Math.cos(a) * (r * v / 100 + pad), cy + Math.sin(a) * (r * v / 100 + pad)];
  };
  for (const ring of [33, 66, 100]) {
    svg.append(node('polygon', { points: spokes.map((_, i) => at(i, ring).join(',')).join(' '), class: 'radar-grid' }));
  }
  spokes.forEach((_, i) => {
    const [x, y] = at(i, 100);
    svg.append(node('line', { x1: cx, y1: cy, x2: x, y2: y, class: 'radar-spoke' }));
  });

  for (const [key, cls] of [['you', 'shape-you'], ['them', 'shape-pick']]) {
    svg.append(node('polygon', {
      points: spokes.map((s, i) => at(i, s[key]).join(',')).join(' '),
      class: `shape ${cls}`,
    }));
    spokes.forEach((s, i) => {
      const [x, y] = at(i, s[key]);
      svg.append(node('circle', { cx: x, cy: y, r: 3.2, class: `dot ${cls}` }));
    });
  }

  keyList.replaceChildren();
  keyList.hidden = !tight;
  spokes.forEach((s, i) => {
    const [x, y] = at(i, 100, tight ? 15 : 22);
    if (tight) {
      const t = node('text', { x, y: y + 4, 'text-anchor': 'middle', class: 'radar-label' });
      t.textContent = String(i + 1);
      svg.append(t);
      const li = document.createElement('li');
      li.textContent = short(s.name);
      keyList.append(li);
      return;
    }
    const anchor = x < cx - 24 ? 'end' : x > cx + 24 ? 'start' : 'middle';
    const label = node('text', { x, y, 'text-anchor': anchor, class: 'radar-label' });
    const words = short(s.name).split(' ');
    const lines = [''];
    for (const word of words) {
      if ((lines.at(-1) + ' ' + word).trim().length > 16 && lines.at(-1)) lines.push(word);
      else lines[lines.length - 1] = (lines.at(-1) + ' ' + word).trim();
    }
    lines.forEach((line, j) => {
      const span = node('tspan', { x, dy: j ? 14 : -(lines.length - 1) * 7 });
      span.textContent = line;
      label.append(span);
    });
    svg.append(label);
  });

  const caption = node('title');
  caption.textContent = spokes.map(s => `${short(s.name)}: you ${s.you}%, pick ${s.them ? 'yes' : 'no'}`).join('. ');
  svg.prepend(caption);
}

export { short };
