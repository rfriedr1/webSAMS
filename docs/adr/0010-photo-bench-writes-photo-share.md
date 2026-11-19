# The photo bench writes into the photo share

Every sample is photographed after the import and before it goes into the lab, and sometimes again while it is processed. Until now the pictures were taken outside webSAMS and dropped into the shared photo folder by hand; webSAMS only read that folder (Sample Photos, Setup → *Sample Photos*). Samples → **Photos** (`/samples/photos`, Magic Nav `/photo`) is a bench that takes the pictures with the webcam of the bench PC and saves them there (2026-11).

## Decisions

1. **The same folder, no new setting.** Photos are saved into the folder configured in Setup → *Sample Photos*, the one the sample pages read. This is webSAMS' **first write** to that share: the account the server runs as now needs *write* access to it, not only read access.

2. **Names follow the folder's own convention.** The first photo of a sample is `<nr>.jpg`; when the sample already has a photo of its own, the next free `<nr>_2.jpg`, `<nr>_3.jpg`, … (an underscore number already means "photo k of that sample" to the reader, so no parser change). Group photos do not count as the sample's own. Files are created exclusively (`open(…, "xb")`): an existing file is never overwritten, the next number is taken instead, which also keeps two benches saving the same sample apart. Only JPEG is accepted, checked by content.

3. **New photos go into the range folder of their number.** The top-level folder named `a-b` with `a ≤ nr ≤ b` (`90001-95000`); when there is none, one 5 000 wide is created, aligned like the lab's (`95001-100000`). Reading still matches on file names alone, because several hundred older photos sit in the wrong range.

4. **No request waits on a dead share.** The write runs in a worker thread that the request waits on for 15 s; after that the bench says the folder is not answering, through the same `FolderProblem` texts the sample page uses. Saved files are put into the in-memory index straight away (`SamplePhotoLibrary.add_files`), so they show on the sample page without a rescan, also when a scan was running at the time.

5. **Photo first, number second, never without an acknowledgement.** The browser reads the label's QR / DataMatrix code in each shot (the browser's own `BarcodeDetector` where it exists, otherwise zxing-wasm, vendored under `static/vendor/zxing-wasm` so no internet is needed). A label that names a sample the bench is not on opens a *suggestion card* with that sample's record; the operator compares it with the printed label and confirms (Enter) or rejects it (Esc). Nothing is saved under a number that was neither confirmed nor typed. Photos whose label names another sample are marked and asked about before saving. When the next sample's label is read while the current one has unsaved photos, the one confirmation saves those and switches.

6. **No database change.** The bench writes files only; `sample_t.photo` stays untouched (it is an unrelated legacy field).

7. **Camera settings belong to the PC.** Brightness, exposure, white balance, focus, zoom (whatever the webcam reports) are kept in the browser's `localStorage`, like the benches' *Balance g → mg*, not in Setup, which would apply them to every PC.

## Consequences

- Browsers allow the camera only on `https://` pages or on `localhost`. Until webSAMS runs behind HTTPS (IIS, server guide §13), each bench PC needs Chrome's / Edge's *unsafely-treat-insecure-origin-as-secure* flag for the server's address; the page explains this when the camera is blocked. *Add file…* works regardless.
- The label rule (number alone, `MAMS-48211`, or a text with exactly one run of 3+ digits) lives in `photo_bench.sample_nr_from_label` and is mirrored in `photo-bench.js`. Check it against the real labels and adjust both if they encode something else.
- The change log will hook into `SamplePhotos.save_new` once login exists (ADR-0006).
