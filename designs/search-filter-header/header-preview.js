const nav = document.getElementById('nav');
const find = document.getElementById('find');
const input = document.getElementById('q');
const search = document.getElementById('find-open');
const filters = document.getElementById('filter-open');
const searchShape = '<span class="i"><svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><path d="M20.5 20.5l-4.3-4.3"/></svg></span>';
const backShape = '<span class="i"><svg viewBox="0 0 24 24"><path d="M15 18l-6-6 6-6"/></svg></span>';
find.insertBefore(filters, document.getElementById('recent-drop'));
input.placeholder = 'Search';
let expanded = false;
export function expand(open) {
  expanded = open;
  find.classList.toggle('searching', open);
  nav.classList.toggle('searching', open);
  const full = document.documentElement.dataset.headerOption === '2' && open;
  search.innerHTML = full ? backShape : searchShape;
  search.setAttribute('aria-label', full ? 'Close search' : 'Search');
}
input.addEventListener('focus', () => expand(true));
input.addEventListener('input', () => expand(true));
find.addEventListener('focusout', () => setTimeout(() => {
  if (!find.contains(document.activeElement) && !document.querySelector('dialog[open]') && !input.value) expand(false);
}, 0));
search.addEventListener('click', event => {
  if (document.documentElement.dataset.headerOption === '2' && expanded) {
    event.stopImmediatePropagation();
    input.blur();expand(false);
    document.querySelector('.brand').focus();
  } else {
    expand(true);
  }
}, true);
input.addEventListener('keydown', event => {
  if (event.key === 'Escape' && !document.querySelector('dialog[open]')) {
    input.blur();expand(false);document.querySelector('.brand').focus();
  }
});
expand(false);
