#!/usr/bin/env python3
"""cowork.py — relais mono-fichier Claude <-> Codex, portable sur tout projet.

Modele : copier CE seul fichier a la racine d'un projet, puis `./cowork.py init`.
`init` (re)genere COWORK.md + COWORK.protocol.md et injecte les ancrages dans
CLAUDE.md / AGENTS.md. Le verrou (mutex) est le bloc LOCK en tete de COWORK.md,
delimite par les commentaires HTML COWORK:LOCK:BEGIN / COWORK:LOCK:END. Les tours
sont delimites par COWORK:TURN <n> <agent> BEGIN / END. Voir COWORK.protocol.md.
"""
import argparse
import contextlib
import datetime as dt
import os
import re
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
COWORK = os.path.join(HERE, "COWORK.md")
ARCHIVE = os.path.join(HERE, "COWORK.archive.md")
PROTO = os.path.join(HERE, "COWORK.protocol.md")
LOCKFILE = os.path.join(HERE, ".cowork.lock")  # verrou inter-process (O_EXCL)
LOCK_TIMEOUT = 10        # s : attente max pour acquérir le verrou interne
LOCK_STALE_S = 60        # s : au-delà, un .cowork.lock est réputé abandonné
TTL_MIN = 30
AGENTS = ("claude", "codex")
# Sous-chaînes réservées au format : interdites dans les champs, neutralisées dans les corps.
RESERVED = ("COWORK:TURN", "COWORK:LOCK", "COWORK:STANZA")

LOCK_BEGIN = "<!-- COWORK:LOCK:BEGIN -->"
LOCK_END = "<!-- COWORK:LOCK:END -->"
STANZA_BEGIN = "<!-- COWORK:STANZA:BEGIN (genere par cowork.py init - ne pas editer a la main) -->"
STANZA_END = "<!-- COWORK:STANZA:END -->"

# Variantes de noms de fichiers d'ancrage, par ordre de preference si aucune n'existe.
CLAUDE_NAMES = ("CLAUDE.md", "claude.md", "Claude.md")
CODEX_NAMES = ("AGENTS.md", "agents.md", "Agents.md")


# ----------------------------------------------------------------- templates

COWORK_TEMPLATE = r"""<!-- ╔════════════════════════════════════════════════════════════╗
     ║  COWORK · relais mono-fichier Claude ⇄ Codex · protocole v1 ║
     ║  Lis COWORK.protocol.md AVANT d'écrire ici.                 ║
     ╚════════════════════════════════════════════════════════════╝ -->

# COWORK · __PROJECT__

> Fichier de travail partagé. **Un seul agent écrit à la fois.** Le verrou est le
> bloc `LOCK` ci-dessous. N'écris que si `state == AWAITING_<toi>`. Détails →
> [COWORK.protocol.md](COWORK.protocol.md). Outil → `./cowork.py status`.

<!-- COWORK:LOCK:BEGIN -->
holder:   none
state:    IDLE
turn:     0
since:    __NOW__
expires:  -
note:     session initialisée, aucun tour ouvert
<!-- COWORK:LOCK:END -->

---

## Journal des tours

<!-- Les tours s'empilent ci-dessous, du plus ancien au plus récent.        -->
<!-- Format d'un tour : voir COWORK.protocol.md §3. Ne jamais éditer un tour -->
<!-- déjà clôturé (END posé) : on ajoute un nouveau tour à la place.         -->

<!-- COWORK:TURN 0 system BEGIN -->
- from:    system
- to:      none
- ask:     —
- done:    Initialisation du relais. Le premier agent qui veut démarrer fait
           `./cowork.py append claude --to codex --ask "..." --done "..."`
           (ou l'inverse), ce qui ouvre le tour 1 et passe la main.
- files:   COWORK.md, COWORK.protocol.md, cowork.py
- handoff: none
<!-- COWORK:TURN 0 system END -->
"""

