# exoprobe

Rejoins the media an Android app cached through ExoPlayer. One file, pure Python,
standard library only. Read-only on the evidence: it writes only into the output
folder you give it, and into a temporary copy of an index database it reads.

ExoPlayer (`com.google.android.exoplayer2`, now `androidx.media3`) is the media
library most Android apps stream with, and it caches what they play. A cached video
is not one file: it is split into pieces named for the byte offset they start at,
and the address the video came from is kept in a separate index. Opening a piece on
its own gives a truncated file at best. exoprobe reads the index, joins each item's
pieces back into the file the app downloaded, joins a DASH stream's segments in the
order its cached manifest lists them, and can put a DASH video and its audio into one
playable MP4 without re-encoding anything.

```python
import exoprobe

for cache in exoprobe.find_caches("extraction/"):
    for record in exoprobe.rejoin(cache, "out/" + cache.root.replace("/", "_")):
        print(record["status"], record.get("file"), record.get("key"))
```

## Command line

```
exoprobe scan   extraction/                  # every cache, item, key and state
exoprobe rejoin extraction/ -o out/          # the joined media, plus out/report.json
exoprobe mux    video.mp4 audio.m4a [more.m4a ...] -o combined.mp4
```

`rejoin` writes each cache into its own subfolder of `out/` and records, for every
item, which index named it, how many pieces were joined, how many bytes against the
length the index recorded, whether the join is complete, and the last-touched time
from the piece names.

## What it reads

- **Pieces**, `<id>.<position>.<timestamp>.v3.exo` in subfolders `0` to `9` of the
  cache folder, and the older `<key>.<position>.<timestamp>.v2.exo` (key escaped with
  `%xx`) and `.v1.exo` forms that carry the key in the name.
- **The index**, either `cached_content_index.exi` (the `.exi.bak` wins when both are
  present, as ExoPlayer's `AtomicFile` restores it) or an `ExoPlayerCacheIndex<uid>`
  table in `exoplayer_internal.db`, matched to the cache by its `<uid>.uid` file. The
  database is read from a temporary copy with its `-wal` or `-journal`: even a
  read-only SQLite open rewrites the `-shm` beside the file it opens.
- **Metadata** the index records per item: the full length (`exo_len`) and the address
  it was redirected to (`exo_redir`).
- **DASH manifests** cached beside the segments. A stream is joined only from what the
  manifest lists, in its order: an initialization segment and then media segments up
  to the first one missing or incomplete. Addresses that merely look alike are never
  joined. A stream fetched as one file by byte range (SegmentBase) is already whole,
  and is paired with the other streams its manifest lists.

The layout is taken from androidx/media 1.11.1
([8c6678b6](https://github.com/androidx/media/tree/8c6678b657ede1e7883fc164ef73ed483c7796c3/libraries/datasource/src/main/java/androidx/media3/datasource/cache)),
`SimpleCacheSpan`, `CachedContentIndex`, `DefaultContentMetadata`, and for DASH
`DashManifestParser` and `DashUtil.resolveCacheKey`.

## Behaviours worth knowing

- **A gap ends the join.** Pieces after it cannot be placed in a playable file without
  the bytes before them, so they are counted (`pieces_left_out`), not joined.
- **An item with no piece at position 0 is recorded, not written.** Nothing in it can
  open.
- **Two pieces at one position:** the one with the later last-touch time is used.
  ExoPlayer renames a piece to its new time when it touches it
  (`CachedContent.setLastTouchTimestamp`), so a live cache holds only one.
- **An encrypted index is named as such** and no key is invented for its items.
- **An audio-only MP4 is audio**, whatever its brand says, read from the track's own
  handler (`hdlr`).

## Putting video and audio together

DASH serves video and sound as separate streams, so the cache holds a silent video
and a picture-less audio track. `mux` rewrites the boxes that describe the tracks
(ISO/IEC 14496-12) into one header and copies every sample's bytes unchanged, for
fragmented MP4 (DASH) and for ordinary MP4 alike.

When a manifest lists more than one cached audio stream, two languages say, picking
one would be a guess, so every one goes in as its own track in the manifest's order.
They share an alternate group and only the first is enabled, the marking ffmpeg
writes for alternative languages, so a player that honours it starts on the first and
offers the others. Each track's language is reported as the manifest writes it; the
language field inside the file is copied from the cached stream unchanged. A
whole-file video that is cut short is not combined, and a whole-file audio cut short
is left out and counted.

The tests compare every combined file with its inputs frame by frame through ffmpeg's
`framemd5` where ffmpeg is installed, and always check the output's own boxes: every
track declared, every input fragment present unchanged, every rewritten chunk offset
pointing at the bytes it pointed at before.

## What it does not do

- A DASH stream described by a `SegmentTemplate` is not joined.
- HLS video is cached one segment per item; each is joined on its own, as long as the
  segment, and segments are not put together.
- An encrypted index (`.exi` flag 1) cannot be read without its key, which is not in
  the file. Encrypted media tracks (a `sinf` box) are not combined.
- It reads only what an extraction holds: a video evicted from the cache is gone.

## Licence

MIT. See `LICENSE`.
