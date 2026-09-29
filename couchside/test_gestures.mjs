// The thresholds and maths behind Couchside's gestures (gestures.js), which imports here
// without a page: nothing in it touches one until main.js calls it.
import { LONG_PRESS, SLOP, EDGE, FLICK, rubber, follow, speed, dismisses, glide, heading, wandered, fromEdge, goesBack,
  stagger } from './gestures.js';
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

console.log(fails ? `\n${fails} failed` : '\nall gesture checks passed');
process.exit(fails ? 1 : 0);
