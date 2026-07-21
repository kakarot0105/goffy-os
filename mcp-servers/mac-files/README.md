# mac-files

Current Hub tool:

- `mac.files.list`: SAFE read-only directory listing for explicitly configured
  `GOFFY_MAC_FILES_ROOTS`.
- `mac.files.largest`: SAFE read-only largest-file metadata scan for explicitly
  configured `GOFFY_MAC_FILES_ROOTS`.

Boundaries:

- No arbitrary path access outside approved roots.
- No file-content reads in this slice.
- No create, move, delete, recursive delete, or shell execution.
- Symlink entries are reported as symlinks without following their targets.
- Largest-file scans skip symlinks, return relative paths only, and stop at
  fixed result, depth, and scan-count bounds.
