import { encode, decode, LIMITS } from './transfer.js';
globalThis.btoa = s => Buffer.from(s, 'binary').toString('base64');
globalThis.atob = s => Buffer.from(s, 'base64').toString('binary');
let fails = 0;
const check = (name, ok, extra = '') => { console.log(`${ok ? 'pass' : 'FAIL'}  ${name}${ok ? '' : '  ' + extra}`); if (!ok) fails++; };

const state = {
  profile: [{ id: 13417, weight: 1 }, { id: 169, weight: .7 }, { id: 82, weight: .35 },
            { id: 80, weight: -1 }, { id: 5, weight: 0 }],
  saved: [{ id: 527 }, { id: 179 }, { id: 89594 }],
  settings: { text: 15, themes: 70, genres: 15, closest: .3, dislike: .5, language: 'Japanese',
              type: 'animation', status: 'Running', year_min: 2010, runtime_min: 0, rating_min: 0, known_min: 60 },
};
const code = encode(state);
const back = decode(code);
check('ratings survive the trip', JSON.stringify(back.profile) === JSON.stringify(state.profile));
check('saved ids survive the trip', JSON.stringify(back.saved) === JSON.stringify(state.saved));
for (const key of ['text', 'themes', 'genres', 'dislike', 'language', 'type', 'status', 'year_min', 'known_min'])
  check(`setting ${key} survives`, back.settings[key] === state.settings[key], `${back.settings[key]} != ${state.settings[key]}`);
check('code is url safe', !/[+/=]/.test(code), code);
check('a typical list stays short', code.length < 160, `${code.length} chars`);

const full = {
  profile: Array.from({ length: LIMITS.rated }, (_, n) => ({ id: 89594 - n, weight: 1 })),
  saved: Array.from({ length: LIMITS.saved }, (_, n) => ({ id: 1000 + n })),
  settings: { ...state.settings, language: 'all', status: 'all' },
};
const big = encode(full);
check('a full list still fits a URL', big.length < 1200, `${big.length} chars`);
check('a full list round-trips', decode(big).saved.length === LIMITS.saved);

const broken = [['empty', ''], ['junk', 'not-a-code'], ['truncated', code.slice(0, 8)],
                ['wrong version', encode(state).replace(/^./, 'B')]];
for (const [name, bad] of broken) {
  let threw = false;
  try { decode(bad); } catch { threw = true; }
  check(`rejects ${name}`, threw);
}
let dupThrew = false;
try { decode(encode({ ...state, profile: [{ id: 5, weight: 1 }, { id: 5, weight: .7 }] })); } catch { dupThrew = true; }
check('rejects a duplicate show', dupThrew);
check('saved never shadows a rated show',
  decode(encode({ ...state, saved: [{ id: 13417 }, { id: 527 }] })).saved.length === 1);
console.log(fails ? `\n${fails} failed` : '\nall codec checks passed');
process.exit(fails ? 1 : 0);
