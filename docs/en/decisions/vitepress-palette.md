# VitePress Palette Adoption Decision

Status: accepted for the current VitePress documentation site.

This decision records what should be kept from the M8Shift brand palette for the
current VitePress site, what should remain only as broader brand reference, and why.
The full palette is useful, but the documentation site should not import every color
at once.

Reference palette: [docs/en/brand/color-palette.md](../brand/color-palette.md).

## Context

The current VitePress CSS already uses the right family:

- `#FF7A18` for orange;
- `#F0509C` as the current pink approximation;
- `#7C3AED` as the current VitePress brand purple;
- light gradients and low-opacity accents on hero, feature cards, FAQ cards, use-case
  cards, and quick-start panels.

VitePress is documentation-first. The color system should make the brand recognizable
without making normal reading surfaces feel like a product-dashboard redesign.

## Kept For VitePress

| Item | Status | Why |
|---|---|---|
| **M8 Orange** `#FF7A18` | Keep active | Already present in the site and strongly tied to the logo. Use for warm accents, identity gradients, and action energy. |
| **Relay Pink** `#F252BF` | Keep active | Better brand match than `#F0509C`; it bridges the orange to purple arc of the logo more naturally. Use for handoff, transition, halo, and small highlight moments. |
| **Shift Purple** `#5D26F2` | Keep as target primary | More specific to M8Shift than VitePress' current `#7C3AED`. Good candidate for `--vp-c-brand-1` and `theme-color` in a controlled CSS pass. |
| **Electric Violet** `#8B47F9` | Keep for focus and secondary accents | Bright enough for focus rings, badges, and hover states without replacing the primary purple everywhere. Also a candidate for dark-mode brand accents. |
| **Flow Coral** `#FB6F74` | Keep active | The orange to pink bridge stop in the gradient, plus hover/badge micro-interactions. Like orange, it fails white-text contrast, so it should remain an accent. |
| **Deep Violet** `#2D09A4` | Keep for dark surfaces | Strong contrast, colored shadows, and dark accents. Too dark for dark-mode link text; use a lighter variant there. |
| **M8Shift gradient** | Keep, but constrain | Excellent for brand identity, title halo, icon banners, premium borders, and small visual anchors. Avoid using it as a large background or paragraph treatment. |
| **System colors** `#22C55E`, `#F59E0B`, `#EF4444`, `#7B8196` | Keep as semantic reference | Useful for validation, warning, error, and pending states. They should stay quieter than the brand colors. |
| **Slate Text** `#2B3045` and **Silver White** `#F4F4F2` | Keep as reference | Useful for custom surfaces and assets. VitePress' own text tokens can remain the default for normal documentation pages. |

## Set Aside For Now

| Item | Status | Why |
|---|---|---|
| **M8 Night** `#070B1F` and **Deep Navy** `#11183A` as main site backgrounds | Set aside for VitePress | They fit a premium dark product site, especially the Astro prototype, but would make the VitePress documentation feel heavier and less readable. |
| **Robot White** `#FFF8F0`, **Soft Apricot** `#F7C789`, and large warm panels | Set aside for VitePress | They risk pushing the documentation into a beige/cream palette. Use only in small assets or illustrations if needed. |
| **Soft Lavender** `#BA68F3` and **Soft Panel** `#F7F5FF` as broad surfaces | Set aside for now | They are useful in a full design system, but VitePress already has neutral surface tokens. Adding more panel colors would increase visual noise. `#BA68F3` remains useful as a dark-mode accent, not as a broad surface. |
| **Burnt Orange** `#AD2F0A` | Set aside for general UI | Too heavy for common UI. Keep only for rare contrast/shadow work on light backgrounds. |
| Full orange to pink to purple gradient as a text-bearing CTA background | Set aside for accessible buttons | White text fails on the orange/coral side, while dark text fails on the purple side. Use the gradient for borders, halos, icons, or non-text backgrounds instead. |
| Applying every secondary token immediately | Set aside | The current site is still documentation-first. Too many accents would make the CSS harder to maintain and weaken the core orange/pink/purple identity. |

## Practical Mapping

Recommended next cleanup for the current VitePress site. These reuse the canonical
token names from the palette file, so the project stays on one naming scheme:

```css
:root {
  --color-m8-orange: #FF7A18;
  --color-flow-coral: #FB6F74;
  --color-relay-pink: #F252BF;
  --color-shift-purple: #5D26F2;
  --color-deep-violet: #2D09A4;
  --color-electric-violet: #8B47F9;
}
```

VitePress drives links with `--vp-c-brand-1` in both color modes, so purple needs two
values. A single value cannot pass contrast on both white and `#070B1F`:

```css
:root {
  --vp-c-brand-1: #5D26F2; /* 7.0:1 on white */
}

.dark {
  --vp-c-brand-1: #BA68F3; /* 5.9:1 on #070B1F */
}
```

## Migration Notes

- replace `#F0509C` with `#F252BF`;
- replace `#7C3AED` with `#5D26F2` for light mode and add the `.dark` override above;
- keep `#FF7A18` unchanged;
- keep gradients subtle and mostly low-opacity on documentation surfaces;
- use a solid accessible color for primary CTAs, with the gradient as a border, glow,
  or adjacent accent instead of the text-bearing surface.

## Consequences

The VitePress site keeps a restrained documentation feel while becoming more aligned
with the M8Shift logo. The full palette remains available for richer product surfaces,
especially the Astro prototype, without forcing VitePress into a heavier visual system.
