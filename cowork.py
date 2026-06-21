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
- done:    Initialisation du relais. Le premier agent qui démarre fait
           `./cowork.py claim claude` (ou `codex`), travaille, puis
           `./cowork.py append claude --to codex --ask "..." --done "..."`.
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
- **Alternance stricte** : claude → codex → claude … Chaque passage de main est
  un *tour* (`TURN`) numéroté, encadré `BEGIN`/`END`.
- **Poll** : quand ce n'est pas ton tour, tu attends (`./cowork.py wait <toi>`,
  ~60 s) puis tu retentes `claim`.

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
>    `O_CREAT|O_EXCL`, à jeton d'ownership) : chaque read-modify-write du LOCK +
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
./cowork.py init [--name PROJET] [--force]        # (re)génère le kit dans CE dossier
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
    """Écriture atomique : fichier temporaire UNIQUE + os.replace, en préservant
    le mode du fichier cible existant (mkstemp force 0600 sinon)."""
    d = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".cowork-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        try:
            os.chmod(tmp, os.stat(path).st_mode)  # conserver le mode existant
        except OSError:
            os.chmod(tmp, 0o666 & ~_current_umask())  # nouveau fichier : mode usuel
        os.replace(tmp, path)  # remplacement atomique
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


@contextlib.contextmanager
def file_lock(timeout=LOCK_TIMEOUT):
    """Verrou inter-process via création exclusive d'un fichier (O_CREAT|O_EXCL).

    Sérialise le read-modify-write du LOCK : deux `cowork.py` concurrents ne
    peuvent pas muter `COWORK.md` en même temps. Le verrou porte un **jeton
    d'ownership** : on ne le supprime (en fin de section, ou en reprise d'un verrou
    abandonné depuis LOCK_STALE_S) qu'après avoir vérifié le jeton, pour ne jamais
    effacer le verrou d'un successeur.
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
                    # toujours périmé ET inchangé depuis la lecture → reprise sûre
                    if time.time() - os.path.getmtime(LOCKFILE) > LOCK_STALE_S:
                        with open(LOCKFILE, "rb") as f2:
                            if f2.read() == victim:
                                os.unlink(LOCKFILE)
                                continue
            except OSError:
                pass
            if time.monotonic() - start > timeout:
                sys.exit("verrou interne occupé (un autre cowork.py écrit) — réessaie.")
            time.sleep(0.05)
    try:
        yield
    finally:
        # ne supprimer QUE notre propre verrou (jeton vérifié)
        try:
            with open(LOCKFILE, "rb") as f:
                mine = f.read() == token
            if mine:
                os.unlink(LOCKFILE)
        except OSError:
            pass


def require_cowork():
    if not os.path.exists(COWORK):
        sys.exit("COWORK.md introuvable — lance d'abord `./cowork.py init`.")


VALID_STATES = ("IDLE", "DONE", "WORKING_CLAUDE", "WORKING_CODEX",
                "AWAITING_CLAUDE", "AWAITING_CODEX")


def load_or_die():
    """Lit COWORK.md en validant le bloc LOCK (présence ET schéma) ; sortie propre
    sinon — aucune valeur invalide ne doit atteindre la logique (pas de traceback)."""
    require_cowork()
    text = read()
    if LOCK_BEGIN not in text or LOCK_END not in text:
        sys.exit("COWORK.md corrompu : bloc LOCK introuvable — "
                 "`./cowork.py init --force` pour réinitialiser le verrou.")
    lk = get_lock(text)
    errs = []
    if lk.get("state") not in VALID_STATES:
        errs.append(f"state={lk.get('state')!r}")
    if not re.fullmatch(r"\d+", lk.get("turn", "")):
        errs.append(f"turn={lk.get('turn')!r}")
    if lk.get("holder") not in ("claude", "codex", "none"):
        errs.append(f"holder={lk.get('holder')!r}")
    if errs:
        sys.exit("COWORK.md corrompu (LOCK invalide : " + ", ".join(errs) + ") — "
                 "`./cowork.py init --force` pour réparer.")
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
            hint = "à toi" if st == target else "libre"
            print(f"✓ {hint} ({st}) — `./cowork.py claim {agent}` pour acquérir le stylo.")
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
        # append n'est permis QUE si tu tiens déjà le stylo (claim exclusif préalable).
        # C'est ce qui garantit l'exclusivité de la FENÊTRE DE TRAVAIL, pas seulement
        # de l'écriture du journal : on ne peut pas travailler+append depuis IDLE.
        if st != f"WORKING_{agent.upper()}":
            sys.exit(f"refus: tu ne tiens pas le stylo (state={st}) — fais d'abord "
                     f"`./cowork.py claim {agent}` (acquisition exclusive), puis append.")
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

    a = sub.add_parser("append")  # exige WORKING_<agent> : fais `claim` d'abord
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
    sys.exit(args.fn(args))


if __name__ == "__main__":
    main()