PROTOCOL_TEMPLATE = r"""# COWORK · Protocole de relais mono-fichier (v1)

Instruction commune à **Claude** et **Codex** pour coopérer via un seul fichier
`COWORK.md`, en alternance stricte (mutex), avec poll périodique. Portable : ce
protocole est identique dans tout projet ; seul le titre de `COWORK.md` change.

À lire **une fois en début de session** dès que tu vois un `COWORK.md` à la
racine d'un projet. Tu es soit `claude`, soit `codex` — identifie-toi.

---

## 0. TL;DR — opère sans aide humaine

Tu viens d'arriver dans le projet et tu vois un `COWORK.md` : voici la boucle
complète, copiable, **aucune autre instruction n'est nécessaire**. `<toi>` vaut
`claude` ou `codex` (selon ton ancrage `CLAUDE.md` / `AGENTS.md`), `<autre>`
l'autre agent.

```bash
# 1. Suis-je attendu ? (commandes NON bloquantes)
./cowork.py status                 # lis le champ `state`
./cowork.py wait <toi> --once      # rc 0 = c'est à toi ; rc 3 = pas encore

# 2. Si c'est ton tour (state == AWAITING_<TOI> ou IDLE) : lis le `ask:` que
#    <autre> t'a laissé dans le dernier tour de COWORK.md — en IDLE / tour 0, il
#    n'y a pas d'`ask:` réel à honorer, tu démarres librement. Fais le travail
#    dans le dépôt, PUIS dépose ton tour et passe la main en une commande :
./cowork.py append <toi> --to <autre> \
    --ask "ce que tu attends de l'autre" \
    --done "ce que tu viens de faire" \
    --files fichier1,fichier2

# 3. Si ce n'est PAS ton tour : ne touche à rien d'autre. Soit tu fais autre
#    chose et reviendras, soit tu bloques jusqu'à ton tour :
./cowork.py wait <toi>             # poll toutes les ~60 s (--interval N)
```

Règle d'or : **tu n'écris dans le dépôt que si le verrou t'est attribué.** Tout
le reste de ce document n'est que le détail de cette boucle.

---

## 1. Modèle mental

- **Un seul fichier vivant** : `COWORK.md`. Tout le dialogue de travail y est.
- **Un seul stylo** : le bloc `LOCK` en tête dit qui le tient. Tu n'écris dans le
  fichier **que** si le verrou t'est attribué.
- **Alternance stricte** : claude → codex → claude → … Chaque passage de main
  est un *tour* (`TURN`) numéroté, encadré `BEGIN`/`END`.
- **Poll** : quand ce n'est pas ton tour, tu attends et tu relis `LOCK` toutes
  les **~60 s** (`./cowork.py wait <toi>`), jusqu'à ce que `state == AWAITING_<toi>`.

---

## 2. Le bloc LOCK (le mutex)

Délimité par `<!-- COWORK:LOCK:BEGIN -->` … `<!-- COWORK:LOCK:END -->`.
Champs (un `clé: valeur` par ligne, faciles à `grep`) :

| champ     | valeurs | sens |
|-----------|---------|------|
| `holder`  | `claude` \| `codex` \| `none` | qui tient le stylo |
| `state`   | `IDLE` \| `WORKING_CLAUDE` \| `WORKING_CODEX` \| `AWAITING_CLAUDE` \| `AWAITING_CODEX` \| `DONE` | état courant |
| `turn`    | entier | numéro du dernier tour clôturé |
| `since`   | ISO-8601 UTC | depuis quand cet état dure |
| `expires` | ISO-8601 UTC \| `-` | échéance de reprise anti-blocage (TTL 30 min) |
| `note`    | texte court | mémo lisible |

> `expires` ne porte une date **que** pendant `WORKING_*` (un agent travaille,
> TTL 30 min). Il repasse à `-` dès qu'on attend (`AWAITING_*`, `IDLE`, `DONE`) :
> personne ne tient le stylo, donc pas de péremption à surveiller.

**Lecture des états :**
- `AWAITING_CLAUDE` → c'est à Claude de jouer (Codex attend).
- `WORKING_CODEX` → Codex tient le stylo et travaille (Claude attend, ne touche à rien).
- `IDLE` → personne n'a la main, le premier qui a quelque chose à dire démarre.
- `DONE` → session close, plus de relais attendu.

---

## 3. Format d'un tour

```
<!-- COWORK:TURN <n> <agent> BEGIN -->
- from:    <agent>           # claude | codex
- to:      <agent|none>      # à qui tu repasses la main
- ask:     <ce que tu attends de l'autre, précis et actionnable>
- done:    <ce que tu viens de faire>
- files:   <fichiers touchés, séparés par des virgules>
- handoff: <agent|none>      # = to ; redondance volontaire, grep-friendly
<ligne vide>
<corps libre : explications, questions, blocs de code, listes>
<!-- COWORK:TURN <n> <agent> END -->
```

Règles :
- Un tour **clôturé** (`END` posé) est **immuable**. Pour réagir, tu ouvres le
  tour suivant. Jamais de réécriture rétroactive.
- `ask` doit être actionnable : l'autre agent doit pouvoir démarrer sans te
  reposer de question. Si tu n'attends rien (juste un FYI), mets `ask: —`.
- Garde un tour **borné** : si ça dépasse ~150 lignes ou plusieurs sujets,
  découpe en plusieurs tours successifs (un sujet = un tour).

---

## 4. Cycle de travail (la boucle de chaque agent)

```
boucle:
  1. lire LOCK
  2. si state == AWAITING_<moi>  (ou IDLE et j'ai qqch à dire) :
       a. CLAIM  : holder=moi, state=WORKING_<MOI>, since=now, expires=now+30min
       b. (re-lire LOCK : confirmer que turn n'a pas bougé → sinon abandonner, conflit)
       c. TRAVAILLER (éditer le code/contenu hors COWORK.md)
       d. APPEND  : écrire mon tour <turn+1> BEGIN…END en bas du journal
       e. RELEASE : holder=<autre>, state=AWAITING_<AUTRE>, turn=<turn+1>, since=now
  3. sinon si state == WORKING_<autre> ou AWAITING_<autre> :
       attendre ~60 s, retourner en 1
  4. sinon si state == DONE :
       sortir
```

En pratique, `./cowork.py` fait CLAIM+APPEND+RELEASE en une commande atomique
(`append`), et la boucle d'attente (`wait`).

> **Modèle de concurrence** : les commandes qui mutent l'état prennent d'abord un
> **verrou inter-process** (`.cowork.lock`, créé en `O_CREAT|O_EXCL`), puis font
> le read-modify-write *à l'intérieur* de ce verrou et une écriture atomique
> (fichier temporaire unique + `os.replace`). Deux `cowork.py` concurrents sont
> donc **sérialisés** : le double-démarrage depuis `IDLE` est impossible (le 2ᵉ
> relit le LOCK et voit que ce n'est plus son tour). Un `.cowork.lock` abandonné
> (process tué) est récupéré après 60 s.
> *Limites* : le verrou est **conseillé** (une édition manuelle de `COWORK.md`
> hors outil le contourne) ; sur un FS réseau (NFS) les sémantiques `O_EXCL` /
> `rename` peuvent être plus faibles — cowork vise un dépôt sur disque local.

---

## 5. Anti-blocage (lock périmé)

Si l'autre agent crashe en tenant le stylo, le verrou resterait coincé. Garde-fou :
- au CLAIM, on pose `expires = now + 30 min` ;
- si tu vois `state == WORKING_<autre>` **et** `now > expires`, le verrou est
  **périmé** : reprends-le avec `./cowork.py claim <toi> --force`, puis ouvre un
  tour notant la reprise (`done: reprise après lock périmé de <autre>`) ;
- **l'outil applique la règle** : `--force` est **refusé** sur un verrou encore
  valide. Tu ne peux donc pas voler le stylo d'un agent actif (c'est voulu) ;
- tu peux **rafraîchir ton propre** verrou avant péremption : `./cowork.py claim
  <toi>` quand tu le détiens déjà repose `expires` à +30 min ;
- `release` et `done` n'agissent que si **tu** tiens le stylo (ou si personne ne
  le tient) ; `--force` outrepasse, réservé à la récupération.

---

## 6. Tenue dans le temps (longueur bornée)

`COWORK.md` ne doit pas gonfler indéfiniment :
- garde dans `COWORK.md` le bloc `LOCK` + les **~6 derniers tours** ;
- `./cowork.py archive --keep 6` déplace les tours plus anciens (déjà clôturés)
  vers `COWORK.archive.md` (append), sans jamais toucher au verrou ni au dernier
  tour ouvert.
- L'archive est consultable mais n'est **jamais** relue par la boucle : seule la
  partie vivante de `COWORK.md` pilote le relais.

---

## 7. Outil `cowork.py`

```
./cowork.py init [--name PROJET] [--force]        # (re)génère le kit dans CE dossier
./cowork.py status                                # verrou + dernier tour (NON bloquant)
./cowork.py wait <agent> [--once] [--interval N]  # attend ton tour ; --once = 1 check (rc 3 si pas ton tour)
./cowork.py claim <agent> [--force]               # prendre le verrou (ton tour / IDLE / ton propre verrou ;
                                                  #   --force = verrou périmé UNIQUEMENT)
./cowork.py append <agent> --to <autre> \
     --ask "..." --done "..." [--files a,b] [--body fichier.md|-]   # tour + passe la main
./cowork.py release <agent> --to <autre> [--force]  # repasser la main sans corps (ne ré-incrémente PAS turn)
./cowork.py done <agent> [--force]                 # clore la session (state=DONE)
./cowork.py archive [--keep N]                     # purge les vieux tours clôturés (jamais le tour #0)
```

- `append` est l'opération principale : elle ouvre le tour suivant **et** repasse
  la main en un seul geste. `--body -` lit le corps depuis stdin ; `--body f.md`
  depuis un fichier ; sans `--body`, le tour n'a que l'en-tête.
- `--to` doit viser **l'autre** agent (auto-passation refusée : alternance stricte).
- Inspection **non bloquante** : `status` ou `wait <toi> --once`. `wait <toi>`
  **sans** `--once` bloque jusqu'à ton tour — ne l'utilise pas si tu dois rendre
  la main à ta boucle entre-temps.

---

## 8. Adoption par tout projet (portabilité)

`cowork.py` est **auto-suffisant** : il embarque ce protocole, le gabarit de
`COWORK.md` et les ancrages. Pour adopter le relais dans un projet :

```bash
cp /chemin/vers/cowork.py .      # copier le seul fichier nécessaire
./cowork.py init                 # nom du projet = nom du dossier (sinon --name)
```

`init` :
- écrit `COWORK.protocol.md` (ce document) et `COWORK.md` (verrou IDLE neuf) ;
  `COWORK.md` n'est **pas** écrasé s'il existe déjà (sauf `--force`) → l'état du
  relais en cours est préservé ;
- injecte un bloc « Co-work relais » dans `CLAUDE.md` et `AGENTS.md` (créés s'ils
  manquent), entre marqueurs `COWORK:STANZA` → ré-injection **idempotente**
  (remplace le bloc existant au lieu de le dupliquer), le reste du fichier intact.
  La détection est **insensible à la casse** : un `claude.md`/`agents.md`
  préexistant est réutilisé tel quel (pas de doublon majuscule créé).

Claude lit `CLAUDE.md`, Codex lit `AGENTS.md` : les deux ancrages pointent vers ce
protocole, et chaque agent sait alors quoi faire en voyant un `COWORK.md`.
"""

