// Which liked shows the picks are matched to. Pure rules over the list, kept
// apart from the page so test_similar.mjs can pin them.

// The chosen ids that are still liked shows on the list, in list order. Anything
// removed, re-rated below liked, or repeated is dropped. Below two liked shows
// there is nothing to narrow, so the choice goes along with the control.
export function prune(profile, chosen) {
  const liked = profile.filter(p => p.weight > 0);
  const wanted = new Set(chosen);
  return liked.length < 2 ? [] : liked.filter(p => wanted.has(p.id)).map(p => p.id);
}

// "Ozark", "Ozark and Dark", "Ozark, Dark and Fargo", "Ozark, Dark and 3 more".
export function few(names) {
  if (names.length > 3) return `${names[0]}, ${names[1]} and ${names.length - 2} more`;
  if (names.length > 1) return `${names.slice(0, -1).join(', ')} and ${names.at(-1)}`;
  return names[0] || '';
}
