![CoWork](CoWork-logo.png)

# CoWork

**Un relais en fichier unique qui permet à deux agents IA (Claude ⇄ Codex) de coopérer sur le même dépôt par alternance stricte.**

[![License: Apache 2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![tests](https://img.shields.io/badge/tests-46%20passing-brightgreen.svg)](#tests)
[![python](https://img.shields.io/badge/python-3.8%2B-blue.svg)](#installation)
[![single file](https://img.shields.io/badge/single%20file-cowork.py-orange.svg)](cowork.py)

[English](README.md) | Français

---

## Qu'est-ce que CoWork ?

CoWork est un **mutex coopératif** pour agents IA. Quand Claude et Codex travaillent sur le
même dépôt, ils s'écrasent mutuellement. CoWork introduit un unique **stylo** : à
tout instant, exactement un agent est autorisé à écrire ; l'autre attend son tour et
sait précisément ce qu'on attend de lui.

Tout le kit tient dans **un seul fichier** : [`cowork.py`](cowork.py). Vous le copiez à la
racine d'un projet, lancez `init`, et les deux agents se passent la main via un
fichier `COWORK.md` partagé. Il est conçu pour être piloté par les agents eux-mêmes,
**sans intervention ni explication humaine** — toute la procédure est embarquée dans
les fichiers générés.

## Pourquoi

Quand Claude et Codex partagent un dépôt, ils n'ont aucun moyen de prendre les tours :
les modifications entrent en collision et le travail est perdu. CoWork corrige cela avec un
unique verrou exclusif (le **stylo**) et une règle simple — **acquérir le stylo avant de
travailler** — pour que les deux agents ne modifient jamais le dépôt en même temps. L'état de
coordination vit dans un fichier versionnable, lisible à l'œil comme par `grep`, et préservé
dans le temps. Pas de démon, pas de serveur, pas de dépendance externe — juste un fichier
Python et les conventions propres des outils hôtes.

## Installation

```bash
cp cowork.py /mon/projet/           # le SEUL fichier dont vous avez besoin
cd /mon/projet
python3 cowork.py init              # nom du projet = nom du dossier (ou --name "X")
```

`init` est idempotent (relançable sans risque) et génère :

| fichier généré              | rôle |
|-----------------------------|------|
| `COWORK.md`                 | **le** fichier vivant : le verrou (`LOCK`) + le journal des tours |
| `COWORK.protocol.md`        | l'instruction partagée complète (lue une fois par chaque agent) |
| `CLAUDE.md` / `AGENTS.md`   | ancrages canoniques — une stance est injectée en tête sans dupliquer ni écraser le contenu existant |
| `AGENTS.override.md`        | s'il est présent, l'ancrage Codex prioritaire ; la stance y est synchronisée aussi |

Utilisez `--lang en|fr` pour choisir la langue des fichiers générés (**anglais par
défaut**).

## Démarrage rapide

Chaque agent exécute la même boucle : `wait → claim → work → append`. `<you>` est `claude`
ou `codex` ; `<other>` est l'autre agent.

```bash
./cowork.py status                # qui détient le stylo ? (non bloquant)
./cowork.py wait claude --once    # rc 0 = vous pouvez acquérir ; rc 3 = pas encore

# Acquérir le stylo AVANT de travailler (exclusif : un seul gagnant) :
./cowork.py claim claude          # rc 0 = vous détenez le stylo ; sinon ce n'est pas votre tour

# ...travaillez dans le dépôt, puis clôturez votre tour et passez la main :
./cowork.py append claude --to codex \
    --ask  "ce dont vous avez besoin de l'autre" \
    --done "ce que vous venez de faire" \
    --files a,b

# Pas votre tour ? Bloquez jusqu'à ce qu'il arrive, puis relancez claim :
./cowork.py wait claude           # interroge ~60s (--interval N)
```

**Règle d'or :** vous ne travaillez et n'écrivez **qu'après avoir acquis le stylo via `claim`**
(`append` n'est accepté que depuis `WORKING_<you>`).

## Documentation

La documentation suit le cadre [Diátaxis](https://diataxis.fr/) :

- **Tutoriel** — [docs/fr/tutoriel.md](docs/fr/tutoriel.md) — apprenez le relais pas à pas.
- **Guide (VS Code)** — [docs/fr/guide-vscode.md](docs/fr/guide-vscode.md) — lancez le relais avec Claude + Codex.
- **Référence (protocole)** — [docs/fr/protocole.md](docs/fr/protocole.md) — le protocole partagé, les états et les règles.
- **Référence (cahier des charges)** — [docs/fr/cahier-des-charges.md](docs/fr/cahier-des-charges.md) — la spécification complète.
- **Explication (architecture)** — [docs/fr/architecture.md](docs/fr/architecture.md) — conception et fonctionnement.

## Comment ça marche

CoWork stocke son état dans le bloc `LOCK` en tête de `COWORK.md`. Pour travailler, un
agent doit d'abord **prendre le stylo** avec `claim` (état `WORKING_<you>`), une
**acquisition exclusive** : si deux agents font `claim` en même temps, un seul gagne. Comme le
travail n'a lieu que pendant que vous détenez le stylo et que `append` n'est accepté que depuis
`WORKING_<you>`, les deux agents n'écrivent jamais le dépôt en concurrence. Cette
règle **claim-avant-travail** est le cœur de CoWork.

Les champs du verrou — `holder`, `state`, `turn`, `since`, `expires`, `note`, `lang` —
sont un `key: value` par ligne (faciles à `grep`er). Les états sont `IDLE`,
`WORKING_CLAUDE`, `WORKING_CODEX`, `AWAITING_CLAUDE`, `AWAITING_CODEX`, `DONE`.
Les tours sont encadrés par des commentaires HTML `COWORK:TURN <n> <agent> BEGIN/END` (invisibles dans
le rendu Markdown) et sont **immuables** une fois clos.

## Garanties

Vérifiées par les tests et par revue multi-agents :

- **Mutex sur la fenêtre de travail** — `claim` est l'acquisition exclusive du stylo
  (deux `claim`s simultanés ⇒ un seul gagnant) ; `append` n'est accepté que depuis
  `WORKING_<you>`. Vous ne travaillez qu'après un `claim` réussi, donc deux agents ne
  modifient jamais le dépôt en même temps. `--to` ≠ soi-même (alternance stricte).
- **Récupération de verrou périmé** — `claim --force` ne réclame **qu'un verrou périmé** (refusé
  sur un verrou actif) ; le détenteur peut rafraîchir son propre verrou.
- **Garde-fous** — `release` / `done` exigent de détenir le stylo (`--force` = récupération).
- **Concurrence sérialisée** — un verrou inter-processus `.cowork.lock` (`O_EXCL`, avec
  un jeton d'ownership) plus des écritures atomiques (fichier temporaire unique + `os.replace`, mode
  préservé) ⇒ deux exécutions concurrentes de `cowork.py` ne corrompent jamais le fichier.
- **Sûr contre l'injection** — champs sur une seule ligne (sauts de ligne et marqueurs
  réservés rejetés) ; corps des tours neutralisés contre les faux marqueurs.
- **Borné dans le temps** — `archive` purge les anciens tours clos sans toucher au
  verrou ni au tour d'amorçage (tour #0).
- **Portable** — dossier vide ou dépôt git, chemins avec espaces/accents,
  systèmes de fichiers sensibles ou insensibles à la casse, ancrages préexistants — sans
  casse ni duplication.

## Tests

Aucune dépendance Python externe (stdlib uniquement) :

```bash
python3 -m unittest discover -s tests        # depuis la racine du dépôt
```

**46 tests** : tests unitaires (fonctions pures) + tests de régression CLI (un par
bug corrigé, référencé `NR-n`) couvrant le modèle de claim, le mutex, la concurrence claude/codex,
les ancrages canoniques/override, l'archive, la robustesse et la sûreté face à l'injection.

## Roadmap

CoWork conserve un **mutex à stylo unique** (un seul écrivain à la fois) par
conception — voir [architecture §1.8](docs/fr/architecture.md). Deux étapes :

1. **Couple configurable** — choisir les deux agents du relais dans un **roster
   extensible** (claude, codex, lechat, …) en restant à **2 simultanés** (degré 1).
   Brouillon : [RFC — couple d'agents configurable](docs/fr/rfc-roster.md).
2. **N agents simultanés** — vrai multi-agent (degré > 1) ; une étape distincte et
   plus lourde, avec son propre RFC futur.

## Licence

Sous licence [Apache License 2.0](LICENSE).

## Contribuer

Les issues et pull requests sont les bienvenues. CoWork est un fichier unique par conception
([`cowork.py`](cowork.py) est la source de vérité unique — `COWORK.protocol.md` en est
généré), donc gardez les changements ciblés et couverts par un test dans `tests/`. Lancez
la suite de tests avant d'ouvrir une PR.
