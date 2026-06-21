#!/usr/bin/env python3
"""cowork.py — single-file Claude <-> Codex relay, portable to any project.

Model: copy THIS single file to the root of a project, then `./cowork.py init`.
`init` (re)generates COWORK.md + COWORK.protocol.md and injects the anchors into
CLAUDE.md / AGENTS.md. The lock (mutex) is the LOCK block at the top of COWORK.md,
delimited by the HTML comments COWORK:LOCK:BEGIN / COWORK:LOCK:END. Turns are
delimited by COWORK:TURN <n> <agent> BEGIN / END. See COWORK.protocol.md.
"""
import argparse
import contextlib
import datetime as dt
import os
import re
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
COWORK = os.path.join(HERE, "COWORK.md")
ARCHIVE = os.path.join(HERE, "COWORK.archive.md")
PROTO = os.path.join(HERE, "COWORK.protocol.md")
LOCKFILE = os.path.join(HERE, ".cowork.lock")  # inter-process lock (O_EXCL)
LOCK_TIMEOUT = 10        # s: max wait to acquire the internal lock
LOCK_STALE_S = 60        # s: beyond this, a .cowork.lock is deemed abandoned
TTL_MIN = 30
LANGS = ("en", "fr")             # supported languages (catalog keys + CLI choices)
DEFAULT_LANG = "en"              # default / ultimate fallback language
AGENTS = ("claude", "codex")     # default active pair (exact backward-compat)
ROSTER = AGENTS                  # current ACTIVE pair (2 agents) — refined at runtime
AGENT_RE = r"[a-z][a-z0-9_-]*"   # normalized agent name (ASCII)
# Substrings reserved by the format: forbidden in fields, neutralized in bodies.
RESERVED = ("COWORK:TURN", "COWORK:LOCK", "COWORK:STANZA")

LOCK_BEGIN = "<!-- COWORK:LOCK:BEGIN -->"
LOCK_END = "<!-- COWORK:LOCK:END -->"
STANZA_BEGIN = "<!-- COWORK:STANZA:BEGIN (genere par cowork.py init - ne pas editer a la main) -->"
STANZA_END = "<!-- COWORK:STANZA:END -->"

# Canonical names auto-loaded by the host tools. Existing variants are renamed to
# these names during `init`, including via a two-step rename on case-insensitive
# filesystems.
CLAUDE_ANCHOR = "CLAUDE.md"
CODEX_ANCHOR = "AGENTS.md"
CODEX_OVERRIDE = "AGENTS.override.md"

# Anchor file auto-loaded by each known agent. Best-effort: an agent missing from
# the table gets a manual-bootstrap warning (cf. RFC roster §5).
ANCHORS = {
    "claude": "CLAUDE.md",
    "codex": "AGENTS.md",
    "gemini": "GEMINI.md",
    "lechat": "AGENTS.md",   # Le Chat / Mistral: best-effort (convention unconfirmed)
    "mistral": "AGENTS.md",
    # NOTE: nested-path anchors (e.g. GitHub Copilot's .github/copilot-instructions.md)
    # are out of stage 1 — ensure_canonical_anchor is not path-aware (no case handling
    # in subdirs). Such an agent falls back to a manual-bootstrap warning.
}

BRIDGE_FR = """## Instructions communes du projet

Lis et applique intégralement `CLAUDE.md`, qui contient les instructions communes
du projet pour Claude et Codex.
"""


# ----------------------------------------------------------------- templates

COWORK_FR = r"""<!-- ╔════════════════════════════════════════════════════════════╗
     ║  COWORK · relais mono-fichier multi-agents · protocole v1   ║
     ║  Lis COWORK.protocol.md AVANT d'écrire ici.                 ║
     ╚════════════════════════════════════════════════════════════╝ -->

# COWORK · __PROJECT__

> Fichier de travail partagé. **Un seul agent écrit à la fois.** Le verrou est le
> bloc `LOCK` ci-dessous. N'écris que si `state == AWAITING_<toi>`. Détails →
> [COWORK.protocol.md](COWORK.protocol.md). Outil → `./cowork.py status`.

<!-- COWORK:LOCK:BEGIN -->
holder:   none
state:    IDLE
agents:   __AGENTS__
lang:     __LANG__
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
- done:    Initialisation du relais. Le premier agent qui démarre fait
           `./cowork.py claim __A__` (ou `__B__`), travaille, puis
           `./cowork.py append __A__ --to __B__ --ask "..." --done "..."`.
- files:   COWORK.md, COWORK.protocol.md, cowork.py
- handoff: none
<!-- COWORK:TURN 0 system END -->
"""

