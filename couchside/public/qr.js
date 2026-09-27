// A QR code for the transfer link, so a phone can pick a list up by camera.
//
// Byte mode at error-correction level M, which is the usual default and holds
// 2,331 bytes at version 40, far more than the longest link the app can produce.
// Supporting one level keeps the block table to forty rows.

// Per version: EC codewords per block, then two groups of (blocks, data codewords).
const BLOCKS = ('10 1 16 0 0,16 1 28 0 0,26 1 44 0 0,18 2 32 0 0,24 2 43 0 0,16 4 27 0 0,18 4 31 0 0,'
  + '22 2 38 2 39,22 3 36 2 37,26 4 43 1 44,30 1 50 4 51,22 6 36 2 37,22 8 37 1 38,24 4 40 5 41,'
  + '24 5 41 5 42,28 7 45 3 46,28 10 46 1 47,26 9 43 4 44,26 3 44 11 45,26 3 41 13 42,26 17 42 0 0,'
  + '28 17 46 0 0,28 4 47 14 48,28 6 45 14 46,28 8 47 13 48,28 19 46 4 47,28 22 45 3 46,28 3 45 23 46,'
  + '28 21 45 7 46,28 19 47 10 48,28 2 46 29 47,28 10 46 23 47,28 14 46 21 47,28 14 46 23 47,'
  + '28 12 47 26 48,28 6 47 34 48,28 29 46 14 47,28 13 46 32 47,28 40 47 7 48,28 18 47 31 48')
  .split(',').map(row => row.split(' ').map(Number));

// Alignment pattern centres, versions 2 to 40.
const ALIGN = ('6 18,6 22,6 26,6 30,6 34,6 22 38,6 24 42,6 26 46,6 28 50,6 30 54,6 32 58,6 34 62,'
  + '6 26 46 66,6 26 48 70,6 26 50 74,6 30 54 78,6 30 56 82,6 30 58 86,6 34 62 90,6 28 50 72 94,'
  + '6 26 50 74 98,6 30 54 78 102,6 28 54 80 106,6 32 58 84 110,6 30 58 86 114,6 34 62 90 118,'
  + '6 26 50 74 98 122,6 30 54 78 102 126,6 26 52 78 104 130,6 30 56 82 108 134,6 34 60 86 112 138,'
  + '6 30 58 86 114 142,6 34 62 90 118 146,6 30 54 78 102 126 150,6 24 50 76 102 128 154,'
  + '6 28 54 80 106 132 158,6 32 58 84 110 136 162,6 26 54 82 110 138 166,6 30 58 86 114 142 170')
  .split(',').map(row => row.split(' ').map(Number));

// GF(256) with the QR primitive polynomial, for Reed-Solomon.
const EXP = new Uint8Array(512);
const LOG = new Uint8Array(256);
for (let i = 0, x = 1; i < 255; i++) {
  EXP[i] = x;
  LOG[x] = i;
  x <<= 1;
  if (x & 0x100) x ^= 0x11d;
}
for (let i = 255; i < 512; i++) EXP[i] = EXP[i - 255];
const mul = (a, b) => (a && b ? EXP[LOG[a] + LOG[b]] : 0);

/** The product of (x - a^i) for i below `degree`, highest power first. */
function generator(degree) {
  let poly = [1];
  for (let i = 0; i < degree; i++) {
    const next = new Array(poly.length + 1).fill(0);
    for (let j = 0; j < poly.length; j++) {
      next[j] ^= poly[j];                        // poly * x, one degree up
      next[j + 1] ^= mul(poly[j], EXP[i]);       // poly * a^i, same degree
    }
    poly = next;
  }
  return poly;
}

function remainder(data, degree) {
  const gen = generator(degree);
  const out = new Array(degree).fill(0);
  for (const byte of data) {
    const factor = byte ^ out[0];
    out.shift();
    out.push(0);
    for (let i = 0; i < degree; i++) out[i] ^= mul(gen[i + 1], factor);
  }
  return out;
}

/** Smallest version that holds `length` bytes in byte mode at level M. The header
 *  is 4 bits of mode plus an 8 or 16 bit count, so the comparison is in bits: a
 *  byte-rounded one throws away a version's worth of room. */
function pickVersion(length) {
  for (let v = 1; v <= 40; v++) {
    const [, b1, d1, b2, d2] = BLOCKS[v - 1];
    const header = 4 + (v < 10 ? 8 : 16);
    if ((b1 * d1 + b2 * d2) * 8 >= header + length * 8) return v;
  }
  return 0;
}