STANZA_TEMPLATE = """{begin}
## Co-work relais (Claude ⇄ Codex) — autonome, aucune aide humaine requise

Tu es **{me}** dans ce projet. Dès qu'un `COWORK.md` est présent à la racine,
c'est ta source de coordination avec **{other}** : applique `COWORK.protocol.md`
(lis-le une fois, voir son §0) AVANT tout autre travail. **Tu n'écris dans le
dépôt que si le verrou t'est attribué.**

```bash
./cowork.py status                # qui a la main ? (non bloquant)
./cowork.py wait {me} --once      # rc 0 = à toi de jouer ; rc 3 = pas encore
```

- **Ton tour** (`state == AWAITING_{ME}` ou `IDLE`) : lis le `ask:` que {other} t'a
  laissé dans le dernier tour de `COWORK.md` (en `IDLE`/tour 0, rien à honorer :
  démarre librement), fais le travail, puis dépose-le et passe la main :
  `./cowork.py append {me} --to {other} --ask "…" --done "…" [--files a,b]`
- **Pas ton tour** : ne touche à rien ; `./cowork.py wait {me}` bloque jusqu'à ton
  tour (poll ~60 s), ou reviens plus tard.
- **Verrou de {other} périmé** (`WORKING_{OTHER}` + `now > expires`) :
  `./cowork.py claim {me} --force`.

Un tour clôturé est immuable : pour réagir, ouvre le tour suivant.
{end}"""


