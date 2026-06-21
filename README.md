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
| `CLAUDE.md` / `AGENTS.md` | ancrages — Claude lit `CLAUDE.md`, Codex lit `AGENTS.md` ; une *stanza* y est injectée (entre marqueurs, sans dupliquer ni écraser le contenu existant) |

## Boucle d'un agent

```bash
./cowork.py status                # qui a la main ? (non bloquant)
./cowork.py wait claude --once    # rc 0 = à toi de jouer ; rc 3 = pas encore
# si c'est ton tour : travaille dans le dépôt, puis dépose ton tour ET passe la main :
./cowork.py append claude --to codex --ask "ce que tu attends" --done "ce que tu as fait" --files a,b
# sinon, bloquer jusqu'à ton tour :
./cowork.py wait claude           # poll ~60 s (--interval N)
```

Règle d'or : **on n'écrit dans le dépôt que si le verrou nous est attribué.**

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
claim <agent> [--force]                 prend le verrou (--force : verrou périmé uniquement)
append <agent> --to <autre> --ask … --done … [--files …] [--body f|-]   dépose un tour + passe la main
release <agent> --to <autre> [--force]  repasse la main sans corps
done <agent> [--force]                  clôt la session (state=DONE)
archive [--keep N]                      purge les vieux tours clôturés (jamais le tour #0)
```

Détail complet, états et règles → [`docs/COWORK.protocol.md`](docs/COWORK.protocol.md)
(commencer par son **§0 — quickstart**). Spécification → [cahier des charges](docs/CAHIER-DES-CHARGES.md).
Conception & exploitation → [document d'architecture](docs/ARCHITECTURE.md).

## Garanties (vérifiées par les tests et par revue multi-agents)

- **Mutex** : écriture conditionnée à `state == AWAITING_<soi>` ; `append`/`claim`
  refusent hors-tour ; `--to` ne peut pas se viser soi-même.
- **Anti-blocage** : `claim --force` ne reprend **qu'un verrou périmé** (refus sur
  un verrou actif) ; le détenteur peut rafraîchir le sien.
- **Garde-fous** : `release`/`done` exigent de tenir le stylo (`--force` = récupération).
- **Atomicité** : toute écriture passe par un fichier temporaire + `os.replace`.
- **Borné dans le temps** : `archive` purge les anciens tours sans toucher au verrou ni au tour d'amorçage.
- **Portable** : dossier vide ou dépôt git, chemins à espaces/accents, FS sensible
  ou non à la casse, ancrages préexistants — sans casse ni doublon.

## Tests

Aucune dépendance externe (stdlib seule) :

```bash
python3 -m unittest discover -s tests        # depuis la racine du repo
```

26 tests : unitaires (fonctions pures) + non-régression CLI (un test par bug
corrigé, référencés `NR-n`, + cycle, mutex, archive, robustesse).

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