function codewords(bytes, version) {
  const [ec, b1, d1, b2, d2] = BLOCKS[version - 1];
  const capacity = b1 * d1 + b2 * d2;
  const countBits = version < 10 ? 8 : 16;

  const bits = [];
  const push = (value, width) => {
    for (let i = width - 1; i >= 0; i--) bits.push((value >> i) & 1);
  };
  push(0b0100, 4);
  push(bytes.length, countBits);
  for (const byte of bytes) push(byte, 8);
  for (let i = 0; i < 4 && bits.length < capacity * 8; i++) bits.push(0);
  while (bits.length % 8) bits.push(0);

  const data = [];
  for (let i = 0; i < bits.length; i += 8) {
    data.push(bits.slice(i, i + 8).reduce((n, bit) => (n << 1) | bit, 0));
  }
  for (let pad = 0; data.length < capacity; pad++) data.push(pad % 2 ? 0x11 : 0xec);

  const blocks = [];
  let at = 0;
  for (const [count, size] of [[b1, d1], [b2, d2]]) {
    for (let n = 0; n < count; n++) {
      const block = data.slice(at, at + size);
      at += size;
      blocks.push({ data: block, ec: remainder(block, ec) });
    }
  }
  // Interleave: every block's first codeword, then every block's second, and so on.
  const out = [];
  for (let i = 0; i < Math.max(d1, d2); i++) {
    for (const block of blocks) if (i < block.data.length) out.push(block.data[i]);
  }
  for (let i = 0; i < ec; i++) for (const block of blocks) out.push(block.ec[i]);
  return out;
}

/** BCH check bits. The format word is 5 data bits over 10, the version word 6
 *  over 12, so the division starts at bit 17 to cover both. */
const bch = (value, poly, degree) => {
  let rest = value << degree;
  for (let i = 17; i >= degree; i--) if (rest >>> i & 1) rest ^= poly << (i - degree);
  return (value << degree) | rest;
};

// Cells hold -1 for "data goes here", or the module value with bit 1 set to mark
// a function pattern, which placement skips and the mask must never touch.
const FIXED = 2;

function frame(version) {
  const size = version * 4 + 17;
  const grid = Array.from({ length: size }, () => new Int8Array(size).fill(-1));
  const set = (x, y, value) => { if (x >= 0 && y >= 0 && x < size && y < size) grid[y][x] = value | FIXED; };

  for (const [ox, oy] of [[0, 0], [size - 7, 0], [0, size - 7]]) {
    for (let y = -1; y <= 7; y++) {
      for (let x = -1; x <= 7; x++) {
        const edge = x === -1 || x === 7 || y === -1 || y === 7;
        const ring = x === 0 || x === 6 || y === 0 || y === 6;
        const core = x >= 2 && x <= 4 && y >= 2 && y <= 4;
        set(ox + x, oy + y, edge ? 0 : (ring || core) ? 1 : 0);
      }
    }
  }
  for (let i = 8; i < size - 8; i++) {
    grid[6][i] = grid[i][6] = (i % 2 === 0 ? 1 : 0) | FIXED;
  }
  if (version > 1) {
    const centres = ALIGN[version - 2];
    const corner = size - 7;
    for (const cy of centres) {
      for (const cx of centres) {
        // The three that would sit on a finder are omitted. The rest are placed
        // even where they cross a timing line, which they take precedence over.
        if ((cx === 6 && cy === 6) || (cx === 6 && cy === corner) || (cx === corner && cy === 6)) continue;
        for (let y = -2; y <= 2; y++) {
          for (let x = -2; x <= 2; x++) {
            const ring = Math.max(Math.abs(x), Math.abs(y));
            grid[cy + y][cx + x] = (ring === 1 ? 0 : 1) | FIXED;
          }
        }
      }
    }
  }
  grid[size - 8][8] = 1 | FIXED;   // the always-dark module

  // Reserve the format areas so data placement skips them.
  for (let i = 0; i < 9; i++) {
    if (grid[8][i] === -1) grid[8][i] = FIXED;
    if (grid[i][8] === -1) grid[i][8] = FIXED;
  }
  for (let i = 0; i < 8; i++) {
    if (grid[8][size - 1 - i] === -1) grid[8][size - 1 - i] = FIXED;
    if (grid[size - 1 - i][8] === -1) grid[size - 1 - i][8] = FIXED;
  }
  if (version >= 7) {
    const info = bch(version, 0x1f25, 12);
    for (let i = 0; i < 18; i++) {
      const bit = (info >> i) & 1;
      grid[Math.floor(i / 3)][size - 11 + (i % 3)] = bit | FIXED;
      grid[size - 11 + (i % 3)][Math.floor(i / 3)] = bit | FIXED;
    }
  }
  return grid;
}

