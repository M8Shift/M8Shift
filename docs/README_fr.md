![CoWork](../CoWork-logo.png)

# CoWork

**Un relais en fichier unique qui permet à deux agents IA — un couple configurable depuis un roster (la liste d'agents disponibles : Claude, Codex, Gemini, Le Chat, …) — de coopérer sur le même dépôt par alternance stricte.**

[![License: Apache 2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](../LICENSE)
[![tests](https://img.shields.io/badge/tests-74%20passing-brightgreen.svg)](#tests)
[![python](https://img.shields.io/badge/python-3.8%2B-blue.svg)](#installation)
[![single file](https://img.shields.io/badge/single%20file-cowork.py-orange.svg)](../cowork.py)
[![sans clé API](https://img.shields.io/badge/cl%C3%A9%20API-non%20requise-success.svg)](#tourne-partout--sans-clé-api)
[![made with CoWork](https://img.shields.io/badge/made%20with-%E2%9D%A4%20%26%20CoWork-ff69b4.svg)](../docs/fr/cahier-des-charges.md#11-développer-cowork-avec-cowork-dogfooding)

[English](../README.md) | Français

---

## Qu'est-ce que CoWork ?

CoWork est un **mutex coopératif** pour agents IA. Quand Claude et Codex travaillent sur le
même dépôt, ils s'écrasent mutuellement. CoWork introduit un unique **stylo** : à
tout instant, exactement un agent est autorisé à écrire ; l'autre attend son tour et
sait précisément ce qu'on attend de lui.

Tout le kit tient dans **un seul fichier** : [`cowork.py`](../cowork.py). Vous le copiez à la
racine d'un projet, lancez `init`, et les deux agents se passent la main via un
fichier `COWORK.md` partagé. Toute la procédure est **embarquée dans les fichiers
générés**, donc les agents n'ont besoin d'**aucune explication humaine**. *Réserve pour
les UI interactives* (VS Code, …) : un humain relance quand même chaque agent pour qu'il
*reprenne* entre les tours — `wait` bloque un processus mais ne réveille pas l'UI de chat
d'un agent. Voir [Limites](#limites).

## Pourquoi

Quand Claude et Codex partagent un dépôt, ils n'ont aucun moyen de prendre les tours :
les modifications entrent en collision et le travail est perdu. CoWork corrige cela avec un
unique verrou exclusif (le **stylo**) et une règle simple — **acquérir le stylo avant de
travailler** — pour que les deux agents ne modifient jamais le dépôt en même temps. L'état de
coordination vit dans un fichier versionnable, lisible à l'œil comme par `grep`, et préservé
dans le temps. Pas de démon, pas de serveur, pas de dépendance externe — juste un fichier
Python et les conventions propres des outils hôtes.

## Tourne partout — sans clé API

CoWork est un **CLI passif** : les agents le pilotent par des commandes shell, donc il
fonctionne sur toutes les surfaces où tournent Claude Code ou Codex, et il n'ajoute
**aucun identifiant**.

| Surface | Marche ? | Notes |
|---------|----------|-------|
| Terminal / CLI | ✅ | en *headless* (`claude -p`, `codex exec`, cron) c'est **entièrement automatisable** — voir [`examples/headless_runner.py`](../examples/headless_runner.py) |
| Application desktop (Mac/Windows) | ✅ | interactif : un humain relance chaque agent entre les tours |
| VS Code / JetBrains (IDE) | ✅ | comme le desktop |
| Web (claude.ai/code) | ✅ | partout où l'agent peut lancer un shell et lire son ancrage |

**Aucune clé API. Aucun jeton. Aucun compte pour CoWork lui-même.** `cowork.py` ne fait
**aucun appel réseau** (stdlib uniquement, fichiers locaux) — les agents utilisent
l'abonnement ou la connexion que tu as déjà. Rien ne quitte ta machine, aucun coût par
appel, aucun verrouillage propriétaire.

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
| `CLAUDE.md`, `AGENTS.md`, … | l'ancrage canonique de chaque agent actif (le couple par défaut est montré) — une strophe est injectée en tête sans dupliquer ni écraser le contenu existant ; le fichier précédent est sauvegardé dans `<ancrage>.cowork.bak` |
| `AGENTS.override.md`        | s'il est présent, l'ancrage prioritaire de Codex ; la strophe y est synchronisée aussi |

Utilisez `--lang en|fr` pour choisir la langue des fichiers générés (**anglais par
défaut**). Utilisez `--agents a,b` pour choisir le couple du relais dans le roster
(défaut `claude,codex` ; les **deux premiers** noms sont actifs, les noms
supplémentaires sont stockés pour le futur mode N agents).

**Sous Windows ?** Aucune dépendance (stdlib uniquement) — lancez via WSL, Git Bash,
ou `python cowork.py <cmd>` dans PowerShell. Voir [Lancer sous Windows](../docs/fr/windows.md).

**Depuis un fork / clone ?** CoWork tient en un fichier — hébergez-le sur n'importe quel
Git ou GitLab : `git clone https://gitlab.example.com/you/CoWork.git`, puis
`cp cowork.py /mon/projet/` et lancez `init` comme ci-dessus.

## Démarrage rapide

Chaque agent exécute la même boucle : `wait → claim → work → append`. `<toi>` est ton
propre nom d'agent et `<autre>` l'autre agent actif (les exemples ci-dessous utilisent
le couple par défaut `claude`/`codex`).

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
(`append` n'est accepté que depuis `WORKING_<toi>`).

## Documentation

La documentation suit le cadre [Diátaxis](https://diataxis.fr/) :

- **Tutoriel** — [docs/fr/tutoriel.md](../docs/fr/tutoriel.md) — apprenez le relais pas à pas.
- **Guide (VS Code)** — [docs/fr/guide-vscode.md](../docs/fr/guide-vscode.md) — lancez le relais avec Claude + Codex.
- **Guide (Windows)** — [docs/fr/windows.md](../docs/fr/windows.md) — lancez sous Windows (WSL / Git Bash / natif).
- **Référence (protocole)** — [docs/fr/protocole.md](../docs/fr/protocole.md) — le protocole partagé, les états et les règles.
- **Référence (cahier des charges)** — [docs/fr/cahier-des-charges.md](../docs/fr/cahier-des-charges.md) — la spécification complète.
- **Explication (architecture)** — [docs/fr/architecture.md](../docs/fr/architecture.md) — conception et fonctionnement.

## Comment ça marche

CoWork stocke son état dans le bloc `LOCK` en tête de `COWORK.md`. Pour travailler, un
agent doit d'abord **prendre le stylo** avec `claim` (état `WORKING_<toi>`), une
**acquisition exclusive** : si deux agents font `claim` en même temps, un seul gagne. Comme le
travail n'a lieu que pendant que vous détenez le stylo et que `append` n'est accepté que depuis
`WORKING_<toi>`, les deux agents n'écrivent jamais le dépôt en concurrence. Cette
règle **claim-avant-travail** est le cœur de CoWork.

Les champs du verrou — `holder`, `state`, `agents`, `turn`, `since`, `expires`,
`note`, `lang` — sont un `key: value` par ligne (faciles à `grep`er). `holder` est un
agent actif ou `none` ; `agents` est le couple du relais (les 2 premiers déclarés,
défaut `claude,codex`) ; les états sont `IDLE`, `WORKING_<X>`, `AWAITING_<X>`, `DONE`
(`<X>` = un agent actif, en majuscules). Les tours sont encadrés par des commentaires
HTML `COWORK:TURN <n> <agent> BEGIN/END` (invisibles dans
le rendu Markdown) et sont **immuables** une fois clos.

## Garanties

Vérifiées par les tests et par revue multi-agents :

- **Mutex sur la fenêtre de travail** — `claim` est l'acquisition exclusive du stylo
  (deux `claim`s simultanés ⇒ un seul gagnant) ; `append` n'est accepté que depuis
  `WORKING_<toi>`. Vous ne travaillez qu'après un `claim` réussi, donc deux agents ne
  modifient jamais le dépôt en même temps. `--to` ≠ soi-même (alternance stricte).
- **Récupération de verrou périmé** — `claim --force` ne réclame **qu'un verrou périmé** (refusé
  sur un verrou actif) ; le détenteur peut rafraîchir son propre verrou.
- **Garde-fous** — `release` / `done` exigent de détenir le stylo (`--force` = récupération).
- **Concurrence sérialisée** — un verrou inter-processus `.cowork.lock` (`O_EXCL`, avec
  un jeton de propriété) plus des écritures atomiques (fichier temporaire unique + `os.replace`, mode
  préservé) ⇒ deux exécutions concurrentes de `cowork.py` ne corrompent jamais le fichier.
- **Sûr contre l'injection** — champs sur une seule ligne (sauts de ligne et marqueurs
  réservés rejetés) ; corps des tours neutralisés contre les faux marqueurs.
- **Borné dans le temps** — `archive` purge les anciens tours clos sans toucher au
  verrou ni au tour d'amorçage (tour #0).
- **Portable** — dossier vide ou dépôt git, chemins avec espaces/accents,
  systèmes de fichiers sensibles ou insensibles à la casse, ancrages préexistants — sans
  casse ni duplication.

## Limites

- **Réveiller l'UI d'un agent interactif.** `wait` bloque un *processus* jusqu'à ton
  tour ; il ne **relance ni ne réveille** un agent tournant dans une UI interactive
  (VS Code, …). Entre les tours, un humain relance quand même chaque agent (p. ex.
  *« reprends CoWork »*). Une opération entièrement autonome exige une boucle **headless (sans interface)**
  (`claude -p`, `codex exec`, cron) enveloppant `wait → relancer l'agent → claim` — une
  intégration à l'hôte, pas une modification du mutex. Une notification système/webhook
  peut *signaler* un tour mais ne peut pas *réveiller* l'IA à elle seule. Un exemple de
  lanceur est fourni : [`examples/headless_runner.py`](../examples/headless_runner.py).
- **Coopératif, deux agents, verrou conseillé** — voir le
  [cahier des charges](../docs/fr/cahier-des-charges.md) §8 (mutex coopératif, verrou
  conseillé, deux agents simultanés).

## Tests

Aucune dépendance Python externe (stdlib uniquement) :

```bash
python3 -m unittest discover -s tests        # depuis la racine du dépôt
```

**74 tests** : tests unitaires (fonctions pures) + tests de régression CLI (un par
bug corrigé, référencé `NR-n`) couvrant le modèle de claim, le mutex, la concurrence claude/codex,
les ancrages canoniques/override, le roster configurable, l'archive, la robustesse et la sûreté face à l'injection.

## Roadmap

CoWork conserve un **mutex à stylo unique** (un seul écrivain à la fois) par
conception — voir [architecture §1.8](../docs/fr/architecture.md). Deux étapes :

1. **Couple configurable (livré)** — choisir les deux agents du relais dans un
   **roster extensible** via `cowork.py init --agents a,b` ; les deux premiers
   relaient, les noms supplémentaires sont stockés pour plus tard. Toujours
   **2 simultanés** (degré 1). Voir [RFC — couple d'agents configurable](../docs/fr/rfc-roster.md).
2. **N agents simultanés** — vrai multi-agent (degré > 1) ; une étape distincte et
   plus lourde, avec son propre RFC futur.

## Licence

Sous licence [Apache License 2.0](../LICENSE).

## Contribuer

Les issues et pull requests sont les bienvenues. CoWork est un fichier unique par conception
([`cowork.py`](../cowork.py) est la source de vérité unique — `COWORK.protocol.md` en est
généré), donc gardez les changements ciblés et couverts par un test dans `tests/`. Lancez
la suite de tests avant d'ouvrir une PR.
