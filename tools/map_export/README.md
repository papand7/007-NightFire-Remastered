# Map export (offline, read-only)

Offline tools that read the game's own data (`assets/eurocom/filesys.d00`-`d10`). They never run inside the game, so
the recomp, its renderer and its physics are untouched. Output goes to `generated/private/` (git-ignored): never commit
it, because everything it contains is game data.

```
python -I tools/map_export/nf_unpack.py assets/eurocom                       # list the level files
python -I tools/map_export/nf_unpack.py assets/eurocom generated/private/levels 07000024 07000026
```

Status: the archive, its compression and the level container are decoded and checked (each EDL chunk unpacks to
exactly the size in its header, for all 30 levels). The map geometry format is **not decoded yet**, so there is no
GLB. See "Next step".

## What is known (from default.xbe, addresses in `.local/game.exe`)

| What | Where | Notes |
|---|---|---|
| Archive mount | `FUN_000e2a40` | index = first 0x13800 bytes of filesys.d00; parts `d:\eurocom\filesys.d%02d` |
| Name lookup | `FUN_000e2960` | CRC32 (`FUN_000e8f90`, zlib's table at 0x1d52e8) of the lower-cased name, `/` -> `\`; binary search over sorted hashes |
| Level file name | `FUN_00011160`, `FUN_000be910` | `"%8.8x.bin"` of the level id, e.g. `07000024.bin` |
| KXC | `FUN_000e8e30` | `"KXC" 04`, u32 chunk count, then EDL chunks |
| EDL | `FUN_000d4ac0` / `FUN_000d3a80` | `"EDL"`, flags (bit 7 big endian, method 0 stored / 1 Huffman LZ / 2 unseen), u32 packed size, u32 unpacked size; method 1 = Deflate's LZ77 and length/distance tables (0x18cd5c, 0x18cd7c, 0x18cd9c, 0x18cdd8) with Eurocom's own block headers (see `nf_archive.py`) |
| MP map table | file offset 0x16c698 (stride 0x18) | rows `..., name text id, description text id, level id` |

The index entry layout is in `nf_archive.py`. Fields marked "not decoded" there are not guessed at.

### Multiplayer maps (MP map table + the US English text, archive entry 366, text id 0x03000024 = string 1939)

| Map | Level file | Text ids (name, description) |
|---|---|---|
| Skyrail | `07000024.bin` | 0x24, 0x26 |
| Fort Knox | `07000027.bin` | 0x25, 0x27 |
| Snow Blind | `07000029.bin` | 0x28, 0x29 |
| Phoenix Base ("Battle in Drake's secret underwater base.") | `07000026.bin` | 0x2a, 0x2b |
| Atlantis | `07000023.bin` | 0x2c, 0x2d |
| Missile Silo | `07000028.bin` | 0x2e, 0x2f |
| Sub Pen | `07000025.bin` | 0x30, 0x31 |
| Ravine | `0700004b.bin` | 0x32, 0x33 |

`07000048.bin` is the MP front end (map preview images `prev_*`). As a cross-check, Skyrail's file has `MTower_1`.. (the
gondola towers) and Fort Knox's has `fortLeft_*`. `scripts/pad/mp_bots.txt` gets the recomp into a Skyrail match.

### Level container (`0700xxxx.bin`, observed from the files and not yet from the loader)
- u32 table size (0x6620 for Skyrail), u32 count (1867), 0x18 bytes not decoded; entries from +0x20, 14 bytes each:
  u32 size, u8 kind, 8 hex chars (the sub-file's hashcode) + NUL. The data starts at table size + 0x20, with the
  sub-files back to back in table order. Each one starts with its own hashcode.
- kinds seen in Skyrail: 1 (one per level, `010000fa`, 3.1 MB: the map, with a 0x9b-entry texture table and object
  names such as `MTower_1` in 32-byte fields), 0/2/11 (`01xxxxxx` texture/model files, e.g. `Flag-Base`), 4
  (`04xxxxxx`, 813 animation curve records), 5/7 (`06xxxxxx`), 3 (`05xxxxxx`), 6 (`SKELxxxx` skeletons), 8
  (`08000001`).

## Next step (the blocker)
Decode the kind-1 map file (`010000fa` in Skyrail). Find the reader in default.xbe rather than guessing: the function
that dispatches on the container's kind byte, then the kind-1 loader's pointer fix-ups and the vertex/index buffers it
gives D3D8 (CreateVertexBuffer / SetStreamSource / DrawIndexedVertices callers). A capture from the recomp
(`scripts/pad/mp_bots.txt`, Skyrail) can cross-check the decoded vertices, but it is not a full extraction by itself.
After that: write the GLB (positions, indices, UVs, texture names, node names, Xbox Y-up kept and documented),
collision, and spawns/triggers (the `05xxxxxx`/`06xxxxxx` records are candidates, unverified).
