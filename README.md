# cowork

**Relais mono-fichier pour faire coopérer deux agents IA** (Claude ⇄ Codex) sur
un même dépôt, en alternance stricte (mutex coopératif), avec poll périodique.
Pensé pour être utilisé par les agents **sans intervention ni explication
humaine** : toute la marche à suivre est embarquée dans les fichiers générés.

Tout le kit tient dans **un seul fichier** : [`cowork.py`](cowork.py). On le
copie à la racine d'un projet, on lance `init`, et les deux agents se relaient
via le fichier partagé `COWORK.md`.

---

## Pourquoi

Quand Claude et Codex travaillent sur le même dépôt, ils s'écrasent. `cowork`
introduit un **stylo unique** : à tout instant, un seul agent a le droit
d'écrire ; l'autre attend son tour et sait précisément ce qu'on lui demande.
L'état de coordination vit dans un fichier versionnable, lisible à l'œil comme
au `grep`, et conservé dans le temps.

## Installation / déploiement sur un projet

```bash
cp cowork.py /mon/projet/             # le SEUL fichier nécessaire
cd /mon/projet
python3 cowork.py init                # nom du projet = nom du dossier (sinon --name "X")
```

`init` génère et s'adapte au projet (idempotent, ré-exécutable sans risque) :

| fichier généré          | rôle |
|-------------------------|------|
| `COWORK.md`             | **le** fichier vivant : verrou (`LOCK`) + journal des tours |
| `COWORK.protocol.md`    | l'instruction commune complète (lue une fois par chaque agent) |
| `CLAUDE.md` / `AGENTS.md` | ancrages canoniques — stanza injectée en tête, sans dupliquer ni écraser le contenu existant |
| `AGENTS.override.md` | s'il existe, ancrage Codex prioritaire ; la stanza y est également synchronisée |

## Amorçage : comment les IA le prennent en compte

cowork est **passif** — il n'« appelle » aucune IA. Il s'appuie sur la convention
de chaque outil : **Claude charge `CLAUDE.md`, Codex charge `AGENTS.md`** au
démarrage d'une session/exécution. `init` y injecte en tête une *stanza* qui dit
à chaque agent :
« si un `COWORK.md` existe, lis `COWORK.protocol.md` et applique-le
(`claim → travail → append`) ».

```text
cowork.py init ─▶ stanza dans CLAUDE.md / AGENTS.md
                      └─▶ l'IA lit son ancrage ─▶ découvre la stanza ─▶ suit le protocole
```

- **Après `init`** : démarre une nouvelle session/exécution ; une session déjà
  ouverte ne recharge pas nécessairement ses instructions.
- **Codex interactif et `codex exec`** chargent `AGENTS.md` lorsqu'ils sont lancés
  depuis la racine du projet ou un sous-dossier. Un cron/CI lancé hors du projet
  ne le découvre pas automatiquement.
- **`AGENTS.override.md`** masque `AGENTS.md` dans le même dossier. S'il existe,
  `init` synchronise la stanza dans les deux fichiers.
- **Noms canoniques** : une variante unique comme `agents.md` est renommée
  `AGENTS.md`, y compris sur un FS insensible à la casse. Des variantes multiples
  sont refusées afin de ne pas fusionner silencieusement du contenu utilisateur.
- **Limite Codex** : Codex empile les ancrages jusqu'à un plafond *combiné*
  (32 Kio par défaut) et **saute les fichiers entiers** au-delà (coupe au fichier
  près). La stanza en tête la rend prioritaire dans le fichier, mais un ancrage
  trop gros est ignoré en entier — garde-le **léger**.
- **Limite générale** : cowork ne peut pas forcer une IA à lire son ancrage. Sans
  contexte projet, pointe explicitement l'agent vers `COWORK.protocol.md`.

