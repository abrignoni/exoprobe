exoprobe {{VERSION}}: standalone executables of `exoprobe.py` and its window, `exoprobe_gui.py`, built by this repository's own GitHub Actions workflow from the tagged commit.

- `exoprobe-{{VERSION}}-windows-x64.zip` runs on Intel and AMD PCs, and on Windows on ARM through its x64 emulation.
- `exoprobe-{{VERSION}}-windows-arm64.zip` is native for Windows on ARM.
- `exoprobe-{{VERSION}}-macos-arm64.zip` for Apple silicon Macs, `exoprobe-{{VERSION}}-macos-x64.zip` for Intel Macs.
- `exoprobe-{{VERSION}}-linux-x64.tar.gz` and `exoprobe-{{VERSION}}-linux-arm64.tar.gz`, built on Ubuntu 22.04 so they run on distributions with a glibc at least that old.
- `exoprobe.py` and `exoprobe_gui.py`, the tagged source files themselves.

Each archive holds the command line tool, the window (`exoprobe_gui`), `README.txt`, `LICENSE` and `SHA256SUMS.txt`. `SHA256SUMS.txt` beside the archives covers the archives and the two source files. Before it was attached, each executable was run on caches built the way ExoPlayer writes them (a DASH stream, an HLS stream with two audio renditions, and an item indexed in `exoplayer_internal.db`) and on the mux fixtures, and it wrote the same bytes as `python exoprobe.py` for `scan`, `rejoin` and `mux`.

The window runs the command line tool by re-entering itself with `--cli`; that call went through the same comparison against `python exoprobe.py`, and the window was started and checked to stay up.

None of the executables is code signed: Windows SmartScreen and macOS Gatekeeper will each ask once, and the README inside says what to do. Unzip to a local folder rather than running from a network share.

`exoprobe.py` needs nothing built: `python3 exoprobe.py` works on macOS, Linux and Windows with Python 3.10 or later and the standard library alone. See the README for what it reads.
