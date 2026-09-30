// The thresholds and maths behind Couchside's gestures (gestures.js), which imports here
// without a page: nothing in it touches one until main.js calls it.
import { LONG_PRESS, SLOP, EDGE, FLICK, rubber, follow, speed, dismisses, glide, heading, wandered, fromEdge, goesBack,
  stagger, REST, easesIn } from './gestures.js';
import { LOOP_SCREENS, LOOP_LEAST, LOOP_WAIT, goesRound, loopCopies, copiesOf, lapHome, restPlace, toCard } from './gestures.js';
let fails = 0;
const check = (name, ok, extra = '') => { console.log(`${ok ? 'pass' : 'FAIL'}  ${name}${ok ? '' : '  ' + extra}`); if (!ok) fails++; };

check('a long press is about half a second', LONG_PRESS >= 400 && LONG_PRESS <= 500, LONG_PRESS);
check('a press may wander a little before it is a scroll', SLOP === 10 && !wandered(6, 7) && !wandered(0, -10)
  && wandered(8, 8) && wandered(-11, 0));

check('pulled the wrong way, a sheet gives nothing for nothing', rubber(0, 800) === 0 && rubber(-5, 800) === 0);
check('it gives less than the pull, and less for each more', rubber(100, 800) > 0 && rubber(100, 800) < 100
  && rubber(200, 800) - rubber(100, 800) < rubber(100, 800), [rubber(100, 800), rubber(200, 800)]);
check('it never gives its whole height', rubber(1e6, 800) < 800 && rubber(1e6, 800) > 700);
check('going down, a sheet stays under the finger', follow(120, 800) === 120 && follow(0, 800) === 0);
check('going up, it is held back', follow(-120, 800) < 0 && follow(-120, 800) > -120 && follow(-120, 800) === -rubber(120, 800));

check('speed is over the last tenth of a second', speed([[0, 0], [50, 10], [100, 30], [150, 60]], 150) === .5,
  speed([[0, 0], [50, 10], [100, 30], [150, 60]], 150));
check('a finger that has rested has no speed', speed([[0, 0], [50, 40]], 400) === 0);
check('one sample, or none, has no speed', speed([[0, 10]], 0) === 0 && speed([], 100) === 0);
check('going up is negative', speed([[0, 50], [50, 20], [100, 0]], 100) === -.5);

check('a short, slow drag keeps a sheet', !dismisses(40, .05, 800));
check('a long drag sends it away', dismisses(200, 0, 800) && dismisses(181, 0, 800) && !dismisses(170, 0, 800));
check('a flick sends it away from near its place', dismisses(30, .6, 800) && FLICK <= .6);
check('a twitch at speed does not', !dismisses(5, .8, 800));
check('its speed counts as distance to come', dismisses(120, .35, 800) && !dismisses(120, 0, 800));
check('a flick back up keeps it however far it came', !dismisses(300, -.5, 800) && dismisses(300, -.1, 800));
check('a small sheet goes sooner than a tall one', dismisses(90, 0, 320) && !dismisses(90, 0, 800)
  && dismisses(80, 0, 200));

check('a button sends a sheet off at a steady pace', glide(800) === 280 && glide(100) === 120);
check('a thrown sheet goes on at its speed', glide(600, 3) === 200 && glide(900, 3) === 280);
check('never slower than a button would', glide(300, .5) === glide(300));

check('a finger that has not moved has no heading', heading(0, 0) === '');
check('mostly across is across', heading(5, 2) === 'x' && heading(-5, 4) === 'x');
check('mostly down or up is down or up', heading(2, 5) === 'down' && heading(-1, -4) === 'up' && heading(3, 3) === 'down');

check('a swipe back starts at the very edge', EDGE === 20 && fromEdge(0) && fromEdge(20) && !fromEdge(21));
check('it goes back a third of the way across, 110px at most', !goesBack(100, 0, 375) && goesBack(110, 0, 375)
  && goesBack(100, 0, 300) && !goesBack(99, 0, 300));
check('its speed counts too, but not going back the other way', goesBack(40, .5, 375) && !goesBack(130, -.5, 375));

check('a batch eases in step by step, the last not kept waiting', stagger(0, 40, 200) === 0 && stagger(3, 40, 200) === 120
  && stagger(9, 40, 200) === 200);