PROTOCOL_FR = r"""# COWORK · Protocole de relais mono-fichier (v1)

Instruction commune aux **deux agents actifs** (par défaut **Claude** et **Codex**)
pour coopérer via un seul fichier
`COWORK.md`, en alternance stricte (mutex), avec poll périodique. Portable : ce
protocole est identique dans tout projet ; seul le titre de `COWORK.md` change.

À lire **une fois en début de session** dès que tu vois un `COWORK.md` à la
racine d'un projet. Tu es **l'un des deux agents actifs** déclarés dans le champ
`agents:` de `COWORK.md` (par défaut `claude` et `codex`) — identifie-toi par ton
fichier d'ancrage.

---

## 0. TL;DR — opère sans aide humaine

Tu viens d'arriver dans le projet et tu vois un `COWORK.md` : voici la boucle
complète, copiable, **aucune autre instruction n'est nécessaire**. `<toi>` est ton
propre nom d'agent et `<autre>` l'autre agent actif (le couple déclaré dans
`agents:` ; par défaut `claude` / `codex`, via les ancrages `CLAUDE.md` / `AGENTS.md`).

```bash
# 1. Suis-je attendu ? (commandes NON bloquantes)
./cowork.py status                 # lis le champ `state`
./cowork.py wait <toi> --once      # rc 0 = tu peux acquérir ; rc 3 = pas encore

# 2. ACQUIERS le stylo AVANT de travailler (acquisition EXCLUSIVE : sur deux agents
#    qui tentent en même temps, un seul réussit) :
./cowork.py claim <toi>            # rc 0 = tu tiens le stylo ; rc != 0 = pas ton tour
#    • Si claim RÉUSSIT : lis le `ask:` que <autre> t'a laissé dans le dernier
#      tour (en démarrage IDLE/tour 0, rien à honorer), fais le travail dans le
#      dépôt, PUIS enregistre ton tour et passe la main :
./cowork.py append <toi> --to <autre> \
    --ask "ce que tu attends de l'autre" \
    --done "ce que tu viens de faire" \
    --files fichier1,fichier2
#    • Si claim ÉCHOUE : ce n'est pas (ou plus) ton tour → reviens à l'attente.

# 3. Pas ton tour : ne touche à RIEN. Bloque jusqu'à ton tour, puis reprends en 2 :
./cowork.py wait <toi>             # poll toutes les ~60 s (--interval N)
```

Règle d'or : **tu ne travailles et n'écris que si tu as acquis le stylo via
`claim`.** `claim` est exclusif ; `append` n'est accepté que si tu tiens le
stylo. Tout le reste de ce document n'est que le détail de cette boucle.

---

## 1. Modèle mental

- **Un seul fichier vivant** : `COWORK.md`. Tout le dialogue de travail y est.
- **Un seul stylo, acquis explicitement** : pour travailler, tu **prends** le
  stylo via `claim` → état `WORKING_<toi>`. `claim` est **exclusif** (deux agents
  qui tentent en même temps : un seul réussit). Tu ne modifies le dépôt **que**
  pendant que tu tiens le stylo.
- **`append` clôt ton tour** : il n'est accepté que depuis `WORKING_<toi>`, écrit
  le tour et passe la main (`AWAITING_<autre>`). Pas de `claim` ⇒ pas d'`append`.
- **Alternance stricte** : les deux agents actifs alternent (p. ex. `claude` →
  `codex` → `claude` …). Chaque passage de main est un *tour* (`TURN`) numéroté,
  encadré `BEGIN`/`END`.
- **Poll** : quand ce n'est pas ton tour, tu attends (`./cowork.py wait <toi>`,
  ~60 s) puis tu retentes `claim`.

---

## 2. Le bloc LOCK (le mutex)

Délimité par `<!-- COWORK:LOCK:BEGIN -->` … `<!-- COWORK:LOCK:END -->`.
Champs (un `clé: valeur` par ligne, faciles à `grep`) :

| champ     | valeurs | sens |
|-----------|---------|------|
| `holder`  | un agent actif \| `none` | qui tient le stylo (défaut `claude`/`codex`) |
| `state`   | `IDLE` \| `WORKING_<X>` \| `AWAITING_<X>` \| `DONE` | état courant (`<X>` = un agent actif, en majuscules) |
| `agents`  | CSV, ex. `claude,codex` | le couple du relais (les 2 premiers déclarés) ; défaut `claude,codex` |
| `turn`    | entier | numéro du dernier tour clôturé |
| `since`   | ISO-8601 UTC | depuis quand cet état dure |
| `expires` | ISO-8601 UTC \| `-` | échéance de reprise anti-blocage (TTL 30 min) |
| `note`    | texte court | mémo lisible |

> `expires` ne porte une date **que** pendant `WORKING_*` (un agent travaille,
> TTL 30 min). Il repasse à `-` dès qu'on attend (`AWAITING_*`, `IDLE`, `DONE`) :
> personne ne tient le stylo, donc pas de péremption à surveiller.

**Lecture des états** (`<X>` = un agent actif — par défaut `claude`/`codex`) :
- `AWAITING_<X>` → c'est à `<X>` de jouer (l'autre agent attend).
- `WORKING_<X>` → `<X>` tient le stylo et travaille (l'autre attend, ne touche à rien).
- `IDLE` → personne n'a la main, le premier qui a quelque chose à dire démarre.
- `DONE` → session close, plus de relais attendu.

---

## 3. Format d'un tour

```
<!-- COWORK:TURN <n> <agent> BEGIN -->
- from:    <agent>           # un agent actif
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
  1. lire LOCK (status / wait)
  2. si state == AWAITING_<moi> ou IDLE :
       a. CLAIM  : ./cowork.py claim <moi>   → state=WORKING_<MOI>, expires=now+30min
                   EXCLUSIF : si un autre a déjà pris le stylo entre-temps,
                   claim ÉCHOUE → va en 3.
       b. TRAVAILLER dans le dépôt (tant que tu tiens le stylo, toi seul)
       c. APPEND  : ./cowork.py append <moi> --to <autre>
                   écrit mon tour <turn+1>, state=AWAITING_<AUTRE>
  3. sinon (WORKING_<autre> ou AWAITING_<autre>) :
       attendre ~60 s (wait), retourner en 1
  4. si state == DONE : sortir
```

En pratique : `claim` **acquiert** le stylo (exclusif), `append` **clôt** ton tour
et passe la main, `wait` attend ton tour. L'acquisition explicite avant de
travailler est ce qui garantit qu'un seul agent modifie le dépôt à la fois.

> **Modèle de concurrence (deux niveaux)** :
> 1. **Transitions** sérialisées par un verrou inter-process (`.cowork.lock`,
>    `O_CREAT|O_EXCL`, à jeton de propriété) : chaque read-modify-write du LOCK +
>    écriture atomique (temporaire unique + `os.replace`) est exclusif.
> 2. **Fenêtre de travail** protégée par l'état persistant `WORKING_<agent>` :
>    `claim` est la seule acquisition, et il échoue si quelqu'un d'autre tient ou
>    a déjà pris le stylo. Deux `claim` simultanés depuis `IDLE` ⇒ **un seul
>    réussit** ; l'autre doit attendre. Comme on ne travaille qu'après un `claim`
>    réussi, deux agents ne modifient jamais le dépôt en même temps.
>
> Un `.cowork.lock` abandonné (process tué) est repris après 60 s, jeton vérifié.
> *Limites* : verrou **conseillé** (une édition manuelle de `COWORK.md` le
> contourne) ; sur FS réseau (NFS) `O_EXCL`/`rename` sont moins fiables — cowork
> vise un dépôt sur disque local. Voir aussi §0/§4 (claim obligatoire).

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
./cowork.py init [--name PROJET] [--agents a,b] [--lang en|fr] [--force]  # (re)génère le kit ici
./cowork.py status                                # verrou + dernier tour (NON bloquant)
./cowork.py wait <agent> [--once] [--interval N]  # attend ton tour ; --once = 1 check (rc 3 si pas ton tour)
./cowork.py claim <agent> [--force]               # ACQUIERS le stylo (exclusif) — depuis ton tour /
                                                  #   IDLE / ton propre verrou ; --force = verrou périmé SEULEMENT
./cowork.py append <agent> --to <autre> \
     --ask "..." --done "..." [--files a,b] [--body fichier.md|-]   # clôt ton tour + passe la main
./cowork.py release <agent> --to <autre> [--force]  # repasser la main sans corps (ne ré-incrémente PAS turn)
./cowork.py done <agent> [--force]                 # clore la session (state=DONE)
./cowork.py archive [--keep N]                     # purge les vieux tours clôturés (jamais le tour #0)
```

- **`claim` d'abord** : tu dois tenir le stylo (`WORKING_<toi>`) pour `append`.
  `claim` est **exclusif** (un seul gagnant si deux agents tentent ensemble).
- `append` n'est accepté **que depuis `WORKING_<toi>`** ; il écrit le tour et
  passe la main. `--body -` lit le corps depuis stdin ; `--body f.md` depuis un
  fichier ; sans `--body`, le tour n'a que l'en-tête.
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
- injecte en **tête** un bloc « Co-work relais » dans **l'ancrage de chaque agent
  actif** (par défaut `CLAUDE.md` et `AGENTS.md` ; créés s'ils manquent), entre
  marqueurs `COWORK:STANZA` → ré-injection **idempotente** (déplace/actualise le bloc
  sans dupliquer, contenu existant préservé ; le fichier précédent est sauvegardé dans
  `<ancrage>.cowork.bak`) ;
- si `CLAUDE.md` existait mais qu'aucune instruction Codex (`AGENTS.md` ou
  `AGENTS.override.md`) n'existait, crée automatiquement dans `AGENTS.md` un pont
  demandant à Codex de lire les instructions communes de `CLAUDE.md`. Un ancrage
  Codex préexistant n'est jamais complété ou remplacé automatiquement ;
- renomme une variante unique `claude.md`/`agents.md` vers le nom canonique
  auto-chargé, y compris sur un FS insensible à la casse. Plusieurs variantes
  coexistantes sont refusées plutôt que fusionnées silencieusement. Si Git est
  disponible et que la variante est suivie, emploie `git mv -f` pour actualiser
  aussi l'index ;
- si `AGENTS.override.md` existe, y synchronise aussi la stanza : Codex charge
  cet override à la place de `AGENTS.md` dans le même dossier.

### Amorçage / prise en compte par les agents

cowork est **passif** : il n'« appelle » aucune IA. Il s'appuie sur la convention de
chaque outil hôte — **Claude lit `CLAUDE.md`, Codex lit `AGENTS.md`**, et tout autre
agent actif lit son propre ancrage — au démarrage de session/exécution. La chaîne
d'amorçage est donc :

```
cowork.py init  ──▶  injecte la STANZA dans l'ancrage de chaque agent actif (CLAUDE.md, AGENTS.md, …)
                          │
   chaque IA charge son ancrage au démarrage ──▶ lit la stanza ──▶
   « si un COWORK.md existe, applique COWORK.protocol.md (claim → travail → append) »
```

- **Après `init`** : démarre une nouvelle session/exécution de l'agent. Une session
  déjà ouverte a généralement construit sa chaîne d'instructions avant l'injection.
- **Codex interactif ou `codex exec`** : `AGENTS.md` est chargé si la commande part
  de la racine du projet ou d'un de ses sous-dossiers. Le mode *headless* n'est pas
  en soi une limite ; un cron/CI lancé hors du projet, en revanche, ne découvre pas
  l'ancrage.
- **Override Codex** : `AGENTS.override.md` masque `AGENTS.md` dans un même dossier ;
  `init` injecte donc la stanza dans les deux lorsqu'il est présent.
- **Taille Codex** : Codex empile les fichiers d'instructions jusqu'à un plafond
  *combiné* (`project_doc_max_bytes`, 32 Kio par défaut) et tronque le fichier qui
  dépasse au nombre d'octets restant. Mettre la stanza en tête la conserve donc en
  priorité (et un fichier plus proche du cwd prime) ; garde néanmoins les ancrages
  **légers**.
- **Limite générale** : cowork ne peut pas forcer une IA à lire quoi que ce soit.
  Sans racine/contexte projet, pointe explicitement l'agent vers
  `COWORK.protocol.md`.

Référence Codex : https://developers.openai.com/codex/guides/agents-md
"""

STANZA_FR = """{begin}
## Co-work relais — autonome, aucune aide humaine requise

Tu es **{me}** dans ce projet. Dès qu'un `COWORK.md` est présent à la racine,
c'est ta source de coordination avec **{other}** : applique `COWORK.protocol.md`
(lis-le une fois, voir son §0) AVANT tout autre travail. **Tu ne travailles et
n'écris que si tu as acquis le stylo via `claim`.**

```bash
./cowork.py status                # qui a la main ? (non bloquant)
./cowork.py wait {me} --once      # rc 0 = tu peux acquérir ; rc 3 = pas encore
```

- **Acquiers d'abord** (`state == AWAITING_{ME}` ou `IDLE`) :
  `./cowork.py claim {me}` — **exclusif** : si {other} a déjà pris le stylo, ça
  échoue → reviens à l'attente. Si ça réussit, tu tiens le stylo (`WORKING_{ME}`).
- **Puis travaille et clôts ton tour** : lis le `ask:` que {other} t'a laissé
  (en démarrage IDLE, rien à honorer), fais le travail, puis :
  `./cowork.py append {me} --to {other} --ask "…" --done "…" [--files a,b]`
- **Pas ton tour** : ne touche à rien ; `./cowork.py wait {me}` bloque jusqu'à ton
  tour (poll ~60 s), puis retente `claim`.
- **Verrou de {other} périmé** (`WORKING_{OTHER}` + `now > expires`) :
  `./cowork.py claim {me} --force`.

Un tour clôturé est immuable : pour réagir, ouvre le tour suivant.
{end}"""


