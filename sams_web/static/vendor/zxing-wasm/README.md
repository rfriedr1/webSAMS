# zxing-wasm (vendored)

QR / DataMatrix reader for the photo bench (`static/js/photo-bench.js`),
copied unchanged from the npm package so the bench works on a lab network
without internet access (the library would otherwise fetch its `.wasm`
from jsDelivr).

- Package: `zxing-wasm` **3.1.6** (MIT, see `LICENSE`)
- `zxing-reader.iife.js` = `dist/iife/reader/index.js` (global `ZXingWASM`)
- `zxing_reader.wasm`    = `dist/reader/zxing_reader.wasm`

To upgrade: `npm pack zxing-wasm@<version>`, copy the same two files,
update the version here and the `ZXING_VERSION` note in `photo-bench.js`.
