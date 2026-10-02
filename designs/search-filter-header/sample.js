import {filterBar} from '/assets/scripts/filters.js';
const shape = (paths) => `<span class="i"><svg viewBox="0 0 24 24">${paths}</svg></span>`;
document.getElementById('find-open').innerHTML = shape('<circle cx="11" cy="11" r="7"/><path d="M20.5 20.5l-4.3-4.3"/>');
document.getElementById('filter-open').innerHTML = shape('<path d="M22 3H2l8 9.5V19l4 2v-8.5L22 3z"/>');
document.getElementById('account-open').innerHTML = shape('<circle cx="12" cy="12" r="9.5"/><path d="M8 14s1.5 2 4 2 4-2 4-2M9 9h.01M15 9h.01"/>');
document.getElementById('filter-open').hidden = false;
const input = document.getElementById('q');
const search = document.getElementById('find-open');
search.addEventListener('click',()=>input.focus());
const {expand} = await import('/header-preview.js');
if (document.body.dataset.focused === 'true') {
  expand(true);
  input.placeholder = 'Search shows';
}
const trigger = document.getElementById('filter-open');
const control = filterBar('browse', {trigger,genres:[{key:'Drama',label:'Drama'},{key:'Comedy',label:'Comedy'},{key:'Crime',label:'Crime'}],languages:['English','Spanish'],onChange:()=>{
  trigger.classList.toggle('active',control.count()>0);
}});
trigger.onclick=()=>control.open();
