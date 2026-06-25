# M8Shift — Brand Color Palette

Palette derived from the M8Shift logo: orange/purple loop, white robots, central document icon, and light wordmark.

---

## Implementation decisions

This file is the canonical brand palette. Site-specific adoption choices live in
[docs/en/decisions/vitepress-palette.md](../decisions/vitepress-palette.md).

---

## 1. Primary colors

| Name | Hex | Recommended use |
|---|---:|---|
| **M8 Orange** | `#FF7A18` | Main left-side color, primary CTA, warm accents |
| **Shift Purple** | `#5D26F2` | Main right-side color, active links, AI/tech elements |
| **Relay Pink** | `#F252BF` | Transition color, handoffs, active states, highlights |
| **Flow Coral** | `#FB6F74` | Secondary accent, hover states, badges, micro-interactions |
| **Deep Violet** | `#2D09A4` | Strong contrast, dark mode, colored shadows |

---

## 2. Brand gradient

```css
--m8shift-gradient: linear-gradient(
  90deg,
  #FF7A18 0%,
  #FB6F74 35%,
  #F252BF 55%,
  #8B47F9 75%,
  #5D26F2 100%
);
```

Recommended use:

- logo;
- primary buttons;
- active navigation links;
- premium borders;
- illustrations;
- `handoff`, `shift`, and `active` states.

Avoid using it for:

- long text blocks;
- heavy backgrounds;
- large surfaces that reduce readability.

---

## 3. Secondary colors

| Name | Hex | Recommended use |
|---|---:|---|
| **Warm Amber** | `#FD9F2C` | Orange hover states, secondary icons, illustrations |
| **Soft Apricot** | `#F7C789` | Light warm backgrounds, information cards |
| **Electric Violet** | `#8B47F9` | Bright violet accent, focus states, badges |
| **Soft Lavender** | `#BA68F3` | Light purple backgrounds, tags, secondary states |
| **Burnt Orange** | `#AD2F0A` | Warm shadows, contrast on light backgrounds |

---

## 4. Neutrals

| Name | Hex | Recommended use |
|---|---:|---|
| **M8 Night** | `#070B1F` | Main dark background |
| **Deep Navy** | `#11183A` | Dark cards, header, footer |
| **Slate Text** | `#2B3045` | Main text on light backgrounds |
| **Cool Gray** | `#7B8196` | Secondary text, metadata |
| **Robot White** | `#FFF8F0` | Warm white surfaces, robots, cards |
| **Silver White** | `#F4F4F2` | Light text, wordmark on dark backgrounds |
| **Soft Panel** | `#F7F5FF` | Light purple-tinted panel background |

---

## 5. UI state colors

| State | Color | Hex | Use |
|---|---|---:|---|
| **Success** | Green | `#22C55E` | Passing tests, approved validation |
| **Warning** | Amber | `#F59E0B` | Required validation, pending action |
| **Error** | Red | `#EF4444` | Conflict, refused lock, rejected validation |
| **Info** | Purple | `#5D26F2` | Active state, documentation, help |
| **Pending** | Gray | `#7B8196` | Pending task, inactive agent |

These state colors should remain more restrained than the brand colors. Otherwise the interface starts looking like a SaaS dashboard that escaped from a venture-capital pitch deck, and nobody asked for that tragedy.

---

## 6. Visual priority

1. **M8Shift gradient**: identity, hero sections, primary CTA.
2. **Orange + purple**: dual-agent identity.
3. **Pink / coral**: transition, handoff, role shift.
4. **Night blue**: technical seriousness, readability, premium background.
5. **Warm white**: breathing space, readability, accessibility.

---

## 7. Recommended ratio

| Use | Proportion |
|---|---:|
| Neutrals | 60% |
| Primary orange / purple | 25% |
| Transition pink / coral | 10% |
| System states | 5% |

---

## 8. Applications

### Primary button

For accessible CTAs, prefer a solid brand fill or a gradient border. Do not put white
text directly on the full orange→pink→purple gradient.

```css
.button-primary {
  background: #5D26F2;
  color: #FFFFFF;
}

.button-primary-gradient-border {
  background:
    linear-gradient(#5D26F2, #5D26F2) padding-box,
    linear-gradient(90deg, #FF7A18, #F252BF, #5D26F2) border-box;
  border: 1px solid transparent;
  color: #FFFFFF;
}
```

### Secondary button

```css
.button-secondary {
  background: #F7F5FF;
  color: #2D09A4;
  border: 1px solid #BA68F3;
}
```

### Dark background

```css
.page-dark {
  background: #070B1F;
  color: #F4F4F2;
}
```

### Light card

```css
.card-light {
  background: #FFF8F0;
  color: #2B3045;
  border: 1px solid #F7C789;
}
```

### Accessible focus

```css
:focus-visible {
  outline: 3px solid #8B47F9;
  outline-offset: 3px;
}
```

---

## 9. Complete CSS tokens

```css
:root {
  /* Brand */
  --color-m8-orange: #FF7A18;
  --color-shift-purple: #5D26F2;
  --color-relay-pink: #F252BF;
  --color-flow-coral: #FB6F74;
  --color-deep-violet: #2D09A4;

  /* Secondary */
  --color-warm-amber: #FD9F2C;
  --color-soft-apricot: #F7C789;
  --color-electric-violet: #8B47F9;
  --color-soft-lavender: #BA68F3;
  --color-burnt-orange: #AD2F0A;

  /* Neutral */
  --color-m8-night: #070B1F;
  --color-deep-navy: #11183A;
  --color-slate-text: #2B3045;
  --color-cool-gray: #7B8196;
  --color-robot-white: #FFF8F0;
  --color-silver-white: #F4F4F2;
  --color-soft-panel: #F7F5FF;

  /* States */
  --color-success: #22C55E;
  --color-warning: #F59E0B;
  --color-error: #EF4444;
  --color-info: #5D26F2;
  --color-pending: #7B8196;

  /* Gradients */
  --gradient-m8shift: linear-gradient(
    90deg,
    #FF7A18 0%,
    #FB6F74 35%,
    #F252BF 55%,
    #8B47F9 75%,
    #5D26F2 100%
  );

  --gradient-orange: linear-gradient(
    135deg,
    #FD9F2C 0%,
    #FF7A18 60%,
    #F16006 100%
  );

  --gradient-purple: linear-gradient(
    135deg,
    #BA68F3 0%,
    #8B47F9 45%,
    #5D26F2 100%
  );
}
```

---

## 10. Accessibility notes

For body text:

- use `#2B3045` on light backgrounds;
- use `#F4F4F2` on dark backgrounds;
- avoid long text in pure orange, pink, or violet;
- reserve saturated colors for accents, buttons, icons, and states;
- test contrast on CTAs, especially when using gradients.

The gradient is excellent for identity, but mediocre for paragraphs. Human eyes, in one of their few sensible design choices, still prefer stable backgrounds for reading.

---

## 11. Quick summary

```text
Orange  : energy, source agent, action
Pink    : transition, relay, handoff
Purple  : target agent, AI, coordination
Navy    : technical seriousness, premium background
White   : readability, robots, breathing space
```