# ------------------------------------------------------------------- helpers


PROTOCOL_EN = r"""# COWORK · Single-file relay protocol (v1)

Shared instruction for the **two active agents** (by default **Claude** and
**Codex**) to cooperate through a single
`COWORK.md` file, in strict alternation (mutex), with periodic polling. Portable:
this protocol is identical in every project; only the title of `COWORK.md`
changes.

Read it **once at the start of a session** as soon as you see a `COWORK.md` at
the root of a project. You are **one of the two active agents** declared in the
`agents:` field of `COWORK.md` (by default `claude` and `codex`) — identify yourself
by your anchor file.

---

## 0. TL;DR — operate without human help

You have just arrived in the project and you see a `COWORK.md`: here is the
complete, copy-pasteable loop, **no other instruction is required**. `<you>` is your
own agent name and `<other>` is the other active agent (the pair declared in
`agents:`; by default `claude` / `codex`, via the `CLAUDE.md` / `AGENTS.md` anchors).

```bash
# 1. Am I expected? (NON-blocking commands)
./cowork.py status                 # read the `state` field
./cowork.py wait <you> --once      # rc 0 = you may acquire ; rc 3 = not yet

# 2. ACQUIRE the pen BEFORE working (EXCLUSIVE acquisition: when two agents
#    try at the same time, only one succeeds):
./cowork.py claim <you>           # rc 0 = you hold the pen ; rc != 0 = not your turn
#    • If claim SUCCEEDS: read the `ask:` that <other> left you in the last
#      turn (at IDLE startup / turn 0, nothing to honour), do the work in the
#      repository, THEN record your turn and hand off:
./cowork.py append <you> --to <other> \
    --ask "what you expect from the other" \
    --done "what you just did" \
    --files file1,file2
#    • If claim FAILS: it is not (or no longer) your turn → go back to waiting.

# 3. Not your turn: touch NOTHING. Block until your turn, then resume at 2:
./cowork.py wait <you>             # poll every ~60 s (--interval N)
```

Golden rule: **you work and write only if you have acquired the pen via
`claim`.** `claim` is exclusive; `append` is accepted only if you hold the
pen. Everything else in this document is just the detail of this loop.

---

## 1. Mental model

- **A single living file**: `COWORK.md`. The entire work dialogue is there.
- **A single pen, explicitly acquired**: to work, you **take** the pen via
  `claim` → state `WORKING_<you>`. `claim` is **exclusive** (two agents trying
  at the same time: only one succeeds). You modify the repository **only** while
  you hold the pen.
- **`append` closes your turn**: it is accepted only from `WORKING_<you>`,
  writes the turn and hands off (`AWAITING_<other>`). No `claim` ⇒ no `append`.
- **Strict alternation**: the two active agents take turns (e.g. `claude` → `codex`
  → `claude` …). Each hand-off is a numbered *turn* (`TURN`), framed by `BEGIN`/`END`.
- **Poll**: when it is not your turn, you wait (`./cowork.py wait <you>`,
  ~60 s) then you retry `claim`.

---

## 2. The LOCK block (the mutex)

Delimited by `<!-- COWORK:LOCK:BEGIN -->` … `<!-- COWORK:LOCK:END -->`.
Fields (one `key: value` per line, easy to `grep`):

| field     | values | meaning |
|-----------|---------|------|
| `holder`  | an active agent \| `none` | who holds the pen (default `claude`/`codex`) |
| `state`   | `IDLE` \| `WORKING_<X>` \| `AWAITING_<X>` \| `DONE` | current state (`<X>` = an active agent, uppercased) |
| `agents`  | CSV, e.g. `claude,codex` | the relaying pair (the first two declared); default `claude,codex` |
| `turn`    | integer | number of the last closed turn |
| `since`   | ISO-8601 UTC | since when this state has lasted |
| `expires` | ISO-8601 UTC \| `-` | anti-deadlock takeover deadline (TTL 30 min) |
| `note`    | short text | readable memo |

> `expires` carries a date **only** during `WORKING_*` (an agent is working,
> TTL 30 min). It returns to `-` as soon as we are waiting (`AWAITING_*`, `IDLE`,
> `DONE`): nobody holds the pen, so there is no staleness to watch.

**Reading the states** (`<X>` is an active agent — by default `claude`/`codex`):
- `AWAITING_<X>` → it is `<X>`'s turn to play (the other agent waits).
- `WORKING_<X>` → `<X>` holds the pen and is working (the other waits, touches nothing).
- `IDLE` → nobody has the hand, the first who has something to say starts.
- `DONE` → session closed, no further relay expected.

---

## 3. Format of a turn

```
<!-- COWORK:TURN <n> <agent> BEGIN -->
- from:    <agent>           # an active agent
- to:      <agent|none>      # to whom you hand off
- ask:     <what you expect from the other, precise and actionable>
- done:    <what you just did>
- files:   <files touched, comma-separated>
- handoff: <agent|none>      # = to ; deliberate redundancy, grep-friendly
<blank line>
<free body: explanations, questions, code blocks, lists>
<!-- COWORK:TURN <n> <agent> END -->
```

Rules:
- A **closed** turn (`END` set) is **immutable**. To react, you open the next
  turn. Never retroactive rewriting.
- `ask` must be actionable: the other agent must be able to start without asking
  you again. If you expect nothing (just an FYI), put `ask: —`.
- Keep a turn **bounded**: if it exceeds ~150 lines or several topics, split it
  into several successive turns (one topic = one turn).

---

## 4. Work cycle (each agent's loop)

```
loop:
  1. read LOCK (status / wait)
  2. if state == AWAITING_<me> or IDLE:
       a. CLAIM  : ./cowork.py claim <me>   → state=WORKING_<ME>, expires=now+30min
                   EXCLUSIVE: if someone else has taken the pen in the meantime,
                   claim FAILS → go to 3.
       b. WORK in the repository (while you hold the pen, you alone)
       c. APPEND  : ./cowork.py append <me> --to <other>
                   writes my turn <turn+1>, state=AWAITING_<OTHER>
  3. else (WORKING_<other> or AWAITING_<other>):
       wait ~60 s (wait), go back to 1
  4. if state == DONE: exit
```

In practice: `claim` **acquires** the pen (exclusive), `append` **closes** your
turn and hands off, `wait` waits for your turn. The explicit acquisition before
working is what guarantees that a single agent modifies the repository at a time.

> **Concurrency model (two levels)**:
> 1. **Transitions** serialized by an inter-process lock (`.cowork.lock`,
>    `O_CREAT|O_EXCL`, with an ownership token): each read-modify-write of the
>    LOCK + atomic write (unique temporary + `os.replace`) is exclusive.
> 2. **Work window** protected by the persistent state `WORKING_<agent>`:
>    `claim` is the only acquisition, and it fails if someone else holds or has
>    already taken the pen. Two simultaneous `claim`s from `IDLE` ⇒ **only one
>    succeeds**; the other must wait. Since we work only after a successful
>    `claim`, two agents never modify the repository at the same time.
>
> An abandoned `.cowork.lock` (killed process) is taken over after 60 s, token
> verified. *Limits*: the lock is **advisory** (a manual edit of `COWORK.md`
> bypasses it); on a network FS (NFS) `O_EXCL`/`rename` are less reliable —
> cowork targets a repository on local disk. See also §0/§4 (mandatory claim).

---

## 5. Anti-deadlock (stale lock)

If the other agent crashes while holding the pen, the lock would stay stuck.
Guardrail:
- on CLAIM, we set `expires = now + 30 min`;
- if you see `state == WORKING_<other>` **and** `now > expires`, the lock is
  **stale**: take it over with `./cowork.py claim <you> --force`, then open a
  turn noting the takeover (`done: takeover after stale lock from <other>`);
- **the tool enforces the rule**: `--force` is **refused** on a still-valid
  lock. You therefore cannot steal the pen from an active agent (this is
  intentional);
- you can **refresh your own** lock before it expires: `./cowork.py claim
  <you>` when you already hold it resets `expires` to +30 min;
- `release` and `done` act only if **you** hold the pen (or if nobody holds it);
  `--force` overrides, reserved for recovery.

---

## 6. Keeping it bounded over time (bounded length)

`COWORK.md` must not grow indefinitely:
- keep in `COWORK.md` the `LOCK` block + the **~6 last turns**;
- `./cowork.py archive --keep 6` moves the older turns (already closed) to
  `COWORK.archive.md` (append), without ever touching the lock or the last open
  turn.
- The archive can be consulted but is **never** re-read by the loop: only the
  living part of `COWORK.md` drives the relay.

---

## 7. The `cowork.py` tool

```
./cowork.py init [--name PROJECT] [--agents a,b] [--lang en|fr] [--force]  # (re)generates the kit here
./cowork.py status                                # lock + last turn (NON-blocking)
./cowork.py wait <agent> [--once] [--interval N]  # waits for your turn ; --once = 1 check (rc 3 if not your turn)
./cowork.py claim <agent> [--force]               # ACQUIRE the pen (exclusive) — from your turn /
                                                  #   IDLE / your own lock ; --force = stale lock ONLY
./cowork.py append <agent> --to <other> \
     --ask "..." --done "..." [--files a,b] [--body file.md|-]   # closes your turn + hands off
./cowork.py release <agent> --to <other> [--force]  # hand off without a body (does NOT re-increment turn)
./cowork.py done <agent> [--force]                 # close the session (state=DONE)
./cowork.py archive [--keep N]                     # purge old closed turns (never turn #0)
```

- **`claim` first**: you must hold the pen (`WORKING_<you>`) to `append`.
  `claim` is **exclusive** (a single winner if two agents try together).
- `append` is accepted **only from `WORKING_<you>`**; it writes the turn and
  hands off. `--body -` reads the body from stdin; `--body f.md` from a file;
  without `--body`, the turn has only the header.
- `--to` must target **the other** agent (self-hand-off refused: strict alternation).
- **Non-blocking** inspection: `status` or `wait <you> --once`. `wait <you>`
  **without** `--once` blocks until your turn — do not use it if you must return
  control to your loop in the meantime.

---

## 8. Adoption by any project (portability)

`cowork.py` is **self-sufficient**: it embeds this protocol, the `COWORK.md`
template and the anchors. To adopt the relay in a project:

```bash
cp /path/to/cowork.py .          # copy the only file needed
./cowork.py init                 # project name = folder name (otherwise --name)
```

`init`:
- writes `COWORK.protocol.md` (this document) and `COWORK.md` (a fresh IDLE
  lock); `COWORK.md` is **not** overwritten if it already exists (except with
  `--force`) → the state of the ongoing relay is preserved;
- injects at the **top** a "Co-work relay" block into **each active agent's anchor**
  (by default `CLAUDE.md` and `AGENTS.md`; created if missing), between
  `COWORK:STANZA` markers → **idempotent** re-injection (moves/updates the block
  without duplicating, existing content preserved; the prior file is backed up to
  `<anchor>.cowork.bak`);
- if `CLAUDE.md` existed but no Codex instruction (`AGENTS.md` or
  `AGENTS.override.md`) existed, automatically creates in `AGENTS.md` a bridge
  asking Codex to read the shared instructions in `CLAUDE.md`. A pre-existing
  Codex anchor is never completed or replaced automatically;
- renames a single `claude.md`/`agents.md` variant to the canonical
  auto-loaded name, including on a case-insensitive FS. Several coexisting
  variants are refused rather than silently merged. If Git is available and the
  variant is tracked, it uses `git mv -f` to also update the index;
- if `AGENTS.override.md` exists, it also synchronizes the stanza there: Codex
  loads this override instead of `AGENTS.md` in the same folder.

### Bootstrap / uptake by the agents

cowork is **passive**: it never "calls" any AI. It relies on the convention of each
host tool — **Claude reads `CLAUDE.md`, Codex reads `AGENTS.md`**, and any other active
agent reads its own anchor — at session/execution startup. The bootstrap chain is
therefore:

```
cowork.py init  ──▶  injects the STANZA into each active agent's anchor (CLAUDE.md, AGENTS.md, …)
                          │
   each AI loads its anchor at startup ──▶ reads the stanza ──▶
   "if a COWORK.md exists, apply COWORK.protocol.md (claim → work → append)"
```

- **After `init`**: start a new session/execution of the agent. A session
  already open has generally built its instruction chain before the injection.
- **Interactive Codex or `codex exec`**: `AGENTS.md` is loaded if the command
  starts from the project root or one of its subfolders. *Headless* mode is not
  in itself a limit; a cron/CI launched outside the project, however, does not
  discover the anchor.
- **Codex override**: `AGENTS.override.md` masks `AGENTS.md` in the same folder;
  `init` therefore injects the stanza into both when it is present.
- **Codex size**: Codex stacks the instruction files up to a *combined* ceiling
  (`project_doc_max_bytes`, 32 KiB by default) and truncates the file that
  overflows to the remaining byte count. Putting the stanza at the top thus
  keeps it in priority (and a file closer to the cwd takes precedence);
  nevertheless keep the anchors **lightweight**.
- **General limit**: cowork cannot force an AI to read anything. Without a
  project root/context, point the agent explicitly to `COWORK.protocol.md`.

Codex reference: https://developers.openai.com/codex/guides/agents-md
"""

