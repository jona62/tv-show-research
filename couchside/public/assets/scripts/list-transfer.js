import { LIMITS } from './transfer.js?v=2bfd019beccdb78d';

// Manual imports preserve independent rating and saved-list membership. Check
// the complete union before the display sanitizer can trim either list.
export function mergeTransferredList(current, incoming) {
  const combine = (ours, theirs) => {
    const present = new Set(ours.map(show => show.id));
    return [...ours, ...theirs.filter(show => {
      if (present.has(show.id)) return false;
      present.add(show.id);
      return true;
    })];
  };
  const profile = combine(current.profile, incoming.profile);
  const saved = combine(current.saved, incoming.saved);
  for (const [items, limit, label] of [[profile, LIMITS.rated, 'ratings'], [saved, LIMITS.saved, 'shows in My List']]) {
    if (items.length > limit) throw new Error(`Together these lists exceed ${limit.toLocaleString('en-US')} ${label}. Your current list has not changed. Remove a few shows before adding this copy.`);
  }
  return { ...current, profile, saved, onboarded: true };
}