# ------------------------------------------------------------------- helpers

def now():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def iso(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s):
    s = (s or "").strip()
    if not s or s == "-":
        return None
    try:
        return dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return None


def read(path=COWORK):
    with open(path, encoding="utf-8") as f:
        return f.read()


def write(text, path=COWORK):
    """Écriture atomique : fichier temporaire UNIQUE (par process) + os.replace."""
    d = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".cowork-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)  # remplacement atomique
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


@contextlib.contextmanager
def file_lock(timeout=LOCK_TIMEOUT):
    """Verrou inter-process via création exclusive d'un fichier (O_CREAT|O_EXCL).

    Sérialise le read-modify-write du LOCK : empêche deux `cowork.py` concurrents
    de muter `COWORK.md` en même temps (y compris le double-démarrage depuis IDLE).
    Un `.cowork.lock` plus vieux que LOCK_STALE_S (process mort) est récupéré.
    """
    start = time.monotonic()
    while True:
        try:
            fd = os.open(LOCKFILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            break
        except FileExistsError:
            try:
                if time.time() - os.path.getmtime(LOCKFILE) > LOCK_STALE_S:
                    os.unlink(LOCKFILE)  # verrou abandonné → on le reprend
                    continue
            except OSError:
                pass
            if time.monotonic() - start > timeout:
                sys.exit("verrou interne occupé (un autre cowork.py écrit) — réessaie.")
            time.sleep(0.05)
    try:
        yield
    finally:
        with contextlib.suppress(OSError):
            os.unlink(LOCKFILE)


def require_cowork():
    if not os.path.exists(COWORK):
        sys.exit("COWORK.md introuvable — lance d'abord `./cowork.py init`.")


def load_or_die():
    """Lit COWORK.md en validant la présence du bloc LOCK (sortie propre sinon)."""
    require_cowork()
    text = read()
    if LOCK_BEGIN not in text or LOCK_END not in text:
        sys.exit("COWORK.md corrompu : bloc LOCK introuvable — "
                 "`./cowork.py init --force` pour réinitialiser le verrou.")
    return text


def clean_field(label, val):
    """Champ mono-ligne : refuse sauts de ligne et marqueurs réservés (anti-injection)."""
    val = (val or "").strip()
    if "\n" in val or "\r" in val:
        sys.exit(f"refus: {label} ne doit pas contenir de saut de ligne.")
    for r in RESERVED:
        if r in val:
            sys.exit(f"refus: {label} contient un marqueur réservé ({r}).")
    return val


def clean_body(text):
    """Corps multi-ligne : neutralise tout marqueur réservé injecté (zero-width
    après `COWORK`), pour qu'il ne puisse pas se faire passer pour un vrai tour."""
    return text.replace("COWORK:", "COWORK​:")


def get_lock(text):
    i = text.index(LOCK_BEGIN) + len(LOCK_BEGIN)
    j = text.index(LOCK_END)
    fields = {}
    for line in text[i:j].splitlines():
        line = line.strip()
        m = re.match(r"([a-z_]+):\s*(.*)$", line)
        if m:
            fields[m.group(1)] = m.group(2).strip()
    return fields


def set_lock(text, fields):
    i = text.index(LOCK_BEGIN) + len(LOCK_BEGIN)
    j = text.index(LOCK_END)
    body = "\n" + "\n".join(
        f"{k}:{' ' * max(1, 9 - len(k))}{v}"
        for k, v in fields.items()
    ) + "\n"
    return text[:i] + body + text[j:]


def other(agent):
    return "codex" if agent == "claude" else "claude"


def need_agent(a):
    if a not in AGENTS:
        sys.exit(f"agent invalide: {a!r} (attendu: {' | '.join(AGENTS)})")
    return a


# ---------------------------------------------------------------- init / anchors

def pick_anchor(names):
    """Retourne le nom RÉEL on-disk d'une variante existante (insensible à la
    casse), sinon names[0]. Évite un rapport trompeur sur FS case-insensitive."""
    try:
        on_disk = {f.lower(): f for f in os.listdir(HERE)}
    except OSError:
        on_disk = {}
    for n in names:
        if n.lower() in on_disk:
            return on_disk[n.lower()]
    return names[0]


def stanza_for(me):
    o = other(me)
    return STANZA_TEMPLATE.format(
        begin=STANZA_BEGIN, end=STANZA_END,
        me=me, ME=me.upper(), other=o, OTHER=o.upper(),
    )


def inject_anchor(filename, me):
    path = os.path.join(HERE, filename)
    block = stanza_for(me)
    if os.path.exists(path):
        cur = read(path)
        if STANZA_BEGIN in cur and STANZA_END in cur:
            # remplacement idempotent du bloc existant
            pat = re.compile(
                re.escape(STANZA_BEGIN) + r".*?" + re.escape(STANZA_END),
                re.DOTALL,
            )
            new = pat.sub(lambda _m: block, cur)
            action = "stanza remplacée"
        else:
            new = cur.rstrip("\n") + "\n\n" + block + "\n"
            action = "stanza ajoutée"
    else:
        new = f"# {filename}\n\n" + block + "\n"
        action = "fichier créé"
    write(new, path)
    return f"{filename}: {action}"


def cmd_init(args):
    name = args.name or os.path.basename(HERE) or "projet"
    results = []

    with file_lock():
        # protocole : source canonique, (ré)écrit seulement s'il manque ou diffère
        if not os.path.exists(PROTO) or read(PROTO) != PROTOCOL_TEMPLATE:
            write(PROTOCOL_TEMPLATE, PROTO)
            results.append("COWORK.protocol.md: écrit")
        else:
            results.append("COWORK.protocol.md: déjà à jour")

        # cowork.md : préservé s'il existe (état du relais en cours), sauf --force
        if os.path.exists(COWORK) and not args.force:
            results.append("COWORK.md: préservé (existe déjà ; --force pour réinitialiser)")
        else:
            text = COWORK_TEMPLATE.replace("__PROJECT__", name).replace("__NOW__", iso(now()))
            write(text, COWORK)
            results.append(f"COWORK.md: écrit (projet « {name} », verrou IDLE)")

        # ancrages
        results.append(inject_anchor(pick_anchor(CLAUDE_NAMES), "claude"))
        results.append(inject_anchor(pick_anchor(CODEX_NAMES), "codex"))

    print(f"✓ cowork init — projet « {name} » dans {HERE}")
    for r in results:
        print(f"  • {r}")
    print("Démarrer : ./cowork.py append claude --to codex --ask \"…\" --done \"…\"")
    return 0


# ---------------------------------------------------------------- commandes relais

def cmd_status(args):
    text = load_or_die()
    lk = get_lock(text)
    exp = parse_iso(lk.get("expires"))
    stale = (
        lk.get("state", "").startswith("WORKING_")
        and exp is not None
        and now() > exp
    )
    print("── LOCK ───────────────────────────────")
    for k in ("holder", "state", "turn", "since", "expires", "note"):
        print(f"  {k:<8} {lk.get(k, '')}")
    if stale:
        print("  ⚠ verrou PERIME — reprenable avec: claim <toi> --force")
    turns = re.findall(r"COWORK:TURN (\d+) (\w+) BEGIN", text)
    if turns:
        n, who = turns[-1]
        print(f"── dernier tour: #{n} par {who}")
    return 0


def cmd_wait(args):
    agent = need_agent(args.agent)
    if not args.once and args.interval < 1:
        sys.exit("--interval doit être un entier >= 1.")
    target = f"AWAITING_{agent.upper()}"
    while True:
        lk = get_lock(load_or_die())
        st = lk.get("state", "")
        if st in (target, "IDLE"):
            print(f"✓ a toi de jouer ({st}).")
            return 0
        if st == "DONE":
            print("session DONE — rien a attendre.")
            return 0
        exp = parse_iso(lk.get("expires"))
        if st == f"WORKING_{other(agent).upper()}" and exp and now() > exp:
            print(f"⚠ verrou de {other(agent)} PERIME — claim --force possible.")
            return 0
        if args.once:  # poll unique, non bloquant : rc=3 = pas (encore) ton tour
            print(f"… pas ton tour: {st} (holder={lk.get('holder')}).")
            return 3
        print(f"… {st} (holder={lk.get('holder')}), nouvelle verif dans {args.interval}s")
        time.sleep(args.interval)


def cmd_claim(args):
    agent = need_agent(args.agent)
    with file_lock():
        text = load_or_die()
        lk = get_lock(text)
        st = lk.get("state", "")
        holder = lk.get("holder", "none")
        exp = parse_iso(lk.get("expires"))
        stale = st.startswith("WORKING_") and exp is not None and now() > exp
        # ton tour / IDLE / ton propre verrou (refresh du TTL) ; --force UNIQUEMENT si périmé.
        mine = st in ("IDLE", f"AWAITING_{agent.upper()}", f"WORKING_{agent.upper()}")
        if not (mine or (args.force and stale)):
            if args.force and st.startswith("WORKING_"):
                sys.exit(f"refus: verrou de {holder} encore valide (expire {lk.get('expires')}). "
                         f"--force ne reprend qu'un verrou périmé (protocole §5).")
            sys.exit(f"refus: state={st}, holder={holder} — ce n'est pas ton tour.")
        reclaim = args.force and stale and holder not in (agent, "none")
        t = now()
        lk.update(
            holder=agent,
            state=f"WORKING_{agent.upper()}",
            since=iso(t),
            expires=iso(t + dt.timedelta(minutes=TTL_MIN)),
            note=(f"reprise après lock périmé de {holder}" if reclaim
                  else f"{agent} tient le stylo"),
        )
        write(set_lock(text, lk))
    suffix = " — reprise lock périmé" if reclaim else ""
    print(f"✓ verrou pris par {agent} (expire {lk['expires']}{suffix}).")
    return 0


def _read_body(spec):
    if not spec:
        return ""
    if spec == "-":
        return sys.stdin.read().rstrip("\n")
    try:
        with open(spec, encoding="utf-8") as f:
            return f.read().rstrip("\n")
    except OSError as e:
        sys.exit(f"--body: {e}")


def cmd_append(args):
    agent = need_agent(args.agent)
    to = need_agent(args.to)
    if to == agent:
        sys.exit("refus: --to doit viser l'autre agent (alternance stricte, protocole §1).")
    # validation/lecture hors section critique (stdin peut bloquer)
    ask = clean_field("--ask", args.ask) or "—"
    done = clean_field("--done", args.done) or "—"
    files = clean_field("--files", args.files) or "—"
    body = clean_body(_read_body(args.body))

    with file_lock():
        text = load_or_die()
        lk = get_lock(text)
        st = lk.get("state", "")
        exp = parse_iso(lk.get("expires"))
        stale = st.startswith("WORKING_") and exp is not None and now() > exp
        mine = st in ("IDLE", f"AWAITING_{agent.upper()}", f"WORKING_{agent.upper()}")
        if not (mine or (args.force and stale)):
            sys.exit(f"refus: state={st} — claim d'abord, ou ce n'est pas ton tour.")
        n = int(lk.get("turn", "0")) + 1
        block = (
            f"<!-- COWORK:TURN {n} {agent} BEGIN -->\n"
            f"- from:    {agent}\n"
            f"- to:      {to}\n"
            f"- ask:     {ask}\n"
            f"- done:    {done}\n"
            f"- files:   {files}\n"
            f"- handoff: {to}\n"
        )
        if body:
            block += "\n" + body + "\n"
        block += f"<!-- COWORK:TURN {n} {agent} END -->\n"

        # inserer le tour a la fin du fichier (journal append-only)
        text = text.rstrip("\n") + "\n\n" + block

        t = now()
        lk.update(
            holder=to,
            state=f"AWAITING_{to.upper()}",
            turn=str(n),
            since=iso(t),
            expires="-",
            note=f"tour {n} pose par {agent}, en attente de {to}",
        )
        write(set_lock(text, lk))
    print(f"✓ tour {n} ecrit par {agent}, main passee a {to}.")
    return 0


def cmd_release(args):
    agent = need_agent(args.agent)
    to = need_agent(args.to)
    if to == agent:
        sys.exit("refus: --to doit viser l'autre agent.")
    with file_lock():
        text = load_or_die()
        lk = get_lock(text)
        holder = lk.get("holder", "none")
        if holder not in (agent, "none") and not args.force:
            sys.exit(f"refus: {holder} tient le stylo, pas toi (--force pour outrepasser).")
        t = now()
        lk.update(
            holder=to, state=f"AWAITING_{to.upper()}",
            since=iso(t), expires="-",
            note=f"main passee a {to} par {agent} (sans tour)",
        )
        write(set_lock(text, lk))
    print(f"✓ main passee a {to}.")
    return 0


def cmd_done(args):
    agent = need_agent(args.agent)
    with file_lock():
        text = load_or_die()
        lk = get_lock(text)
        holder = lk.get("holder", "none")
        if holder not in (agent, "none") and not args.force:
            sys.exit(f"refus: {holder} tient le stylo, pas toi (--force pour clore quand même).")
        t = now()
        lk.update(holder="none", state="DONE", since=iso(t), expires="-",
                  note=f"session close par {agent}")
        write(set_lock(text, lk))
    print("✓ session DONE.")
    return 0


def cmd_archive(args):
    pat = re.compile(
        r"<!-- COWORK:TURN (\d+) (\w+) BEGIN -->.*?<!-- COWORK:TURN \1 \2 END -->\n?",
        re.DOTALL,
    )
    keep = max(0, args.keep)
    with file_lock():
        text = load_or_die()
        # le tour d'amorçage #0 (system) reste toujours dans le fichier vivant
        matches = [m for m in pat.finditer(text) if m.group(1) != "0"]
        if len(matches) <= keep:
            print(f"rien a archiver ({len(matches)} tour(s) archivable(s), keep={keep}).")
            return 0
        to_move = matches[:-keep] if keep else matches
        moved = "".join(m.group(0) for m in to_move)
        # retirer du vivant (du dernier vers le premier pour garder les offsets)
        for m in reversed(to_move):
            text = text[:m.start()] + text[m.end():]
        text = re.sub(r"\n{3,}", "\n\n", text)
        prev = read(ARCHIVE) if os.path.exists(ARCHIVE) else "# COWORK · archive des tours\n\n"
        write(prev + moved, ARCHIVE)  # écriture atomique (tmp + os.replace)
        write(text)
    print(f"✓ {len(to_move)} tour(s) archive(s) → {os.path.basename(ARCHIVE)} (gardes: {keep}).")
    return 0


def main():
    p = argparse.ArgumentParser(description="Relais mono-fichier Claude <-> Codex (portable).")
    sub = p.add_subparsers(dest="cmd", required=True)

    i = sub.add_parser("init", help="(re)génère le kit dans ce dossier")
    i.add_argument("--name", default="")
    i.add_argument("--force", action="store_true", help="réinitialise aussi COWORK.md")
    i.set_defaults(fn=cmd_init)

    sub.add_parser("status").set_defaults(fn=cmd_status)

    w = sub.add_parser("wait")
    w.add_argument("agent")
    w.add_argument("--interval", type=int, default=60)
    w.add_argument("--once", action="store_true", help="vérifie une fois et sort (rc 3 si pas ton tour)")
    w.set_defaults(fn=cmd_wait)

    c = sub.add_parser("claim")
    c.add_argument("agent")
    c.add_argument("--force", action="store_true")
    c.set_defaults(fn=cmd_claim)

    a = sub.add_parser("append")
    a.add_argument("agent")
    a.add_argument("--to", required=True)
    a.add_argument("--ask", default="")
    a.add_argument("--done", default="")
    a.add_argument("--files", default="")
    a.add_argument("--body", default="")
    a.add_argument("--force", action="store_true")
    a.set_defaults(fn=cmd_append)

    r = sub.add_parser("release")
    r.add_argument("agent")
    r.add_argument("--to", required=True)
    r.add_argument("--force", action="store_true")
    r.set_defaults(fn=cmd_release)

    d = sub.add_parser("done")
    d.add_argument("agent")
    d.add_argument("--force", action="store_true")
    d.set_defaults(fn=cmd_done)

    ar = sub.add_parser("archive")
    ar.add_argument("--keep", type=int, default=6)
    ar.set_defaults(fn=cmd_archive)

    args = p.parse_args()
    sys.exit(args.fn(args))


if __name__ == "__main__":
    main()
