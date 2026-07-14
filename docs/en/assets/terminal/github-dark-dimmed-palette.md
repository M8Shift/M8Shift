# GitHub Dark Dimmed — 24-bit palette (source of truth for m8shift-top #50)

Extracted from `GitHub-Dark-Dimmed.itermcolors` (iTerm2 stores sRGB float components =
true 24-bit). Use these as the truecolour tier for the top's semantic cells so the top
matches the recommended iTerm2 profile (#52). The wordmark keeps the BRAND hex
(M8 Orange `#FF7A18`, Shift Purple `#5D26F2`); the cells use these theme colours.

| ANSI | role | hex | escape |
|---|---|---|---|
| 0  | black       | `#545D68` | `38;2;84;93;104` |
| 1  | red         | `#F47067` | `38;2;244;112;103` |
| 2  | green       | `#57AB5A` | `38;2;87;171;90` |
| 3  | yellow      | `#C69026` | `38;2;198;144;38` |
| 4  | blue        | `#539BF5` | `38;2;83;155;245` |
| 5  | magenta     | `#B083F0` | `38;2;176;131;240` |
| 6  | cyan        | `#39C5CF` | `38;2;57;197;207` |
| 7  | white       | `#909DAB` | `38;2;144;157;171` |
| 8  | br-black    | `#636E7B` | `38;2;99;110;123` |
| 9  | br-red      | `#FF938A` | `38;2;255;147;138` |
| 10 | br-green    | `#6BC46D` | `38;2;107;196;109` |
| 11 | br-yellow   | `#DAAA3F` | `38;2;218;170;63` |
| 12 | br-blue     | `#6CB6FF` | `38;2;108;182;255` |
| 13 | br-magenta  | `#DCBDFB` | `38;2;220;189;251` |
| 14 | br-cyan     | `#56D4DD` | `38;2;86;212;221` |
| 15 | br-white    | `#CDD9E5` | `38;2;205;217;229` |
| bg | background  | `#1C2128` | `38;2;28;33;40` |
| fg | foreground  | `#ADBAC7` | `38;2;173;186;199` |

## Suggested semantic mapping for the top (#50)
- ok / idle-dot / weekly-safe → green `#57AB5A` (or br-green `#6BC46D`)
- elevated / holder / amber → yellow `#C69026` (or br-yellow `#DAAA3F`)
- near-limit / danger → red `#F47067` (or br-red `#FF938A`)
- version / info → cyan `#39C5CF`
- accent / purple → magenta `#B083F0`
- dim / structural → br-black `#636E7B`
- default text → foreground `#ADBAC7`

256-colour and 16-colour fallbacks are computed by the tiered `_brand()` helper
(#49/#50); NO_COLOR stays plain. Wordmark brand hex are NOT from this theme.