check('a row that lands on screen while the page is still eases in', easesIn(true, REST) && easesIn(true, Infinity));
check('one that lands while the reader scrolls is simply there', !easesIn(true, REST - 1) && !easesIn(true, 0));
check('and so is one that lands below the screen, however still', !easesIn(false, Infinity) && !easesIn(false, REST));
check('a page is still once it has not moved for a moment', REST >= 100 && REST <= 250);

// Rows that go round. A phone's row: 112px posters 8px apart, a lap of 20 is 2400px, and
// the row is 390px wide with 16px inside either end.
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
check('a row goes round once its cards run past its width, and not while they all fit, to a pixel',
  goesRound(2400, 8, 16, 390) && !goesRound(360, 8, 16, 390) && goesRound(368, 8, 16, 390) && !goesRound(367, 8, 16, 390));
check('it carries four screens past either end: a drag of a screen, and the furthest Chrome flings a row after it',
  LOOP_SCREENS === 4 && LOOP_LEAST >= 600);
check('a phone row keeps enough copies before its cards to carry it four screens back, and after them four more past a screen',
  same(loopCopies(390, 120), { before: 13, after: 17 }) && 13 * 120 >= 4 * 390 && 17 * 120 >= 5 * 390);
check('a narrow row is still carried 800px', same(loopCopies(200, 120), { before: 7, after: 9 }) && 7 * 120 >= LOOP_LEAST);
check('a wide screen keeps more, a desktop row of 176px posters four screens of them',
  same(loopCopies(1280, 184), { before: 28, after: 35 }));
check('the copies before a row are of its last cards, in order, and after it of its first',
  same(copiesOf(20, 3, 4), { before: [17, 18, 19], after: [0, 1, 2, 3] }));
check('a short row is copied round again as many times as it takes', same(copiesOf(3, 7, 5), { before: [2, 0, 1, 2, 0, 1, 2], after: [0, 1, 2, 0, 1] }));
check('a row resting among its own cards stays there', lapHome(0, 2400) === 0 && lapHome(1200, 2400) === 0 && lapHome(2399, 2400) === 0);
check('past its last card it moves back a lap, the same cards in the same places', lapHome(2400, 2400) === -2400 && lapHome(2520, 2400) === -2400);
check('before its first it moves on a lap', lapHome(-120, 2400) === 2400 && lapHome(-2400, 2400) === 2400);
check('a short row flung further moves back as many laps', lapHome(7300, 360) === -7200 && lapHome(-500, 360) === 720);
check('half a pixel either side of its first card is on it', lapHome(-.4, 2400) === 0 && lapHome(2399.6, 2400) === -2400);
const places = [[16, 128], [-2384, -2272], [2416, 2528]];   // a card's own place, then two copies'
check('at rest a card shows in its own place when that shows', restPlace(places, 0, 390) === 0);
check('and in a copy\'s place when only that shows, so no copy is ever what shows', restPlace([[2416, 2528], [16, 128]], 0, 390) === 1
  && restPlace([[-500, -388], [-2900, -2788], [260, 372]], 0, 390) === 2);
check('a sliver on screen counts, and the width of one edge does not', restPlace([[-500, -388], [-112, 8]], 0, 390) === 1
  && restPlace([[-500, -388], [-112, .3]], 0, 390) === 0);
check('with none of its places showing, a card stays in its own', restPlace([[900, 1012], [-600, -488]], 0, 390) === 0);
const lefts = [-104, 16, 136, 256, 376];
check('a row with a card on its edge rests on it', toCard(lefts, 16, 840, 3000) === 0 && toCard(lefts.map(l => l + .6), 16, 840, 3000) === 0);
check('one short of a card has that far to go, on or back to the nearest',
  toCard(lefts.map(l => l + 6), 16, 846, 3000) === 6 && toCard(lefts.map(l => l - 40), 16, 800, 3000) === -40
  && toCard(lefts.map(l => l - 80), 16, 760, 3000) === 40);
check('at the end of its scroll it goes back to a card, never on past the end', toCard([10, 130, 250], 16, 3000, 3000) === -6
  && toCard([-98, 22, 142], 16, 3000, 3000) === -114);
check('at its start it goes on to one', toCard([4, 124], 16, 0, 3000) === 108 && toCard([-6, 114], 16, 0, 3000) === 98);
check('a row stopped short of a card waits a little over half a second for a browser to snap it', LOOP_WAIT >= 400 && LOOP_WAIT <= 1000
  && LOOP_WAIT > REST);

console.log(fails ? `\n${fails} failed` : '\nall gesture checks passed');
process.exit(fails ? 1 : 0);
