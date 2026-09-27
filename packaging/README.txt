exoprobe, built as a standalone executable
==========================================

  exoprobe            the command line tool (exoprobe.exe on Windows). Open a
                      terminal in this folder and run, for example:
                          exoprobe scan   extraction/
                          exoprobe rejoin extraction/ -o out/
                          exoprobe mux    video.mp4 audio.m4a -o combined.mp4
                          exoprobe --help
                      On Windows write exoprobe.exe; on macOS and Linux write
                      ./exoprobe from this folder. `extraction/` is a folder
                      holding an extracted Android file system, or any part of
                      one that holds an ExoPlayer cache.

  SHA256SUMS.txt      the hash of the executable as built. Check it with
                          certutil -hashfile exoprobe.exe SHA256     (Windows)
                          shasum -a 256 -c SHA256SUMS.txt            (macOS)
                          sha256sum -c SHA256SUMS.txt                (Linux)

It reads the evidence read-only and writes only into the output folder you
give it (and a temporary copy of any index database it reads). It installs
nothing and needs no administrator rights. It is built from exoprobe.py in
https://github.com/abrignoni/exoprobe by the repository's own GitHub Actions
workflow, and is not code signed:

  Windows   SmartScreen may ask once before running it. Unzip to a local
            folder rather than running from a network share.
  macOS     Gatekeeper will refuse a downloaded, unsigned program on first
            run. Right-click (Control-click) exoprobe in Finder and choose
            Open, once, or remove the quarantine mark from this folder:
                xattr -dr com.apple.quarantine .
  Linux     mark the file executable if the archive did not keep the bit:
                chmod +x exoprobe

Builds: windows-x64, windows-arm64 (native for Windows on ARM; the x64 build
also runs there through emulation), macos-arm64 (Apple silicon), macos-x64
(Intel), linux-x64, linux-arm64.