Référence : [découverte des instructions `AGENTS.md` par Codex](https://developers.openai.com/codex/guides/agents-md).

## Boucle d'un agent

```bash
./cowork.py status                # qui a la main ? (non bloquant)
./cowork.py wait claude --once    # rc 0 = tu peux acquérir ; rc 3 = pas encore
# ACQUIERS le stylo AVANT de travailler (exclusif : un seul gagnant) :
./cowork.py claim claude          # rc 0 = tu tiens le stylo ; sinon ce n'est pas ton tour
# puis travaille dans le dépôt, et clos ton tour en passant la main :
./cowork.py append claude --to codex --ask "ce que tu attends" --done "ce que tu as fait" --files a,b
# pas ton tour ? bloque jusqu'à ton tour, puis retente claim :
./cowork.py wait claude           # poll ~60 s (--interval N)
```

Règle d'or : **on ne travaille et n'écrit qu'après avoir acquis le stylo via
`claim`** (`append` n'est accepté que depuis `WORKING_<soi>`).

## Le verrou (`LOCK`)

En tête de `COWORK.md`, entre `<!-- COWORK:LOCK:BEGIN -->` et `:END` :

| champ | valeurs |
|-------|---------|
| `holder`  | `claude` \| `codex` \| `none` |
| `state`   | `IDLE` \| `WORKING_CLAUDE` \| `WORKING_CODEX` \| `AWAITING_CLAUDE` \| `AWAITING_CODEX` \| `DONE` |
| `turn`    | numéro du dernier tour clôturé |
| `since` / `expires` | horodatages ISO-8601 UTC (TTL anti-blocage 30 min) |
| `note`    | mémo lisible |

Les tours sont encadrés par des commentaires HTML `COWORK:TURN <n> <agent>
BEGIN/END` (invisibles dans le rendu Markdown, faciles à `grep`) et sont
**immuables** une fois clôturés.

## Commandes

```text
init [--name PROJET] [--force]          (re)génère le kit dans le dossier courant
status                                  affiche le verrou + le dernier tour (non bloquant)
wait <agent> [--once] [--interval N]    attend son tour (--once : 1 check, rc 3 si pas son tour)
claim <agent> [--force]                 ACQUIERT le stylo, exclusif (--force : verrou périmé uniquement)
append <agent> --to <autre> --ask … --done … [--files …] [--body f|-]   clôt ton tour (exige WORKING_<agent>)
release <agent> --to <autre> [--force]  repasse la main sans corps
done <agent> [--force]                  clôt la session (state=DONE)
archive [--keep N]                      purge les vieux tours clôturés (jamais le tour #0)
```

Détail complet, états et règles → [`docs/COWORK.protocol.md`](docs/COWORK.protocol.md)
(commencer par son **§0 — quickstart**). Spécification → [cahier des charges](docs/CAHIER-DES-CHARGES.md).
Conception & exploitation → [document d'architecture](docs/ARCHITECTURE.md).

## Garanties (vérifiées par les tests et par revue multi-agents)

- **Mutex sur la fenêtre de travail** : `claim` est l'**acquisition exclusive** du
  stylo (deux `claim` simultanés claude/codex ⇒ un seul gagne) ; `append` n'est
  accepté que depuis `WORKING_<soi>`. On ne travaille qu'après un `claim` réussi,
  donc deux agents ne modifient jamais le dépôt en même temps. `--to` ≠ soi.
- **Anti-blocage** : `claim --force` ne reprend **qu'un verrou périmé** (refus sur
  un verrou actif) ; le détenteur peut rafraîchir le sien.
- **Garde-fous** : `release`/`done` exigent de tenir le stylo (`--force` = récupération).
- **Concurrence sérialisée** : verrou inter-process `.cowork.lock` (`O_EXCL`, à
  jeton d'ownership) + écriture atomique (temporaire **unique** + `os.replace`,
  mode préservé) → deux `cowork.py` simultanés ne se corrompent pas.
- **Anti-injection** : champs mono-ligne (refus saut de ligne / marqueurs
  réservés) ; corps de tour neutralisé contre les faux marqueurs.
- **Borné dans le temps** : `archive` purge les anciens tours sans toucher au verrou ni au tour d'amorçage.
- **Portable** : dossier vide ou dépôt git, chemins à espaces/accents, FS sensible
  ou non à la casse, ancrages préexistants — sans casse ni doublon.

## Tests

Aucune dépendance externe (stdlib seule) :

```bash
python3 -m unittest discover -s tests        # depuis la racine du repo
```

43 tests : unitaires (fonctions pures) + non-régression CLI (un test par bug
corrigé, référencés `NR-n`, + modèle claim, mutex, concurrence claude/codex,
ancrages canoniques/override, archive, robustesse, anti-injection).

## Structure

```text
cowork/
├── cowork.py                 # le kit (source de vérité unique)
├── README.md
├── docs/
│   ├── CAHIER-DES-CHARGES.md  # spécification
│   └── COWORK.protocol.md     # protocole rendu (généré depuis cowork.py)
└── tests/
    └── test_cowork.py
```

## Prérequis

Python 3.8+ (stdlib uniquement). Aucune installation, aucun paquet tiers.

## Licence

Usage interne. Protocole v1.