function placeData(grid, stream) {
  const size = grid.length;
  let at = 0, upward = true;
  for (let right = size - 1; right > 0; right -= 2) {
    if (right === 6) right = 5;   // the vertical timing column is not a data column
    for (let step = 0; step < size; step++) {
      const y = upward ? size - 1 - step : step;
      for (const x of [right, right - 1]) {
        if (grid[y][x] !== -1) continue;
        const bit = at < stream.length * 8 ? (stream[at >> 3] >> (7 - (at & 7))) & 1 : 0;
        grid[y][x] = bit;
        at++;
      }
    }
    upward = !upward;
  }
}

const MASKS = [
  (x, y) => (x + y) % 2 === 0,
  (x, y) => y % 2 === 0,
  (x) => x % 3 === 0,
  (x, y) => (x + y) % 3 === 0,
  (x, y) => (Math.floor(y / 2) + Math.floor(x / 3)) % 2 === 0,
  (x, y) => (x * y) % 2 + (x * y) % 3 === 0,
  (x, y) => ((x * y) % 2 + (x * y) % 3) % 2 === 0,
  (x, y) => ((x + y) % 2 + (x * y) % 3) % 2 === 0,
];

/** The four penalty rules from the spec, used to pick the least patterned mask. */
function penalty(grid) {
  const size = grid.length;
  const at = (x, y) => grid[y][x] & 1;
  let score = 0;

  for (let pass = 0; pass < 2; pass++) {
    for (let a = 0; a < size; a++) {
      let run = 1;
      for (let b = 1; b < size; b++) {
        const here = pass ? at(a, b) : at(b, a);
        const before = pass ? at(a, b - 1) : at(b - 1, a);
        if (here === before) {
          run++;
          if (run === 5) score += 3;
          else if (run > 5) score++;
        } else run = 1;
      }
    }
  }
  for (let y = 0; y < size - 1; y++) {
    for (let x = 0; x < size - 1; x++) {
      const v = at(x, y);
      if (v === at(x + 1, y) && v === at(x, y + 1) && v === at(x + 1, y + 1)) score += 3;
    }
  }
  const finder = [1, 0, 1, 1, 1, 0, 1];
  const matches = (line, start) => {
    for (let i = 0; i < 7; i++) if (line[start + i] !== finder[i]) return false;
    const before = line.slice(Math.max(0, start - 4), start);
    const after = line.slice(start + 7, start + 11);
    const clear = run => run.length >= 4 && run.every(v => v === 0);
    return clear(before) || clear(after);
  };
  for (let a = 0; a < size; a++) {
    const row = [], column = [];
    for (let b = 0; b < size; b++) { row.push(at(b, a)); column.push(at(a, b)); }
    for (const line of [row, column]) {
      for (let start = 0; start + 7 <= size; start++) if (matches(line, start)) score += 40;
    }
  }
  let dark = 0;
  for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) dark += at(x, y);
  score += Math.floor(Math.abs(dark * 100 / (size * size) - 50) / 5) * 10;
  return score;
}

function writeFormat(grid, mask) {
  const size = grid.length;
  const info = bch(0b00 << 3 | mask, 0x537, 10) ^ 0b101010000010010;   // 00 is level M
  for (let i = 0; i < 15; i++) {
    const bit = (info >> i) & 1;
    const [x1, y1] = i < 6 ? [8, i] : i < 8 ? [8, i + 1] : i === 8 ? [7, 8] : [14 - i, 8];
    grid[y1][x1] = bit;
    const [x2, y2] = i < 8 ? [size - 1 - i, 8] : [8, size - 15 + i];
    grid[y2][x2] = bit;
  }
}

/** A square matrix of 0 and 1 for `text`, or null if it will not fit. */
export function matrix(text, forceMask) {
  const bytes = new TextEncoder().encode(text);
  const version = pickVersion(bytes.length);
  if (!version) return null;
  const stream = codewords(bytes, version);
  const base = frame(version);
  placeData(base, stream);

  let best = null;
  for (let mask = 0; mask < 8; mask++) {
    if (forceMask !== undefined && mask !== forceMask) continue;
    const grid = base.map(row => Int8Array.from(row));
    for (let y = 0; y < grid.length; y++) {
      for (let x = 0; x < grid.length; x++) {
        if (!(base[y][x] & FIXED) && MASKS[mask](x, y)) grid[y][x] ^= 1;
      }
    }
    writeFormat(grid, mask);
    const score = penalty(grid);
    if (!best || score < best.score) best = { score, grid };
  }
  return best.grid.map(row => Array.from(row, cell => cell & 1));
}

/** One `<path>` of dark modules, with a quiet zone, scaled by the viewBox. */
export function svgPath(grid) {
  const quiet = 4;
  const size = grid.length + quiet * 2;
  let path = '';
  for (let y = 0; y < grid.length; y++) {
    for (let x = 0; x < grid.length; x++) {
      if (grid[y][x]) path += `M${x + quiet} ${y + quiet}h1v1h-1z`;
    }
  }
  return { path, size };
}
