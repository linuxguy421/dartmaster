# Supplied bracket audit

The eight source definitions cover 3 through 10 teams. The loader preserves each
JSON `games` object's insertion order; it does not normalize or repair the files.

## Source inventory

| Teams | Games, including GF and GGF |
|---:|---:|
| 3 | 5 |
| 4 | 7 |
| 5 | 9 |
| 6 | 11 |
| 7 | 13 |
| 8 | 15 |
| 9 | 17 |
| 10 | 19 |

Every file places `GF` and `GGF` as the final two source entries. The application
will combine these into one logical Championship Match, with `GGF` representing
the conditional reset phase rather than a separately scheduled match.

## Known source anomalies

These findings are intentionally recorded as diagnostics, not repaired in place:

- **5 teams:** `GGF.teams` contains `W-G8` and `L-G8`, but the definition has no
  `G8`. The likely intended participants cannot be inferred safely enough to
  rewrite the source automatically.
- **9 teams:** `G12.teams[0]` is `L-10`, which references no defined game. It may
  be a typo for `L-G10`, but the source remains unchanged.
- **9 teams:** `GF.teams[1]` is `W-G17`, but the definition ends its preliminary
  bracket at `G15`. The intended finalist reference requires confirmation.
- **9 teams:** The incoming loser route from `G10` targets `G12` slot 0, but that
  slot says `L-10` rather than `L-G10`.
- **9 teams:** The incoming winner route from `G13` targets `GF` slot 0, but that
  slot says `W-G15` rather than `W-G13`.
- **9 teams:** The incoming winner route from `G15` targets `GF` slot 1, but that
  slot says `W-G17` rather than `W-G15`.

All other supplied files use `W-GF` and `L-GF` as the reset participants in
`GGF`. The championship domain model consumes the first final's participants
and only activates the reset when required; it must not silently reinterpret
malformed source references.

## Validation policy

- Keep source JSON unchanged until an explicit correction is approved.
- Preserve insertion order exactly.
- Treat unresolved references as bracket diagnostics.
- Do not schedule `GGF` independently.
- Keep the championship match and its conditional reset on the same board.
