// Label locator for the photo bench: a second chance for label codes the
// reader misses because printed text runs into them.
//
// zxing's DataMatrix detector follows the code's solid L edge and needs a
// clear margin around it; a letter touching the L (the lab's labels print
// the project code right up to the DataMatrix) makes it give up, although
// the code itself is intact. This module finds dark blobs shaped like a
// code, turns each upright by its edge directions, cuts away what hangs
// off its edges (several ways — the reader's error correction decides
// which cut was right) and returns small crops with everything around the
// code painted white. Pure image work: no DOM, no decoding.
//
//   const found = SAMSLabelLocator.locate(imageData);
//   for (const blob of found.blobs)
//     for (const { image, toSource } of found.cropsFor(blob)) …
//
// `toSource(x, y)` maps a point of the crop back to `imageData`.
(() => {
  const DARK_BELOW = 0.82; // dark = under 82 % of the local mean (Bradley)
  const MAX_BLOBS = 10;

  const grayAndDark = ({ width: W, height: H, data }) => {
    const n = W * H;
    const gray = new Uint8Array(n);
    for (let i = 0, j = 0; i < n; i += 1, j += 4) {
      gray[i] = (data[j] * 77 + data[j + 1] * 150 + data[j + 2] * 29) >> 8;
    }
    const iw = W + 1;
    const integral = new Float64Array(iw * (H + 1));
    for (let y = 0; y < H; y += 1) {
      let row = 0;
      for (let x = 0; x < W; x += 1) {
        row += gray[y * W + x];
        integral[(y + 1) * iw + x + 1] = integral[y * iw + x + 1] + row;
      }
    }
    const r = Math.max(8, Math.round(Math.min(W, H) / 60));
    const dark = new Uint8Array(n);
    for (let y = 0; y < H; y += 1) {
      const y0 = Math.max(0, y - r);
      const y1 = Math.min(H, y + r + 1);
      for (let x = 0; x < W; x += 1) {
        const x0 = Math.max(0, x - r);
        const x1 = Math.min(W, x + r + 1);
        const sum = integral[y1 * iw + x1] - integral[y0 * iw + x1] - integral[y1 * iw + x0] + integral[y0 * iw + x0];
        dark[y * W + x] = gray[y * W + x] * (x1 - x0) * (y1 - y0) < sum * DARK_BELOW ? 1 : 0;
      }
    }
    return { gray, dark };
  };

  // 8-connected dark components (union-find) with their boxes.
  const components = (dark, W, H) => {
    const labels = new Int32Array(W * H);
    const parent = [0];
    const find = (a) => {
      while (parent[a] !== a) {
        parent[a] = parent[parent[a]];
        a = parent[a];
      }
      return a;
    };
    for (let y = 0; y < H; y += 1) {
      for (let x = 0; x < W; x += 1) {
        const i = y * W + x;
        if (!dark[i]) continue;
        let m = 0;
        const join = (l) => {
          if (!l) return;
          l = find(l);
          if (!m) m = l;
          else if (l !== m) {
            const low = Math.min(l, m);
            parent[Math.max(l, m)] = low;
            m = low;
          }
        };
        if (x > 0) join(labels[i - 1]);
        if (y > 0) {
          join(labels[i - W]);
          if (x > 0) join(labels[i - W - 1]);
          if (x < W - 1) join(labels[i - W + 1]);
        }
        if (!m) {
          m = parent.length;
          parent.push(m);
        }
        labels[i] = m;
      }
    }
    const stats = new Map();
    for (let y = 0; y < H; y += 1) {
      for (let x = 0; x < W; x += 1) {
        const i = y * W + x;
        if (!labels[i]) continue;
        const l = find(labels[i]);
        labels[i] = l;
        let s = stats.get(l);
        if (!s) stats.set(l, (s = { l, x0: x, y0: y, x1: x, y1: y, area: 0 }));
        s.area += 1;
        if (x < s.x0) s.x0 = x;
        if (x > s.x1) s.x1 = x;
        if (y > s.y1) s.y1 = y;
      }
    }
    return { labels, stats: [...stats.values()] };
  };

  // Blobs shaped like a code: not tiny, not huge, squarish, partly filled,
  // and many dark/light changes per line (a letter has two to four).
  const codeLike = (stats, dark, W, H) => {
    const maxSide = Math.min(W, H) * 0.6;
    const found = [];
    for (const s of stats) {
      const w = s.x1 - s.x0 + 1;
      const h = s.y1 - s.y0 + 1;
      if (Math.min(w, h) < 16 || Math.max(w, h) > maxSide) continue;
      if (Math.max(w, h) / Math.min(w, h) > 3.4) continue;
      const fill = s.area / (w * h);
      if (fill < 0.15 || fill > 0.8) continue;
      let changes = 0;
      for (let y = s.y0; y <= s.y1; y += 1) {
        for (let x = s.x0 + 1; x <= s.x1; x += 1) changes += dark[y * W + x] ^ dark[y * W + x - 1];
      }
      for (let x = s.x0; x <= s.x1; x += 1) {
        for (let y = s.y0 + 1; y <= s.y1; y += 1) changes += dark[y * W + x] ^ dark[(y - 1) * W + x];
      }
      const perLine = changes / (w + h);
      if (perLine < 3.5) continue;
      found.push({ ...s, w, h, score: perLine * Math.sqrt(s.area) });
    }
    return found.sort((a, b) => b.score - a.score);
  };

  // The blob's angle (mod 90°): the peak of its edge directions — a code's
  // module edges all run along two perpendicular directions.
  const blobAngle = (blob, gray, W, H) => {
    const bins = new Float64Array(90);
    const x0 = Math.max(1, blob.x0);
    const x1 = Math.min(W - 2, blob.x1);
    const y0 = Math.max(1, blob.y0);
    const y1 = Math.min(H - 2, blob.y1);
    for (let y = y0; y <= y1; y += 1) {
      for (let x = x0; x <= x1; x += 1) {
        const i = y * W + x;
        const gx = gray[i - W + 1] + 2 * gray[i + 1] + gray[i + W + 1] - gray[i - W - 1] - 2 * gray[i - 1] - gray[i + W - 1];
        const gy = gray[i + W - 1] + 2 * gray[i + W] + gray[i + W + 1] - gray[i - W - 1] - 2 * gray[i - W] - gray[i - W + 1];
        const magnitude = Math.abs(gx) + Math.abs(gy);
        if (magnitude < 60) continue;
        const deg = ((((Math.atan2(gy, gx) * 180) / Math.PI) % 90) + 90) % 90;
        bins[Math.floor(deg) % 90] += magnitude;
      }
    }
    let peak = 0;
    let best = -1;
    for (let k = 0; k < 90; k += 1) {
      const s = bins[(k + 89) % 90] + bins[k] + bins[(k + 1) % 90];
      if (s > best) {
        best = s;
        peak = k;
      }
    }
    let sum = 0;
    let weight = 0;
    for (let d = -2; d <= 2; d += 1) {
      const w = bins[(peak + d + 90) % 90];
      sum += (peak + d + 0.5) * w;
      weight += w;
    }
    const deg = weight ? sum / weight : 0;
    return deg >= 45 ? deg - 90 : deg;
  };

  const sample = (gray, W, H, x, y) => {
    if (x < 0 || y < 0 || x > W - 1 || y > H - 1) return 255;
    const x0 = Math.floor(x);
    const y0 = Math.floor(y);
    const x1 = Math.min(W - 1, x0 + 1);
    const y1 = Math.min(H - 1, y0 + 1);
    const fx = x - x0;
    const fy = y - y0;
    const top = gray[y0 * W + x0] * (1 - fx) + gray[y0 * W + x1] * fx;
    const bottom = gray[y1 * W + x0] * (1 - fx) + gray[y1 * W + x1] * fx;
    return top * (1 - fy) + bottom * fy;
  };

  // Rows (or columns) to keep: trim faint ends, or cut right at a solid
  // finder edge near either end.
  const cuts = (counts) => {
    const n = counts.length;
    const max = Math.max(...counts);
    let a = 0;
    let b = n - 1;
    while (a < b && counts[a] < max * 0.25) a += 1;
    while (b > a && counts[b] < max * 0.25) b -= 1;
    const strong = [];
    for (let k = 0; k < n; k += 1) if (counts[k] >= max * 0.7) strong.push(k);
    const options = [[a, b]];
    if (strong.length && strong[0] < n * 0.4) options.push([strong[0], b]);
    if (strong.length && strong[strong.length - 1] > n * 0.6) options.push([a, strong[strong.length - 1]]);
    return options;
  };

  const strongest = (counts, from, to) => {
    let best = -1;
    for (let k = from; k < to; k += 1) if (best < 0 || counts[k] > counts[best]) best = k;
    return best;
  };

  // Crops to try for one blob, upright, white outside the kept box.
  const cropsFor = (blob, { gray, dark, labels, W, H }) => {
    const deg = blobAngle(blob, gray, W, H);
    const angle = (deg * Math.PI) / 180;
    const cos = Math.cos(angle);
    const sin = Math.sin(angle);
    const cx = (blob.x0 + blob.x1) / 2;
    const cy = (blob.y0 + blob.y1) / 2;
    const toSource = (u, v) => ({ x: cx + u * cos - v * sin, y: cy + u * sin + v * cos });

    // The blob's extent in the upright frame.
    let u0 = Infinity;
    let u1 = -Infinity;
    let v0 = Infinity;
    let v1 = -Infinity;
    for (let y = blob.y0; y <= blob.y1; y += 1) {
      for (let x = blob.x0; x <= blob.x1; x += 1) {
        if (labels[y * W + x] !== blob.l) continue;
        const u = (x - cx) * cos + (y - cy) * sin;
        const v = -(x - cx) * sin + (y - cy) * cos;
        if (u < u0) u0 = u;
        if (u > u1) u1 = u;
        if (v < v0) v0 = v;
        if (v > v1) v1 = v;
      }
    }
    u0 = Math.floor(u0);
    v0 = Math.floor(v0);
    u1 = Math.ceil(u1);
    v1 = Math.ceil(v1);
    const cw = u1 - u0 + 1;
    const ch = v1 - v0 + 1;

    // Upright dark map — all dark pixels, because a code's dotted clock
    // edge is not part of the one connected blob.
    const grid = new Uint8Array(cw * ch);
    const cols = new Int32Array(cw);
    const rows = new Int32Array(ch);
    for (let v = v0; v <= v1; v += 1) {
      for (let u = u0; u <= u1; u += 1) {
        const { x, y } = toSource(u, v);
        const px = Math.round(x);
        const py = Math.round(y);
        if (px < 0 || py < 0 || px >= W || py >= H || !dark[py * W + px]) continue;
        grid[(v - v0) * cw + (u - u0)] = 1;
        cols[u - u0] += 1;
        rows[v - v0] += 1;
      }
    }

    // Longest dark run along one grid row / column (a gap of a pixel or
    // two is blur): the length of a finder edge.
    const run = (at, len, alongRow) => {
      let best = [0, -1];
      let start = -1;
      let gap = 0;
      for (let k = 0; k <= len; k += 1) {
        const on = k < len && (alongRow ? grid[at * cw + k] : grid[k * cw + at]);
        if (on) {
          if (start < 0) start = k;
          gap = 0;
        } else if (start >= 0 && (++gap > 2 || k === len)) {
          const end = k - gap;
          if (end - start > best[1] - best[0]) best = [start, end];
          start = -1;
          gap = 0;
        }
      }
      return best;
    };

    const boxes = [];
    for (const [ra, rb] of cuts(rows)) for (const [ca, cb] of cuts(cols)) boxes.push([ra, rb, ca, cb]);
    // Boxes measured by the L itself: its row gives the width, its column
    // the height, and nothing lies beyond its corner — so letters touching
    // the code are cut off in both directions.
    const nearRows = [strongest(rows, 0, Math.ceil(ch * 0.4)), strongest(rows, Math.floor(ch * 0.6), ch)];
    const nearCols = [strongest(cols, 0, Math.ceil(cw * 0.4)), strongest(cols, Math.floor(cw * 0.6), cw)];
    nearRows.forEach((r, rowAtEnd) =>
      nearCols.forEach((c, colAtEnd) => {
        if (r < 0 || c < 0) return;
        let [ca, cb] = run(r, cw, true);
        let [ra, rb] = run(c, ch, false);
        if (rowAtEnd) rb = Math.min(rb, r);
        else ra = Math.max(ra, r);
        if (colAtEnd) cb = Math.min(cb, c);
        else ca = Math.max(ca, c);
        if (cb - ca >= 8 && rb - ra >= 8) boxes.push([ra, rb, ca, cb]);
      })
    );

    const seen = new Set();
    const crops = [];
    for (const [ra, rb, ca, cb] of boxes) {
      const key = `${ra},${rb},${ca},${cb}`;
      if (seen.has(key)) continue;
      seen.add(key);
      const bu0 = u0 + ca;
      const bu1 = u0 + cb;
      const bv0 = v0 + ra;
      const bv1 = v0 + rb;
      const side = Math.max(bu1 - bu0, bv1 - bv0) + 1;
      const scale = side < 60 ? 2 : 1; // small codes read better enlarged
      const pad = Math.round(side * 0.3) + 4;
      const ow = (bu1 - bu0 + 1 + 2 * pad) * scale;
      const oh = (bv1 - bv0 + 1 + 2 * pad) * scale;
      const out = new Uint8ClampedArray(ow * oh * 4).fill(255);
      for (let oy = 0; oy < oh; oy += 1) {
        const v = bv0 - pad + oy / scale;
        if (v < bv0 - 0.5 || v > bv1 + 0.5) continue;
        for (let ox = 0; ox < ow; ox += 1) {
          const u = bu0 - pad + ox / scale;
          if (u < bu0 - 0.5 || u > bu1 + 0.5) continue;
          const { x, y } = toSource(u, v);
          const g = sample(gray, W, H, x, y);
          const j = (oy * ow + ox) * 4;
          out[j] = g;
          out[j + 1] = g;
          out[j + 2] = g;
        }
      }
      crops.push({
        image: new ImageData(out, ow, oh),
        toSource: (px, py) => toSource(bu0 - pad + px / scale, bv0 - pad + py / scale),
      });
    }
    return crops;
  };

  const locate = (imageData, { maxBlobs = MAX_BLOBS } = {}) => {
    const W = imageData.width;
    const H = imageData.height;
    const { gray, dark } = grayAndDark(imageData);
    const { labels, stats } = components(dark, W, H);
    const context = { gray, dark, labels, W, H };
    return {
      blobs: codeLike(stats, dark, W, H).slice(0, maxBlobs),
      cropsFor: (blob) => cropsFor(blob, context),
    };
  };

  const api = { locate };
  if (typeof window !== "undefined") window.SAMSLabelLocator = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})();
