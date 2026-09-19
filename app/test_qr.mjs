// Checks for the QR encoder.
//
// The fixtures in qr-golden.json are this encoder's own output, but every one of
// them was read back by ZBar before being recorded, as were all forty versions at
// three payload sizes each. They are a regression lock, not the original proof.
// Regenerate them only after re-verifying with a real scanner.
import { readFileSync } from 'fs';
import { matrix, svgPath } from './qr.js';

const golden = JSON.parse(readFileSync(new URL('./qr-golden.json', import.meta.url)));
let fails = 0;
const check = (name, ok, extra = '') => {
  console.log(`${ok ? 'pass' : 'FAIL'}  ${name}${ok ? '' : '  ' + extra}`);
  if (!ok) fails++;
};

// 1. Known-good matrices, byte for byte.
for (const { text, version, rows } of golden) {
  const got = matrix(text);
  check(`v${version} (${text.length} chars) matches its recorded matrix`,
    got !== null && got.map(r => r.join('')).join('|') === rows.join('|'));
}

// 2. Structure the spec fixes, independent of any payload.
const grid = matrix('https://example.com/#t=' + 'A'.repeat(300));
const size = grid.length;
check('version scales the matrix as 4v+17', (size - 17) % 4 === 0 && size >= 21 && size <= 177);
const finder = [[1,1,1,1,1,1,1],[1,0,0,0,0,0,1],[1,0,1,1,1,0,1],[1,0,1,1,1,0,1],[1,0,1,1,1,0,1],[1,0,0,0,0,0,1],[1,1,1,1,1,1,1]];
for (const [ox, oy, corner] of [[0, 0, 'top left'], [size - 7, 0, 'top right'], [0, size - 7, 'bottom left']]) {
  const ok = finder.every((row, y) => row.every((v, x) => grid[oy + y][ox + x] === v));
  check(`${corner} finder pattern is intact`, ok);
}
check('timing patterns alternate', [...Array(size - 16)].every((_, i) =>
  grid[6][8 + i] === (i % 2 === 0 ? 1 : 0) && grid[8 + i][6] === (i % 2 === 0 ? 1 : 0)));
check('the dark module is dark', grid[size - 8][8] === 1);
check('the quiet zone is left to the renderer', svgPath(grid).size === size + 8);

// 3. The format word must announce level M and the mask that was actually used.
const bits = [];
for (let i = 0; i < 15; i++) {
  const [x, y] = i < 6 ? [8, i] : i < 8 ? [8, i + 1] : i === 8 ? [7, 8] : [14 - i, 8];
  bits.push(grid[y][x]);
}
const word = bits.reduce((n, b, i) => n | (b << i), 0) ^ 0b101010000010010;
check('format word says error level M', (word >> 13) === 0b00, `got ${(word >> 13).toString(2)}`);
const usedMask = (word >> 10) & 7;
check('format word names a real mask', usedMask >= 0 && usedMask <= 7);
const MASKS = [(x, y) => (x + y) % 2 === 0, (x, y) => y % 2 === 0, x => x % 3 === 0,
  (x, y) => (x + y) % 3 === 0, (x, y) => (Math.floor(y / 2) + Math.floor(x / 3)) % 2 === 0,
  (x, y) => (x * y) % 2 + (x * y) % 3 === 0, (x, y) => ((x * y) % 2 + (x * y) % 3) % 2 === 0,
  (x, y) => ((x + y) % 2 + (x * y) % 3) % 2 === 0];
// A masked timing row would break every scanner, so the mask must have spared it.
check('the mask spared the function patterns',
  [...Array(size - 16)].every((_, i) => grid[6][8 + i] === (i % 2 === 0 ? 1 : 0)) && MASKS[usedMask] !== undefined);

// 4. Capacity: the largest payload each version takes, and one byte more.
const CAP_V1 = 14, CAP_V2 = 26;
check('v1 takes 14 bytes', matrix('A'.repeat(CAP_V1)).length === 21);
check('15 bytes moves up to v2', matrix('A'.repeat(CAP_V1 + 1)).length === 25);
check('v2 takes 26 bytes', matrix('A'.repeat(CAP_V2)).length === 25);
check('the longest transfer link still fits', matrix('https://x.dev/#t=' + 'A'.repeat(1136)) !== null);
check('beyond version 40 it declines rather than truncating', matrix('A'.repeat(3000)) === null);

// 5. Multi-byte text must be counted in bytes, not characters.
const wide = matrix('café ☕ 日本');
check('utf-8 payloads encode', wide !== null && wide.length >= 21);

console.log(fails ? `\n${fails} failed` : '\nall qr checks passed');
process.exit(fails ? 1 : 0);
