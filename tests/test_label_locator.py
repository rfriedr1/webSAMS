"""Photo bench: the label locator (static/js/label-locator.js).

zxing's DataMatrix detector gives up on a code whose solid L edge is
touched by printed text, as on the lab's labels. The locator cuts code-like
blobs out of the picture and has each read on its own. This runs the real
browser modules (vendored zxing-wasm + the locator) in Node on a synthetic
label: a DataMatrix for 86103, rotated, with text running into its edge.
Skipped where Node is not installed.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "sams_web" / "static"
FIXTURE = ROOT / "tests" / "fixtures" / "label_code_touched_by_text.pgm.gz"

NODE_SCRIPT = r"""
const fs = require("node:fs");
const vm = require("node:vm");
const zlib = require("node:zlib");
const [zxingJs, wasmPath, locatorJs, fixture] = JSON.parse(process.env.LOCATOR_TEST_PATHS);

globalThis.ImageData = class ImageData {
  constructor(data, width, height) { this.data = data; this.width = width; this.height = height; this.colorSpace = "srgb"; }
};
vm.runInThisContext(fs.readFileSync(zxingJs, "utf8") + "\nglobalThis.ZXingWASM = ZXingWASM;");
const { locate } = require(locatorJs);

const pgm = zlib.gunzipSync(fs.readFileSync(fixture));
const header = pgm.toString("latin1", 0, 40).match(/^P5\s+(\d+)\s+(\d+)\s+255\s/);
const [width, height] = [Number(header[1]), Number(header[2])];
const gray = pgm.subarray(header[0].length);
const rgba = new Uint8ClampedArray(width * height * 4);
for (let i = 0; i < width * height; i += 1) {
  rgba[i * 4] = rgba[i * 4 + 1] = rgba[i * 4 + 2] = gray[i];
  rgba[i * 4 + 3] = 255;
}
const image = new ImageData(rgba, width, height);

(async () => {
  const z = globalThis.ZXingWASM;
  await z.prepareZXingModule({ overrides: { wasmBinary: fs.readFileSync(wasmPath) }, fireImmediately: true });
  const options = { formats: ["QRCode", "DataMatrix", "MicroQRCode"], tryHarder: true, maxNumberOfSymbols: 4 };
  const direct = (await z.readBarcodes(image, options)).map((r) => r.text);
  const found = locate(image);
  const located = [];
  for (const blob of found.blobs) {
    for (const crop of found.cropsFor(blob)) {
      const hit = (await z.readBarcodes(crop.image, { ...options, maxNumberOfSymbols: 1 }))[0];
      if (!hit) continue;
      const p = hit.position;
      const corners = [p.topLeft, p.topRight, p.bottomRight, p.bottomLeft].map((q) => crop.toSource(q.x, q.y));
      located.push({ text: hit.text, corners });
      break;
    }
  }
  process.stdout.write(JSON.stringify({ width, height, direct, located }));
})().catch((error) => { console.error(error); process.exit(1); });
"""


@pytest.fixture(scope="module")
def located() -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is not installed")
    paths = [
        STATIC / "vendor" / "zxing-wasm" / "zxing-reader.iife.js",
        STATIC / "vendor" / "zxing-wasm" / "zxing_reader.wasm",
        STATIC / "js" / "label-locator.js",
        FIXTURE,
    ]
    result = subprocess.run(
        [node, "-e", NODE_SCRIPT],
        env={**os.environ, "LOCATOR_TEST_PATHS": json.dumps([str(p) for p in paths])},
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_zxing_alone_misses_a_code_touched_by_text(located):
    # Why the locator exists: if this ever reads, zxing got better.
    assert located["direct"] == []


def test_locator_reads_it(located):
    assert [code["text"] for code in located["located"]] == ["86103"]


def test_corners_map_back_onto_the_code(located):
    # The code sits at about (430–490, 200–260) in the fixture; the outline
    # drawn over the photo uses these corners.
    corners = located["located"][0]["corners"]
    xs = [c["x"] for c in corners]
    ys = [c["y"] for c in corners]
    assert 400 < min(xs) < max(xs) < 520
    assert 170 < min(ys) < max(ys) < 300
    assert all(0 <= c["x"] <= located["width"] and 0 <= c["y"] <= located["height"] for c in corners)
