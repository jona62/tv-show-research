// Moving a list between devices without an account.
//
// Everything travels in the URL fragment, which browsers never send to a
// server, so a shared link keeps the same promise the app makes everywhere
// else: your list is yours and never reaches us. Only catalog ids and ratings
// go in; titles are looked up again on arrival, which keeps a typical link
// around 140 characters instead of a few thousand.

const VERSION = 1;
export const LIMITS = { rated: 60, saved: 200 };

const FOCUS = ['balanced', 'story', 'themes', 'genres'];
const KNOWN = [0, 60, 85, 95];
const YEARS = [1900, 1990, 2000, 2010, 2018];
const FORMATS = ['all', 'scripted', 'animation', 'documentary', 'unscripted'];
const WEIGHTS = [1, .7, .35, 0, -1];

class Writer {
  constructor() { this.bytes = []; }
  u8(n) { this.bytes.push(n & 0xff); }
  varint(n) {
    let value = n >>> 0;
    while (value >= 0x80) { this.bytes.push((value & 0x7f) | 0x80); value >>>= 7; }
    this.bytes.push(value);
  }
  text(value) {
    const encoded = new TextEncoder().encode((value ?? '').slice(0, 60));
    this.u8(encoded.length);
    for (const byte of encoded) this.bytes.push(byte);
  }
  done() { return Uint8Array.from(this.bytes); }
}

class Reader {
  constructor(bytes) { this.bytes = bytes; this.at = 0; }
  get left() { return this.bytes.length - this.at; }
  u8() {
    if (this.at >= this.bytes.length) throw new Error('truncated');
    return this.bytes[this.at++];
  }
  varint() {
    let value = 0, shift = 0;
    for (;;) {
      const byte = this.u8();
      value |= (byte & 0x7f) << shift;
      if (!(byte & 0x80)) return value >>> 0;
      shift += 7;
      if (shift > 28) throw new Error('varint too long');
    }
  }
  text() {
    const length = this.u8();
    if (length > this.left) throw new Error('truncated');
    const slice = this.bytes.subarray(this.at, this.at + length);
    this.at += length;
    return new TextDecoder().decode(slice);
  }
}

const toBase64 = bytes => {
  let binary = '';
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
};

const fromBase64 = code => {
  const padded = code.replace(/-/g, '+').replace(/_/g, '/');
  const binary = atob(padded + '='.repeat((4 - padded.length % 4) % 4));
  return Uint8Array.from(binary, char => char.charCodeAt(0));
};

const index = (list, value, fallback = 0) => {
  const found = list.indexOf(value);
  return found < 0 ? fallback : found;
};

export function encode(state) {
  const w = new Writer();
  const s = state.settings;
  const focus = FOCUS.findIndex(name => {
    const mix = { balanced: [40, 35, 25], story: [70, 20, 10], themes: [15, 70, 15], genres: [15, 20, 65] }[name];
    return mix[0] === s.text && mix[1] === s.themes && mix[2] === s.genres;
  });
  w.u8(VERSION);
  w.u8(focus < 0 ? 0 : focus);
  w.u8(index(KNOWN, s.known_min, 2));
  w.u8(index(YEARS, s.year_min, 1));
  w.u8(index(FORMATS, s.type));
  w.u8(Math.round(Math.min(1, Math.max(0, s.dislike)) * 20));
  w.text(s.language === 'all' ? '' : s.language);
  w.text(s.status === 'all' ? '' : s.status);

  const rated = state.profile.slice(0, LIMITS.rated);
  w.varint(rated.length);
  for (const show of rated) {
    w.varint(show.id);
    w.u8(index(WEIGHTS, show.weight, 1));
  }
  const saved = state.saved.slice(0, LIMITS.saved);
  w.varint(saved.length);
  for (const show of saved) w.varint(show.id);
  return toBase64(w.done());
}

export function decode(code) {
  const r = new Reader(fromBase64(code.trim()));
  if (r.u8() !== VERSION) throw new Error('This code came from a different version of the app.');
  const settings = {
    ...{ balanced: { text: 40, themes: 35, genres: 25 }, story: { text: 70, themes: 20, genres: 10 },
         themes: { text: 15, themes: 70, genres: 15 }, genres: { text: 15, themes: 20, genres: 65 } }[FOCUS[r.u8()] ?? 'balanced'],
    closest: .3, runtime_min: 0, rating_min: 0,
  };
  settings.known_min = KNOWN[r.u8()] ?? 85;
  settings.year_min = YEARS[r.u8()] ?? 1990;
  settings.type = FORMATS[r.u8()] ?? 'all';
  settings.dislike = Math.min(1, r.u8() / 20);
  settings.language = r.text() || 'all';
  settings.status = r.text() || 'all';

  const read = (limit, withWeight) => {
    const count = r.varint();
    if (count > limit) throw new Error('This code holds more shows than the app accepts.');
    const out = [];
    for (let n = 0; n < count; n++) {
      const id = r.varint();
      const weight = withWeight ? WEIGHTS[r.u8()] : undefined;
      if (!Number.isInteger(id) || id <= 0) throw new Error('This code is damaged.');
      if (withWeight && weight === undefined) throw new Error('This code is damaged.');
      out.push(withWeight ? { id, weight } : { id });
    }
    return out;
  };
  const profile = read(LIMITS.rated, true);
  const saved = read(LIMITS.saved, false);
  if (r.left > 0) throw new Error('This code is damaged.');
  const seen = new Set();
  for (const show of profile) {
    if (seen.has(show.id)) throw new Error('This code lists the same show twice.');
    seen.add(show.id);
  }
  return { profile, saved: saved.filter(show => !seen.has(show.id)), settings };
}
