import { prune, few } from './similar.js';
let fails = 0;
const check = (name, ok, extra = '') => { console.log(`${ok ? 'pass' : 'FAIL'}  ${name}${ok ? '' : '  ' + extra}`); if (!ok) fails++; };
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

const list = [{ id: 1, weight: 1 }, { id: 2, weight: .7 }, { id: 3, weight: .35 }, { id: 4, weight: 0 }, { id: 5, weight: -1 }];
check('keeps chosen liked shows in list order', same(prune(list, [3, 1]), [1, 3]));
check('an OK rating still counts as liked', same(prune(list, [3]), [3]));
check('drops a show rated Meh', same(prune(list, [1, 4]), [1]));
check('drops a show rated No', same(prune(list, [5, 2]), [2]));
check('drops a show no longer on the list', same(prune(list, [1, 99]), [1]));
check('drops a repeat', same(prune(list, [2, 2, 1]), [1, 2]));
check('nothing chosen stays nothing', same(prune(list, []), []));
check('clears the choice below two liked shows', same(prune([{ id: 1, weight: 1 }, { id: 5, weight: -1 }], [1]), []));
check('keeps the choice at exactly two liked shows', same(prune([{ id: 1, weight: 1 }, { id: 2, weight: .35 }], [2]), [2]));
check('an empty list clears the choice', same(prune([], [1]), []));

check('no names is an empty string', few([]) === '');
check('one name stands alone', few(['Ozark']) === 'Ozark');
check('two names are joined with and', few(['Ozark', 'Dark']) === 'Ozark and Dark');
check('three names use a comma and and', few(['Ozark', 'Dark', 'Fargo']) === 'Ozark, Dark and Fargo');
check('four names count the rest', few(['Ozark', 'Dark', 'Fargo', 'Devs']) === 'Ozark, Dark and 2 more');
check('five names count the rest', few(['A', 'B', 'C', 'D', 'E']) === 'A, B and 3 more');
console.log(fails ? `\n${fails} failed` : '\nall similar checks passed');
process.exit(fails ? 1 : 0);