STANZA_EN = """{begin}
## Co-work relay — autonomous, no human help required

You are **{me}** in this project. As soon as a `COWORK.md` is present at the root,
it is your source of coordination with **{other}**: apply `COWORK.protocol.md`
(read it once, see its §0) BEFORE any other work. **You only work and write if
you have acquired the pen via `claim`.**

```bash
./cowork.py status                # who holds the pen? (non-blocking)
./cowork.py wait {me} --once      # rc 0 = you may acquire ; rc 3 = not yet
```

- **Acquire first** (`state == AWAITING_{ME}` or `IDLE`):
  `./cowork.py claim {me}` — **exclusive**: if {other} has already taken the pen, it
  fails → go back to waiting. If it succeeds, you hold the pen (`WORKING_{ME}`).
- **Then work and close your turn**: read the `ask:` that {other} left you
  (at IDLE startup, nothing to honor), do the work, then:
  `./cowork.py append {me} --to {other} --ask "…" --done "…" [--files a,b]`
- **Not your turn**: touch nothing; `./cowork.py wait {me}` blocks until your
  turn (poll ~60 s), then retry `claim`.
- **{other}'s lock is stale** (`WORKING_{OTHER}` + `now > expires`):
  `./cowork.py claim {me} --force`.

A closed turn is immutable: to react, open the next turn.
{end}"""

COWORK_EN = r"""<!-- ╔════════════════════════════════════════════════════════════╗
     ║  COWORK · single-file multi-agent relay · protocol v1      ║
     ║  Read COWORK.protocol.md BEFORE writing here.              ║
     ╚════════════════════════════════════════════════════════════╝ -->

# COWORK · __PROJECT__

> Shared work file. **Only one agent writes at a time.** The lock is the
> `LOCK` block below. Only write if `state == AWAITING_<you>`. Details →
> [COWORK.protocol.md](COWORK.protocol.md). Tool → `./cowork.py status`.

<!-- COWORK:LOCK:BEGIN -->
holder:   none
state:    IDLE
agents:   __AGENTS__
lang:     __LANG__
turn:     0
since:    __NOW__
expires:  -
note:     session initialized, no turn opened
<!-- COWORK:LOCK:END -->

---

## Turn log

<!-- Turns stack below, from oldest to most recent.                          -->
<!-- Turn format: see COWORK.protocol.md §3. Never edit a turn that is        -->
<!-- already closed (END set): add a new turn instead.                        -->

<!-- COWORK:TURN 0 system BEGIN -->
- from:    system
- to:      none
- ask:     —
- done:    Relay initialization. The first agent that starts runs
           `./cowork.py claim __A__` (or `__B__`), works, then
           `./cowork.py append __A__ --to __B__ --ask "..." --done "..."`.
- files:   COWORK.md, COWORK.protocol.md, cowork.py
- handoff: none
<!-- COWORK:TURN 0 system END -->
"""

BRIDGE_EN = """## Shared project instructions

Read and fully apply `CLAUDE.md`, which contains the shared project instructions
for Claude and Codex.
"""

PROTOCOL = {"en": PROTOCOL_EN, "fr": PROTOCOL_FR}
STANZA = {"en": STANZA_EN, "fr": STANZA_FR}
COWORK_TPL = {"en": COWORK_EN, "fr": COWORK_FR}
BRIDGE = {"en": BRIDGE_EN, "fr": BRIDGE_FR}


# ----------------------------------------------------------------- i18n (en/fr)
# Resolved language: --lang (init) > $COWORK_LANG > LOCK `lang` field > en.

def resolve_lang(explicit=None, lk=None):
    if explicit in LANGS:
        return explicit
    env = os.environ.get("COWORK_LANG", "")
    if env in LANGS:
        return env
    if lk and lk.get("lang") in LANGS:
        return lk["lang"]
    return DEFAULT_LANG


LANG = resolve_lang()  # baseline (refined by load_or_die / cmd_init)

