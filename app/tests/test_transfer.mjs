import { encode, decode, LIMITS, packList, codeFrom } from '../client/transfer.js';
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
check('which shows the picks match never rides in the code', encode({ ...state, similar_to: [13417] }) === code);
check('a code carries no such choice back', !('similar_to' in back));
check('a typical list stays short', code.length < 160, `${code.length} chars`);

const full = {
  profile: Array.from({ length: LIMITS.rated }, (_, n) => ({ id: 89594 - n, weight: 1 })),
  saved: Array.from({ length: LIMITS.saved }, (_, n) => ({ id: 1000 + n })),
  settings: { ...state.settings, language: 'all', status: 'all' },
};
const big = encode(full);
check('lists may hold 3,000 ratings and 200 saved shows', LIMITS.rated === 3000 && LIMITS.saved === 200);
check('a full list stays a URL a browser opens', big.length < 20000, `${big.length} chars`);
const back2 = decode(big);
check('a full list round-trips, ratings in order', back2.saved.length === LIMITS.saved
  && JSON.stringify(back2.profile) === JSON.stringify(full.profile));
let over = false;
try { decode(encode({ ...full, profile: [...full.profile, { id: 7, weight: 1 }] })); } catch { over = true; }
check('the codec never writes more than a list holds', !over && decode(encode({ ...full, profile: [...full.profile, { id: 7, weight: 1 }] })).profile.length === LIMITS.rated);
const longest = { ...full, profile: full.profile.slice(0, 400), saved: [] };
check('a list of 400 ratings still fits a QR code (2,331 bytes)', `https://couchside.example/#t=${encode(longest)}`.length <= 2331);

// Requests carry a list as its ids and one character a rating.
const packed = packList(state.profile);
check('a request packs ids and ratings in order', JSON.stringify(packed) === JSON.stringify({
  ids: [13417, 169, 82, 80, 5], weights: '43201' }));
check('and packs about a quarter of the bytes', JSON.stringify(packList(full.profile)).length * 3
  < JSON.stringify(full.profile.map(({ id, weight }) => ({ id, weight }))).length);
check('a pasted link or code is read whatever surrounds it',
  codeFrom(`see https://x.example/#t=${code}`) === code && codeFrom(`  ${code}\n`) === code
  && codeFrom(`${code.slice(0, 10)}\n${code.slice(10, 20)} ${code.slice(20)}`) === code);

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