MESSAGES = {
    "en": {
        "lock_busy": "internal lock busy (another cowork.py is writing) — retry.",
        "cowork_missing": "COWORK.md not found — run `./cowork.py init` first.",
        "lock_missing": "COWORK.md corrupted: LOCK block not found — `./cowork.py init --force` to reset the lock.",
        "lock_invalid": "COWORK.md corrupted (invalid LOCK: {errs}) — `./cowork.py init --force` to repair.",
        "field_newline": "refused: {label} must not contain a line break.",
        "field_reserved": "refused: {label} contains a reserved marker ({marker}).",
        "bad_agent": "invalid agent: {a} (expected: {agents})",
        "bad_roster": "invalid --agents: {raw} — provide at least two distinct agent names (e.g. claude,codex).",
        "anchor_no_map": "{agent}: no known anchor file — bootstrap manually (point {agent} to COWORK.protocol.md).",
        "anchor_collision": "{agent}: anchor {filename} is already used by another active agent — skipped (bootstrap {agent} manually).",
        "roster_extra": "{n} agents declared; only the first two relay in this version ({pair}). Extra names are reserved for the future N-agent mode.",
        "roster_conflict": "refused: --agents {requested} differs from the roster {existing} already in COWORK.md — re-run with --force to reset it, or omit --agents to keep the current roster.",
        "anchor_ambiguous": "ambiguous anchors for {canonical}: {others} — consolidate them before `cowork.py init`.",
        "anchor_git_fail": "could not rename {actual} via Git to {canonical}: {detail}",
        "git_unknown_err": "unknown git error",
        "migrated_git": "{actual} → {canonical}: renamed via Git for auto-loading",
        "migrated_fs": "{actual} → {canonical}: renamed for auto-loading",
        "stanza_incomplete": "{filename}: incomplete COWORK stanza — fix the markers before init.",
        "stanza_updated": "stanza refreshed at top",
        "stanza_added": "stanza added at top",
        "file_created": "file created",
        "anchor_result": "{filename}: {action}",
        "proto_written": "COWORK.protocol.md: written",
        "proto_uptodate": "COWORK.protocol.md: already up to date",
        "cowork_preserved": "COWORK.md: preserved (already exists; --force to reset)",
        "cowork_written": "COWORK.md: written (project “{name}”, lock IDLE)",
        "bridge_added": "AGENTS.md: automatic bridge to the shared instructions in CLAUDE.md",
        "override_synced": "{filename}: Codex override active, stanza synced",
        "init_header": "✓ cowork init — project “{name}” in {here}",
        "init_start": "Start: ./cowork.py claim {a}  (then work, then ./cowork.py append {a} --to {b} --ask \"…\" --done \"…\")",
        "init_bootstrap": "Bootstrap: start a new session/run of each agent to reload its anchor.",
        "status_stale": "  ⚠ stale lock — reclaim with: claim <you> --force",
        "last_turn": "── last turn: #{n} by {who}",
        "wait_your_turn": "✓ your turn ({st}) — `./cowork.py claim {agent}` to acquire the pen.",
        "wait_free": "✓ free ({st}) — `./cowork.py claim {agent}` to acquire the pen.",
        "wait_done": "session DONE — nothing to wait for.",
        "wait_stale": "⚠ {other}'s lock is stale — claim --force possible.",
        "wait_not_yet": "… not your turn: {st} (holder={holder}).",
        "wait_poll": "… {st} (holder={holder}), re-checking in {interval}s",
        "bad_interval": "--interval must be an integer >= 1.",
        "claim_active": "refused: {holder}'s lock is still valid (expires {expires}). --force only reclaims a stale lock (protocol §5).",
        "claim_refused": "refused: state={st}, holder={holder} — it is not your turn.",
        "note_reclaim": "reclaimed after {holder}'s stale lock",
        "note_holds": "{agent} holds the pen",
        "claim_ok": "✓ pen taken by {agent} (expires {expires}{suffix}).",
        "claim_reclaim_suffix": " — stale lock reclaimed",
        "body_error": "--body: {e}",
        "to_self_append": "refused: --to must target the other agent (strict alternation, protocol §1).",
        "append_need_claim": "refused: you do not hold the pen (state={st}) — run `./cowork.py claim {agent}` first (exclusive acquisition), then append.",
        "note_turn": "turn {n} posted by {agent}, awaiting {to}",
        "append_ok": "✓ turn {n} written by {agent}, handed off to {to}.",
        "to_self": "refused: --to must target the other agent.",
        "not_holder_release": "refused: {holder} holds the pen, not you (--force to override).",
        "note_release": "handed off to {to} by {agent} (no turn)",
        "release_ok": "✓ handed off to {to}.",
        "not_holder_done": "refused: {holder} holds the pen, not you (--force to close anyway).",
        "note_done": "session closed by {agent}",
        "done_ok": "✓ session DONE.",
        "archive_none": "nothing to archive ({n} archivable turn(s), keep={keep}).",
        "archive_header": "# COWORK · turn archive\n\n",
        "archive_ok": "✓ {n} turn(s) archived → {file} (kept: {keep}).",
    },
    "fr": {
        "lock_busy": "verrou interne occupé (un autre cowork.py écrit) — réessaie.",
        "cowork_missing": "COWORK.md introuvable — lance d'abord `./cowork.py init`.",
        "lock_missing": "COWORK.md corrompu : bloc LOCK introuvable — `./cowork.py init --force` pour réinitialiser le verrou.",
        "lock_invalid": "COWORK.md corrompu (LOCK invalide : {errs}) — `./cowork.py init --force` pour réparer.",
        "field_newline": "refus: {label} ne doit pas contenir de saut de ligne.",
        "field_reserved": "refus: {label} contient un marqueur réservé ({marker}).",
        "bad_agent": "agent invalide: {a} (attendu: {agents})",
        "bad_roster": "--agents invalide : {raw} — fournis au moins deux noms d'agents distincts (ex. claude,codex).",
        "anchor_no_map": "{agent} : aucun fichier d'ancrage connu — amorce manuellement (pointe {agent} vers COWORK.protocol.md).",
        "anchor_collision": "{agent} : l'ancrage {filename} est déjà utilisé par un autre agent actif — ignoré (amorce {agent} manuellement).",
        "roster_extra": "{n} agents déclarés ; seuls les deux premiers font le relais dans cette version ({pair}). Les noms supplémentaires sont réservés au futur mode N agents.",
        "roster_conflict": "refus : --agents {requested} diffère du roster {existing} déjà présent dans COWORK.md — relance avec --force pour le réinitialiser, ou omets --agents pour conserver le roster courant.",
        "anchor_ambiguous": "ancrages ambigus pour {canonical}: {others} — consolide-les avant `cowork.py init`.",
        "anchor_git_fail": "impossible de renommer {actual} via Git vers {canonical}: {detail}",
        "git_unknown_err": "erreur git inconnue",
        "migrated_git": "{actual} → {canonical}: renommé via Git pour auto-chargement",
        "migrated_fs": "{actual} → {canonical}: renommé pour auto-chargement",
        "stanza_incomplete": "{filename}: stanza COWORK incomplète — répare les marqueurs avant init.",
        "stanza_updated": "stanza actualisée en tête",
        "stanza_added": "stanza ajoutée en tête",
        "file_created": "fichier créé",
        "anchor_result": "{filename}: {action}",
        "proto_written": "COWORK.protocol.md: écrit",
        "proto_uptodate": "COWORK.protocol.md: déjà à jour",
        "cowork_preserved": "COWORK.md: préservé (existe déjà ; --force pour réinitialiser)",
        "cowork_written": "COWORK.md: écrit (projet « {name} », verrou IDLE)",
        "bridge_added": "AGENTS.md: pont automatique vers les instructions communes de CLAUDE.md",
        "override_synced": "{filename}: override Codex actif, stanza synchronisée",
        "init_header": "✓ cowork init — projet « {name} » dans {here}",
        "init_start": "Démarrer : ./cowork.py claim {a}  (puis travaille, puis ./cowork.py append {a} --to {b} --ask \"…\" --done \"…\")",
        "init_bootstrap": "Amorçage : démarre une nouvelle session/exécution de chaque agent pour recharger son ancrage.",
        "status_stale": "  ⚠ verrou PERIME — reprenable avec: claim <toi> --force",
        "last_turn": "── dernier tour: #{n} par {who}",
        "wait_your_turn": "✓ à toi ({st}) — `./cowork.py claim {agent}` pour acquérir le stylo.",
        "wait_free": "✓ libre ({st}) — `./cowork.py claim {agent}` pour acquérir le stylo.",
        "wait_done": "session DONE — rien a attendre.",
        "wait_stale": "⚠ verrou de {other} PERIME — claim --force possible.",
        "wait_not_yet": "… pas ton tour: {st} (holder={holder}).",
        "wait_poll": "… {st} (holder={holder}), nouvelle verif dans {interval}s",
        "bad_interval": "--interval doit être un entier >= 1.",
        "claim_active": "refus: verrou de {holder} encore valide (expire {expires}). --force ne reprend qu'un verrou périmé (protocole §5).",
        "claim_refused": "refus: state={st}, holder={holder} — ce n'est pas ton tour.",
        "note_reclaim": "reprise après lock périmé de {holder}",
        "note_holds": "{agent} tient le stylo",
        "claim_ok": "✓ verrou pris par {agent} (expire {expires}{suffix}).",
        "claim_reclaim_suffix": " — reprise lock périmé",
        "body_error": "--body: {e}",
        "to_self_append": "refus: --to doit viser l'autre agent (alternance stricte, protocole §1).",
        "append_need_claim": "refus: tu ne tiens pas le stylo (state={st}) — fais d'abord `./cowork.py claim {agent}` (acquisition exclusive), puis append.",
        "note_turn": "tour {n} pose par {agent}, en attente de {to}",
        "append_ok": "✓ tour {n} ecrit par {agent}, main passee a {to}.",
        "to_self": "refus: --to doit viser l'autre agent.",
        "not_holder_release": "refus: {holder} tient le stylo, pas toi (--force pour outrepasser).",
        "note_release": "main passee a {to} par {agent} (sans tour)",
        "release_ok": "✓ main passee a {to}.",
        "not_holder_done": "refus: {holder} tient le stylo, pas toi (--force pour clore quand même).",
        "note_done": "session close par {agent}",
        "done_ok": "✓ session DONE.",
        "archive_none": "rien a archiver ({n} tour(s) archivable(s), keep={keep}).",
        "archive_header": "# COWORK · archive des tours\n\n",
        "archive_ok": "✓ {n} tour(s) archive(s) → {file} (gardes: {keep}).",
    },
}


def tr(key, **kw):
    cat = MESSAGES.get(LANG, MESSAGES[DEFAULT_LANG])
    s = cat.get(key) or MESSAGES[DEFAULT_LANG].get(key, key)
    return s.format(**kw) if kw else s

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


def _current_umask():
    m = os.umask(0)
    os.umask(m)
    return m


def write(text, path=COWORK):
    """Atomic write: UNIQUE temporary file + os.replace, preserving the mode of the
    existing target file (mkstemp forces 0600 otherwise)."""
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)  # nested anchors (e.g. .github/…) need their parent
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".cowork-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        try:
            os.chmod(tmp, os.stat(path).st_mode)  # keep the existing mode
        except OSError:
            os.chmod(tmp, 0o666 & ~_current_umask())  # new file: usual mode
        os.replace(tmp, path)  # atomic replacement
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


@contextlib.contextmanager
def file_lock(timeout=LOCK_TIMEOUT):
    """Inter-process lock via exclusive file creation (O_CREAT|O_EXCL).

    Serializes the LOCK read-modify-write: two concurrent `cowork.py` runs cannot
    mutate `COWORK.md` at the same time. The lock carries an **ownership token**: we
    only remove it (at the end of the section, or when taking over a lock abandoned
    for LOCK_STALE_S) after verifying the token, so we never erase a successor's
    lock.
    """
    token = f"{os.getpid()}:{time.time_ns()}".encode()
    start = time.monotonic()
    while True:
        try:
            fd = os.open(LOCKFILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            try:
                os.write(fd, token)
            finally:
                os.close(fd)
            break
        except FileExistsError:
            try:
                victim_age = time.time() - os.path.getmtime(LOCKFILE)
                if victim_age > LOCK_STALE_S:
                    with open(LOCKFILE, "rb") as f:
                        victim = f.read()
                    # still stale AND unchanged since the read → safe takeover
                    if time.time() - os.path.getmtime(LOCKFILE) > LOCK_STALE_S:
                        with open(LOCKFILE, "rb") as f2:
                            if f2.read() == victim:
                                os.unlink(LOCKFILE)
                                continue
            except OSError:
                pass
            if time.monotonic() - start > timeout:
                sys.exit(tr("lock_busy"))
            time.sleep(0.05)
    try:
        yield
    finally:
        # remove ONLY our own lock (token verified)
        try:
            with open(LOCKFILE, "rb") as f:
                mine = f.read() == token
            if mine:
                os.unlink(LOCKFILE)
        except OSError:
            pass


def require_cowork():
    if not os.path.exists(COWORK):
        sys.exit(tr("cowork_missing"))


def load_or_die():
    """Read COWORK.md while validating the LOCK block (presence AND schema); clean
    exit otherwise — no invalid value must reach the logic (no traceback)."""
    require_cowork()
    text = read()
    if LOCK_BEGIN not in text or LOCK_END not in text:
        sys.exit(tr("lock_missing"))
    lk = get_lock(text)
    globals()["LANG"] = resolve_lang(lk=lk)  # localize the validation errors below
    pair = active_pair(lk)
    errs = []
    if "agents" in lk:
        ag_valid, ag_invalid = roster_tokens(lk["agents"])
        if ag_invalid or len(ag_valid) < 2:  # reject a partially-invalid stored roster
            errs.append(f"agents={lk.get('agents')!r}")
    if lk.get("state") not in valid_states(pair):
        errs.append(f"state={lk.get('state')!r}")
    if not re.fullmatch(r"\d+", lk.get("turn", "")):
        errs.append(f"turn={lk.get('turn')!r}")
    if lk.get("holder") not in set(pair) | {"none"}:
        errs.append(f"holder={lk.get('holder')!r}")
    if lk.get("lang") not in (None, *LANGS):
        errs.append(f"lang={lk.get('lang')!r}")
    if errs:
        sys.exit(tr("lock_invalid", errs=", ".join(errs)))
    globals()["ROSTER"] = pair
    return text


def clean_field(label, val):
    """Single-line field: rejects line breaks and reserved markers (injection-safe)."""
    val = (val or "").strip()
    if "\n" in val or "\r" in val:
        sys.exit(tr("field_newline", label=label))
    for r in RESERVED:
        if r in val:
            sys.exit(tr("field_reserved", label=label, marker=r))
    return val


def clean_body(text):
    """Multi-line body: neutralizes any injected reserved marker (zero-width after
    `COWORK`) so it cannot masquerade as a real turn."""
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


def roster_tokens(raw):
    """Split a roster CSV into (valid, invalid). Valid = normalized AGENT_RE names
    (lowercased, de-duplicated, order kept); invalid = non-empty tokens that are not
    a well-formed agent name. Empty tokens (trailing comma) are ignored, not invalid."""
    valid, invalid = [], []
    for tok in (raw or "").split(","):
        s = tok.strip()
        if not s:
            continue
        n = s.lower()
        if re.fullmatch(AGENT_RE, n):
            if n not in valid:
                valid.append(n)
        else:
            invalid.append(s)
    return valid, invalid


def parse_roster_csv(raw):
    """Valid agents from a CSV (lenient: empty/invalid tokens are ignored)."""
    return roster_tokens(raw)[0]


def roster_full(lk):
    """Full declared roster (>=2 names); falls back to the default pair if absent/invalid."""
    names = parse_roster_csv(lk.get("agents", ""))
    return names if len(names) >= 2 else list(AGENTS)


def active_pair(lk):
    """ACTIVE pair for this version = the first 2 of the declared roster.
    (Names beyond the 2nd are kept but inactive until the N-agent mode.)"""
    return tuple(roster_full(lk)[:2])


def valid_states(pair):
    s = {"IDLE", "DONE"}
    for a in pair:
        s.add(f"WORKING_{a.upper()}")
        s.add(f"AWAITING_{a.upper()}")
    return s


def other(agent):
    for a in ROSTER:
        if a != agent:
            return a
    return agent


def need_agent(a):
    if a not in ROSTER:
        sys.exit(tr("bad_agent", a=repr(a), agents=" | ".join(ROSTER)))
    return a


# ---------------------------------------------------------------- init / anchors

def ensure_canonical_anchor(canonical, create=True):
    """Return an auto-loadable anchor, along with its migration action if any.

    A single variant (`agents.md`) is renamed to the canonical name (`AGENTS.md`).
    On a case-insensitive FS, a two-step rename also forces the case of the on-disk
    entry. Several coexisting variants are ambiguous: we refuse rather than merge or
    silently overwrite user content.
    """
    try:
        on_disk = os.listdir(HERE)
    except OSError:
        on_disk = []

    variants = [f for f in on_disk if f.casefold() == canonical.casefold()]
    if canonical in variants:
        if len(variants) > 1:
            others = ", ".join(repr(v) for v in variants if v != canonical)
            sys.exit(tr("anchor_ambiguous", canonical=repr(canonical), others=others))
        return canonical, ""
    if not variants:
        return (canonical, "") if create else (None, "")
    if len(variants) > 1:
        names = ", ".join(repr(v) for v in variants)
        sys.exit(tr("anchor_ambiguous", canonical=repr(canonical), others=names))

    actual = variants[0]
    actual_path = os.path.join(HERE, actual)
    canonical_path = os.path.join(HERE, canonical)

    # If the variant is tracked by Git, a plain rename on a case-insensitive FS does
    # not update the index (`git add -A` would then keep agents.md). `git mv -f`
    # makes the case change durable in future clones.
    try:
        tracked = subprocess.run(
            ["git", "-C", HERE, "ls-files", "--error-unmatch", "--", actual],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        ).returncode == 0
    except OSError:
        tracked = False
    if tracked:
        moved = subprocess.run(
            ["git", "-C", HERE, "mv", "-f", "--", actual, canonical],
            capture_output=True,
            text=True,
            check=False,
        )
        if moved.returncode != 0:
            detail = (moved.stderr or moved.stdout).strip()
            sys.exit(tr("anchor_git_fail", actual=repr(actual), canonical=repr(canonical),
                        detail=detail or tr("git_unknown_err")))
        return canonical, tr("migrated_git", actual=actual, canonical=canonical)

    try:
        same_file = os.path.exists(canonical_path) and os.path.samefile(actual_path, canonical_path)
    except OSError:
        same_file = False
    if same_file:
        # A rename that only changes case is unreliable across OSes/filesystems.
        # Freeing the name first via an intermediate forces the canonical entry.
        intermediate = os.path.join(
            HERE, f".cowork-anchor-{os.getpid()}-{time.time_ns()}.tmp"
        )
        os.replace(actual_path, intermediate)
        try:
            os.replace(intermediate, canonical_path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.replace(intermediate, actual_path)
            raise
    else:
        os.replace(actual_path, canonical_path)
    return canonical, tr("migrated_fs", actual=actual, canonical=canonical)


def stanza_for(me):
    o = other(me)
    return STANZA[LANG].format(
        begin=STANZA_BEGIN, end=STANZA_END,
        me=me, ME=me.upper(), other=o, OTHER=o.upper(),
    )


def anchor_exists(canonical):
    """Whether a case variant of an anchor already exists on disk."""
    try:
        return any(
            filename.casefold() == canonical.casefold()
            for filename in os.listdir(HERE)
        )
    except OSError:
        return False


def inject_anchor(filename, me, initial_content=""):
    path = os.path.join(HERE, filename)
    block = stanza_for(me)
    if os.path.exists(path):
        cur = read(path)
        has_begin = STANZA_BEGIN in cur
        has_end = STANZA_END in cur
        if has_begin != has_end:
            sys.exit(tr("stanza_incomplete", filename=filename))
        if has_begin:
            # Remove any old stanza, even one placed at the end of the file. The
            # current version is reinserted at the top to stay prioritized if the
            # host tool truncates a large instruction file.
            pat = re.compile(
                re.escape(STANZA_BEGIN) + r".*?" + re.escape(STANZA_END),
                re.DOTALL,
            )
            remainder = pat.sub("", cur).lstrip("\n")
            action = tr("stanza_updated")
        else:
            remainder = cur
            action = tr("stanza_added")
        new = block + "\n"
        if remainder:
            new += "\n" + remainder
        if new != cur:  # back up the pre-init content before modifying an existing anchor
            write(cur, path + ".cowork.bak")
    else:
        # Deliberate choice (tested): the stanza is the FIRST thing in the file, even
        # a new one, to stay prioritized/untruncated — no H1 title above it.
        new = block + "\n"
        if initial_content:
            new += "\n" + initial_content.rstrip() + "\n"
        action = tr("file_created")
    write(new, path)
    return tr("anchor_result", filename=filename, action=action)


def cmd_init(args):
    globals()["LANG"] = resolve_lang(explicit=getattr(args, "lang", "") or None)
    name = args.name or os.path.basename(HERE) or "project"
    results = []

    # --- roster (RFC stage 1): validate the requested CSV up front (CLI level).
    # An explicit but malformed token is rejected, never silently dropped.
    req_valid, req_invalid = roster_tokens(getattr(args, "agents", "") or "")
    if getattr(args, "agents", "") and (req_invalid or len(req_valid) < 2):
        sys.exit(tr("bad_roster", raw=repr(args.agents)))

    with file_lock():
        # Determine the ACTIVE pair UNDER the lock, so two concurrent inits cannot
        # compute different rosters before serializing. Pair = the first 2 declared
        # names; extras are stored but inactive until the N-agent mode.
        cowork_exists = os.path.exists(COWORK)
        existing = None
        if cowork_exists:
            try:
                existing_lk = get_lock(read(COWORK))
            except (OSError, ValueError):
                existing_lk = None
            if existing_lk is not None:
                # A preserved COWORK.md (no --force) must carry a VALID roster — don't
                # silently keep a corrupt one; point to --force to repair / re-seed.
                if not args.force and "agents" in existing_lk:
                    ev, einv = roster_tokens(existing_lk["agents"])
                    if einv or len(ev) < 2:
                        sys.exit(tr("lock_invalid", errs=f"agents={existing_lk['agents']!r}"))
                existing = roster_full(existing_lk)
        if req_valid and cowork_exists and not args.force:
            # COWORK.md is preserved (no --force): --agents must match the in-place
            # roster, else demand --force rather than silently ignoring it.
            if existing is not None and req_valid != existing:
                sys.exit(tr("roster_conflict", requested=",".join(req_valid),
                            existing=",".join(existing)))
            full = existing or req_valid
        elif req_valid and ((not cowork_exists) or args.force):
            full = req_valid
        elif cowork_exists and existing is not None:
            full = existing
        else:
            full = list(AGENTS)
        pair = tuple(full[:2])
        extra = full[2:]
        globals()["ROSTER"] = pair

        # Capture the state BEFORE creating the anchors. The CLAUDE → Codex bridge
        # must only be offered when a project genuinely had Claude instructions but
        # no Codex instructions.
        had_claude_anchor = anchor_exists(CLAUDE_ANCHOR)
        had_codex_anchor = (
            anchor_exists(CODEX_ANCHOR) or anchor_exists(CODEX_OVERRIDE)
        )

        # protocol: canonical source, (re)written only if missing or different
        if not os.path.exists(PROTO) or read(PROTO) != PROTOCOL[LANG]:
            write(PROTOCOL[LANG], PROTO)
            results.append(tr("proto_written"))
        else:
            results.append(tr("proto_uptodate"))

        # cowork.md: preserved if it exists (state of the ongoing relay), unless --force
        if os.path.exists(COWORK) and not args.force:
            results.append(tr("cowork_preserved"))
        else:
            text = (COWORK_TPL[LANG].replace("__PROJECT__", name)
                    .replace("__NOW__", iso(now())).replace("__LANG__", LANG)
                    .replace("__AGENTS__", ",".join(full))
                    .replace("__A__", pair[0]).replace("__B__", pair[1]))
            write(text, COWORK)
            results.append(tr("cowork_written", name=name))

        # Anchors: the stanza is injected for EACH agent of the active pair.
        # claude / codex keep their dedicated handling (CLAUDE → Codex bridge,
        # AGENTS.override.md sync). Any other roster agent gets a best-effort anchor
        # via the ANCHORS table (warning if it is unmapped or if its anchor file is
        # already taken by another active agent).
        injected = set()
        for ag in pair:
            if ag == "claude":
                claude_anchor, migration = ensure_canonical_anchor(CLAUDE_ANCHOR)
                if claude_anchor in injected:
                    results.append(tr("anchor_collision", agent=ag, filename=claude_anchor))
                    continue
                if migration:
                    results.append(migration)
                results.append(inject_anchor(claude_anchor, "claude"))
                injected.add(claude_anchor)
            elif ag == "codex":
                codex_anchor, migration = ensure_canonical_anchor(CODEX_ANCHOR)
                if codex_anchor in injected:
                    results.append(tr("anchor_collision", agent=ag, filename=codex_anchor))
                    continue
                if migration:
                    results.append(migration)
                # AGENTS.override.md masks AGENTS.md in Codex: if it exists, we inject
                # into both so the stanza survives its later removal.
                codex_initial_content = (
                    BRIDGE[LANG]
                    if had_claude_anchor and not had_codex_anchor and "claude" in pair
                    else ""
                )
                results.append(inject_anchor(
                    codex_anchor, "codex", initial_content=codex_initial_content
                ))
                injected.add(codex_anchor)
                if codex_initial_content:
                    results.append(tr("bridge_added"))

                codex_override, migration = ensure_canonical_anchor(CODEX_OVERRIDE, create=False)
                if migration:
                    results.append(migration)
                if codex_override:
                    results.append(inject_anchor(codex_override, "codex"))
                    results.append(tr("override_synced", filename=codex_override))
            else:
                anchor = ANCHORS.get(ag)
                if not anchor:
                    results.append(tr("anchor_no_map", agent=ag))
                    continue
                resolved, migration = ensure_canonical_anchor(anchor)
                if resolved in injected:
                    results.append(tr("anchor_collision", agent=ag, filename=resolved))
                    continue
                if migration:
                    results.append(migration)
                results.append(inject_anchor(resolved, ag))
                injected.add(resolved)

        if extra:
            results.append(tr("roster_extra", n=len(full), pair=",".join(pair)))

    print(tr("init_header", name=name, here=HERE))
    for r in results:
        print(f"  • {r}")
    print(tr("init_start", a=pair[0], b=pair[1]))
    print(tr("init_bootstrap"))
    return 0


# ---------------------------------------------------------------- relay commands

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
    for k in ("holder", "state", "lang", "turn", "since", "expires", "note"):
        print(f"  {k:<8} {lk.get(k, '')}")
        if k == "state":
            print(f"  {'agents':<8} {','.join(active_pair(lk))}")
    if stale:
        print(tr("status_stale"))
    turns = re.findall(r"COWORK:TURN (\d+) ([a-z][a-z0-9_-]*) BEGIN", text)
    if turns:
        n, who = turns[-1]
        print(tr("last_turn", n=n, who=who))
    return 0


def cmd_wait(args):
    if not args.once and args.interval < 1:
        sys.exit(tr("bad_interval"))
    while True:
        text = load_or_die()              # sets ROSTER/LANG from the current file
        agent = need_agent(args.agent)    # validated against the current roster
        lk = get_lock(text)
        st = lk.get("state", "")
        target = f"AWAITING_{agent.upper()}"
        if st in (target, "IDLE"):
            key = "wait_your_turn" if st == target else "wait_free"
            print(tr(key, st=st, agent=agent))
            return 0
        if st == "DONE":
            print(tr("wait_done"))
            return 0
        exp = parse_iso(lk.get("expires"))
        if st == f"WORKING_{other(agent).upper()}" and exp and now() > exp:
            print(tr("wait_stale", other=other(agent)))
            return 0
        if args.once:  # single, non-blocking poll: rc=3 = not (yet) your turn
            print(tr("wait_not_yet", st=st, holder=lk.get("holder")))
            return 3
        print(tr("wait_poll", st=st, holder=lk.get("holder"), interval=args.interval))
        time.sleep(args.interval)


def cmd_claim(args):
    with file_lock():
        text = load_or_die()             # sets ROSTER/LANG from the on-disk file…
        agent = need_agent(args.agent)   # …so the agent is validated against it
        lk = get_lock(text)
        st = lk.get("state", "")
        holder = lk.get("holder", "none")
        exp = parse_iso(lk.get("expires"))
        stale = st.startswith("WORKING_") and exp is not None and now() > exp
        # your turn / IDLE / your own lock (TTL refresh); --force ONLY if stale.
        mine = st in ("IDLE", f"AWAITING_{agent.upper()}", f"WORKING_{agent.upper()}")
        if not (mine or (args.force and stale)):
            if args.force and st.startswith("WORKING_"):
                sys.exit(tr("claim_active", holder=holder, expires=lk.get("expires")))
            sys.exit(tr("claim_refused", st=st, holder=holder))
        reclaim = args.force and stale and holder not in (agent, "none")
        t = now()
        lk.update(
            holder=agent,
            state=f"WORKING_{agent.upper()}",
            since=iso(t),
            expires=iso(t + dt.timedelta(minutes=TTL_MIN)),
            note=(tr("note_reclaim", holder=holder) if reclaim
                  else tr("note_holds", agent=agent)),
        )
        write(set_lock(text, lk))
    suffix = tr("claim_reclaim_suffix") if reclaim else ""
    print(tr("claim_ok", agent=agent, expires=lk["expires"], suffix=suffix))
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
        sys.exit(tr("body_error", e=e))


def cmd_append(args):
    # Field/body reading stays OUTSIDE the critical section (stdin may block); agent
    # validation happens UNDER the lock, against the roster load_or_die reads.
    ask = clean_field("--ask", args.ask) or "—"
    done = clean_field("--done", args.done) or "—"
    files = clean_field("--files", args.files) or "—"
    body = clean_body(_read_body(args.body))

    with file_lock():
        text = load_or_die()
        agent = need_agent(args.agent)
        to = need_agent(args.to)
        if to == agent:
            sys.exit(tr("to_self_append"))
        lk = get_lock(text)
        st = lk.get("state", "")
        # append is allowed ONLY if you already hold the pen (prior exclusive claim).
        # This is what guarantees exclusivity of the WORK WINDOW, not just of the
        # journal write: you cannot work+append from IDLE.
        if st != f"WORKING_{agent.upper()}":
            sys.exit(tr("append_need_claim", st=st, agent=agent))
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

        # insert the turn at the end of the file (append-only journal)
        text = text.rstrip("\n") + "\n\n" + block

        t = now()
        lk.update(
            holder=to,
            state=f"AWAITING_{to.upper()}",
            turn=str(n),
            since=iso(t),
            expires="-",
            note=tr("note_turn", n=n, agent=agent, to=to),
        )
        write(set_lock(text, lk))
    print(tr("append_ok", n=n, agent=agent, to=to))
    return 0


def cmd_release(args):
    with file_lock():
        text = load_or_die()
        agent = need_agent(args.agent)
        to = need_agent(args.to)
        if to == agent:
            sys.exit(tr("to_self"))
        lk = get_lock(text)
        holder = lk.get("holder", "none")
        if holder not in (agent, "none") and not args.force:
            sys.exit(tr("not_holder_release", holder=holder))
        t = now()
        lk.update(
            holder=to, state=f"AWAITING_{to.upper()}",
            since=iso(t), expires="-",
            note=tr("note_release", to=to, agent=agent),
        )
        write(set_lock(text, lk))
    print(tr("release_ok", to=to))
    return 0


def cmd_done(args):
    with file_lock():
        text = load_or_die()
        agent = need_agent(args.agent)
        lk = get_lock(text)
        holder = lk.get("holder", "none")
        if holder not in (agent, "none") and not args.force:
            sys.exit(tr("not_holder_done", holder=holder))
        t = now()
        lk.update(holder="none", state="DONE", since=iso(t), expires="-",
                  note=tr("note_done", agent=agent))
        write(set_lock(text, lk))
    print(tr("done_ok"))
    return 0


def cmd_archive(args):
    pat = re.compile(
        r"<!-- COWORK:TURN (\d+) ([a-z][a-z0-9_-]*) BEGIN -->.*?<!-- COWORK:TURN \1 \2 END -->\n?",
        re.DOTALL,
    )
    keep = max(0, args.keep)
    with file_lock():
        text = load_or_die()
        # the bootstrap turn #0 (system) always stays in the living file
        matches = [m for m in pat.finditer(text) if m.group(1) != "0"]
        if len(matches) <= keep:
            print(tr("archive_none", n=len(matches), keep=keep))
            return 0
        to_move = matches[:-keep] if keep else matches
        moved = "".join(m.group(0) for m in to_move)
        # remove from the living file (last to first to keep offsets valid)
        for m in reversed(to_move):
            text = text[:m.start()] + text[m.end():]
        text = re.sub(r"\n{3,}", "\n\n", text)
        prev = read(ARCHIVE) if os.path.exists(ARCHIVE) else tr("archive_header")
        write(prev + moved, ARCHIVE)  # atomic write (tmp + os.replace)
        write(text)
    print(tr("archive_ok", n=len(to_move), file=os.path.basename(ARCHIVE), keep=keep))
    return 0


def main():
    p = argparse.ArgumentParser(description="Single-file Claude <-> Codex relay (portable).")
    sub = p.add_subparsers(dest="cmd", required=True)

    i = sub.add_parser("init", help="(re)generate the kit in this folder")
    i.add_argument("--name", default="")
    i.add_argument("--agents", default="",
                   help="comma-separated agent roster; the first two relay "
                        "(e.g. claude,codex). Extra names are reserved for the "
                        "future N-agent mode.")
    i.add_argument("--lang", choices=LANGS, default="",
                   help="language of generated files (default: en, or $COWORK_LANG)")
    i.add_argument("--force", action="store_true", help="also reset COWORK.md")
    i.set_defaults(fn=cmd_init)

    sub.add_parser("status").set_defaults(fn=cmd_status)

    w = sub.add_parser("wait")
    w.add_argument("agent")
    w.add_argument("--interval", type=int, default=60)
    w.add_argument("--once", action="store_true", help="check once and exit (rc 3 if not your turn)")
    w.set_defaults(fn=cmd_wait)

    c = sub.add_parser("claim")
    c.add_argument("agent")
    c.add_argument("--force", action="store_true")
    c.set_defaults(fn=cmd_claim)

    a = sub.add_parser("append")  # requires WORKING_<agent>: run `claim` first
    a.add_argument("agent")
    a.add_argument("--to", required=True)
    a.add_argument("--ask", default="")
    a.add_argument("--done", default="")
    a.add_argument("--files", default="")
    a.add_argument("--body", default="")
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
    # ROSTER/LANG are resolved per command by load_or_die (and by cmd_init), under
    # the file lock, so agent validation always matches the on-disk roster.
    sys.exit(args.fn(args))


if __name__ == "__main__":
    main()
