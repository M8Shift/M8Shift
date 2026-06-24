# Tutoriel — Lancez votre premier relais M8Shift

Ceci est un tutoriel pratique. À la fin, vous aurez exécuté un relais M8Shift
complet du début à la fin dans un dossier jetable : vous jouerez un tour en tant
que `claude`, vous passerez la main, vous jouerez un tour en tant que `codex`,
vous verrez l'alternance stricte se produire, puis vous clôturerez la session.

Vous n'avez pas encore besoin de comprendre tout le protocole. Suivez simplement
les étapes dans l'ordre et comparez chaque sortie console avec le bloc
**Résultat attendu** qui la suit. Si quelque chose paraît différent, lisez
l'encart **Si X s'affiche à la place**.

> Astuce : le `m8shift.py` fourni affiche ses messages runtime en anglais. Les
> variantes générées avec `m8shift-i18n.py` peuvent afficher une autre langue,
> mais les commandes, flags, états et champs du verrou restent identiques.

**Ce qu'il vous faut :** un terminal, Python 3, et le fichier unique `m8shift.py`.
**Durée :** environ 10 minutes.

---

## Étape 1 — Créer un dossier d'essai

Nous allons travailler dans un dossier temporaire afin que rien sur votre
machine ne soit touché. M8Shift est un fichier unique autonome, donc un projet
d'essai n'est qu'un répertoire vide.

```bash
mkdir /tmp/m8shift-toy
cd /tmp/m8shift-toy
```

**Résultat attendu :** aucune sortie. Vous avez maintenant un dossier vide et
votre terminal est positionné à l'intérieur.

---

## Étape 2 — Copier `m8shift.py` dans le dossier

M8Shift se distribue sous forme d'un seul fichier. Pour l'adopter dans n'importe
quel projet, vous copiez ce fichier unique à l'intérieur.

```bash
cp /path/to/m8shift.py .
chmod +x m8shift.py
```

Remplacez `/path/to/m8shift.py` par l'emplacement réel sur votre machine.

**Résultat attendu :** aucune sortie. `ls` devrait maintenant afficher un unique
`m8shift.py`.

**Si `No such file or directory` s'affiche :** le chemin source est erroné.
Localisez d'abord le fichier avec `find ~ -name m8shift.py 2>/dev/null` et
utilisez le chemin qu'il affiche.

---

## Étape 3 — Initialiser le relais avec `init`

La commande `init` génère tout ce dont M8Shift a besoin dans ce dossier : le
fichier de travail partagé `M8SHIFT.md`, la référence de protocole
`M8SHIFT.protocol.md`, et les fichiers d'ancrage (`CLAUDE.md`, `AGENTS.md`) qui
permettent à chaque agent de s'amorcer lui-même.

```bash
./m8shift.py init --name hello-m8shift
```

**Résultat attendu :**

```text
✓ m8shift init — project “hello-m8shift” in /tmp/m8shift-toy
  • M8SHIFT.protocol.md: written
  • M8SHIFT.md: written (project “hello-m8shift”, lock IDLE)
  • CLAUDE.md: file created
  • AGENTS.md: file created
Start: ./m8shift.py claim claude  (then work, then ./m8shift.py append claude --to codex --ask "…" --done "…")
Bootstrap: start a new session/run of each agent to reload its anchor.
```

En clair : le protocole a été écrit, `M8SHIFT.md` a été créé avec un verrou tout
neuf dans l'état `IDLE`, et les deux fichiers d'ancrage ont été créés. Le verrou
démarre à `IDLE` parce que personne ne détient encore le stylo.

**Si `M8SHIFT.md: preserved` s'affiche :** vous avez déjà lancé `init` ici
auparavant, donc l'état de relais existant a été conservé (c'est voulu). Pour ce
tutoriel, repartez de zéro avec
`./m8shift.py init --name hello-m8shift --force`.

---

## Étape 4 — Observer le verrou à l'intérieur de `M8SHIFT.md`

Le cœur de M8Shift est un bloc unique appelé **LOCK** en haut de `M8SHIFT.md`.
C'est un mutex coopératif : quelques lignes `field: value` qui indiquent qui, le
cas échéant, détient le stylo. Ouvrez `M8SHIFT.md` dans n'importe quel éditeur,
ou affichez-en le haut :

```bash
sed -n '/M8SHIFT:LOCK:BEGIN/,/M8SHIFT:LOCK:END/p' M8SHIFT.md
```

**Résultat attendu (la partie verrou) :**

```text
<!-- M8SHIFT:LOCK:BEGIN -->
holder:   none
state:    IDLE
agents:   claude,codex
lang:     en
session:  20260624T155219Z-16e3a02d
turn:     0
since:    2026-06-24T15:52:19Z
expires:  -
note:     session initialized, no turn opened
<!-- M8SHIFT:LOCK:END -->
```

Ce que signifie chaque champ :

- `holder` — qui détient le stylo en ce moment. `none` signifie personne.
- `state` — l'état courant. `IDLE` signifie que le relais est libre de démarrer.
- `agents` — le roster actif. Ici, le défaut `claude,codex`.
- `lang` — la langue générée/runtime.
- `session` — l'identifiant de session utilisé par `history`.
- `turn` — le numéro du dernier tour clôturé. `0` est le tour initial.
- `since` — quand cet état a commencé (ISO-8601 UTC).
- `expires` — l'échéance du verrou périmé. Il ne porte une date que tant que
  quelqu'un est `WORKING_*` ; sinon il vaut `-`.
- `note` — un court mémo lisible par un humain.

Vous n'éditez jamais ce bloc à la main — les commandes `m8shift.py` le
réécrivent pour vous. Les marqueurs `M8SHIFT:LOCK:BEGIN` et `M8SHIFT:LOCK:END`
sont la manière dont l'outil le repère.

---

## Étape 5 — Vérifier l'état avec `status`

`status` est la façon en lecture seule de demander « que dit le verrou ? ». Il
ne bloque jamais et ne change jamais rien, donc il est toujours sûr de
l'exécuter.

```bash
./m8shift.py status
```

**Résultat attendu :**

```text
m8shift.py v3.9.0
── LOCK ───────────────────────────────
  holder   none
  state    IDLE
  agents   claude,codex
  lang     en
  session  20260624T155219Z-16e3a02d
  turn     0
  since    2026-06-24T15:52:19Z  local 2026-06-24 17:52:19 CEST
  expires  -
  note     session initialized, no turn opened
── last turn: #0 by system
```

La dernière ligne confirme que le seul tour pour l'instant est le tour initial
`#0`, posté par `system`. Personne n'a encore joué. Parfait — c'est au tour de
`claude` de commencer.

---

## Étape 6 — En tant que `claude`, confirmer que c'est votre tour avec `wait --once`

Avant de prendre le stylo, un agent vérifie s'il y est autorisé.
`wait <agent> --once` fait exactement une vérification non bloquante puis sort.
Le code de retour `0` signifie « vas-y » ; le code de retour `3` signifie « pas
encore ».

```bash
./m8shift.py wait claude --once
```

**Résultat attendu :**

```text
✓ free (IDLE) — `./m8shift.py claim claude` to acquire the pen.
```

En clair : le relais est libre (`IDLE`), donc `claude` peut maintenant acquérir
le stylo.

**Si `… not your turn` s'affiche :** c'est le cas du code de retour 3 — ce n'est
pas votre tour. À ce stade du tutoriel, cela devrait indiquer `IDLE`. Si ce
n'est pas le cas, vous avez probablement déjà joué un tour ; relancez
`init --force` (Étape 3) pour réinitialiser.

---

## Étape 7 — En tant que `claude`, prendre le stylo avec `claim`

`claim` acquiert le stylo de manière exclusive. Après cela, l'état devient
`WORKING_CLAUDE` et vous — et vous seul — pouvez modifier le projet. Si deux
agents lançaient `claim` au même instant, un seul l'emporterait ; à l'autre il
serait signalé que ce n'est pas son tour.

```bash
./m8shift.py claim claude
```

**Résultat attendu :**

```text
✓ pen taken by claude (expires 2026-06-24T16:22:19Z).
```

En clair : le stylo est désormais détenu par `claude`. Remarquez l'heure
`expires` — elle est fixée 30 minutes plus loin. C'est le garde-fou : si
`claude` venait à planter en tenant le stylo, le verrou deviendrait périmé après
cette échéance et pourrait être repris.

---

## Étape 8 — En tant que `claude`, effectuer un vrai travail

Maintenant que vous détenez le stylo, vous effectuez le travail réel dans le
projet. Pour ce tutoriel, faites un minuscule changement fictif :

```bash
echo "hello from claude" > hello.txt
```

**Résultat attendu :** aucune sortie. Vous avez créé `hello.txt`. Dans un vrai
projet, c'est ici que vous écririez du code, éditeriez des fichiers, lanceriez
des tests — n'importe quoi. La règle est simplement : **travaillez uniquement
tant que vous détenez le stylo.**

---

## Étape 9 — En tant que `claude`, enregistrer votre tour et passer la main avec `append`

`append` clôture votre tour : il écrit un bloc de tour numéroté dans `M8SHIFT.md`
et passe le stylo à l'autre agent. `append` n'est accepté que tant que vous
détenez le stylo, ce qui garantit que la fenêtre de travail elle-même était
exclusive — pas seulement l'écriture du journal.

```bash
./m8shift.py append claude --to codex \
    --ask "review my note" \
    --done "added hello.txt" \
    --files hello.txt
```

- `--to codex` — passer la main à l'autre agent (se passer la main à soi-même
  est refusé : alternance stricte).
- `--ask` — ce que vous voulez que `codex` fasse ensuite, rédigé de façon à
  être actionnable.
- `--done` — ce que vous venez de faire.
- `--files` — les fichiers que vous avez touchés.

**Résultat attendu :**

```text
✓ turn 1 written by claude, handed off to codex.
```

En clair : le tour 1 a été écrit par `claude`, et le stylo a été passé à
`codex`.

---

## Étape 10 — Voir l'alternance avec `status`

Regardez à nouveau le verrou. Il devrait maintenant pointer vers `codex`.

```bash
./m8shift.py status
```

**Résultat attendu :**

```text
m8shift.py v3.9.0
── LOCK ───────────────────────────────
  holder   codex
  state    AWAITING_CODEX
  agents   claude,codex
  lang     en
  session  20260624T155219Z-16e3a02d
  turn     1
  since    2026-06-24T15:52:19Z  local 2026-06-24 17:52:19 CEST
  expires  -
  note     turn 1 posted by claude, awaiting codex
── last turn: #1 by claude
```

Ce qui a changé : `holder` est maintenant `codex`, `state` est `AWAITING_CODEX`
(c'est le tour de codex), `turn` est passé à `1`, et `expires` est revenu à `-`
parce que personne ne travaille activement — le relais attend. Voici
l'alternance stricte en action : claude a joué, donc c'est maintenant le tour de
codex, et jamais à nouveau celui de claude tant que codex n'a pas repassé la
main.

---

## Étape 11 — En tant que `codex`, vérifier et prendre le stylo

Changez maintenant de rôle et jouez en tant que `codex`. Même boucle : vérifier,
puis claim.

```bash
./m8shift.py wait codex --once
./m8shift.py claim codex
```

**Résultat attendu :**

```text
✓ your turn (AWAITING_CODEX) — `./m8shift.py claim codex` to acquire the pen.
✓ pen taken by codex (expires 2026-06-24T16:22:19Z).
```

En clair : la première ligne indique que c'est le tour de codex ; la seconde
confirme que codex détient désormais le stylo (état `WORKING_CODEX`).

---

## Étape 12 — En tant que `codex`, enregistrer un tour et repasser la main

`codex` fait son travail (nous sauterons l'édition fictive cette fois) puis
repasse le stylo à `claude`. Lorsque vous n'avez rien à demander, mettez
`--ask "—"`.

```bash
./m8shift.py append codex --to claude \
    --ask "—" \
    --done "reviewed, looks good" \
    --files hello.txt
```

**Résultat attendu :**

```text
✓ turn 2 written by codex, handed off to claude.
```

En clair : le tour 2 a été écrit par `codex`, et le stylo est revenu à `claude`.
Vous avez maintenant vu un aller-retour complet : claude → codex → claude.

---

## Étape 13 — Inspecter l'alternance complète

Vérifiez l'état une fois de plus pour confirmer le retour de la main.

```bash
./m8shift.py status
```

**Résultat attendu :**

```text
m8shift.py v3.9.0
── LOCK ───────────────────────────────
  holder   claude
  state    AWAITING_CLAUDE
  agents   claude,codex
  lang     en
  session  20260624T155219Z-16e3a02d
  turn     2
  since    2026-06-24T15:52:19Z  local 2026-06-24 17:52:19 CEST
  expires  -
  note     turn 2 posted by codex, awaiting claude
── last turn: #2 by codex
```

L'état est revenu à `AWAITING_CLAUDE` : c'est à nouveau le tour de claude.
Chaque passage de main a incrémenté `turn` (maintenant `2`), et chaque tour a
été enregistré comme un bloc immuable dans `M8SHIFT.md`. Ouvrez `M8SHIFT.md` et
faites défiler vers le bas — vous verrez trois blocs de tour : `#0 system`,
`#1 claude`, `#2 codex`, chacun encadré entre les marqueurs
`M8SHIFT:TURN <n> <agent> BEGIN` et `END`.

---

## Étape 14 — Essayer `archive` pour garder `M8SHIFT.md` court

Au fil d'une longue session, `M8SHIFT.md` grossirait. `archive` déplace les
anciens tours déjà clôturés vers `M8SHIFT.archive.md`, en conservant les plus
récents (et toujours le tour initial `#0`) dans le fichier vivant.

```bash
./m8shift.py archive --keep 6
```

**Résultat attendu :**

```text
nothing to archive (2 archivable turn(s), keep=6).
```

En clair : rien à archiver — vous n'avez que 2 tours archivables et vous avez
demandé d'en garder 6. C'est exactement correct ; l'archivage ne se déclenche
qu'une fois que le fichier vivant a plus de tours que `--keep`. Vous avez
maintenant vu la commande et savez qu'elle est sûre.

---

## Étape 15 — Clôturer la session avec `done`

Lorsque le relais est terminé, le détenteur le clôture avec `done`. Le stylo est
relâché et l'état devient `DONE`. Vous détenez actuellement le stylo en tant que
`claude` (depuis l'Étape 13), donc vous pouvez clôturer directement :

```bash
./m8shift.py claim claude
./m8shift.py done claude
```

**Résultat attendu :**

```text
✓ pen taken by claude (expires 2026-06-24T16:22:19Z).
✓ session DONE.
```

Vérifiez l'état final :

```bash
./m8shift.py status
```

**Résultat attendu :**

```text
m8shift.py v3.9.0
── LOCK ───────────────────────────────
  holder   none
  state    DONE
  agents   claude,codex
  lang     en
  session  20260624T155219Z-16e3a02d
  turn     2
  since    2026-06-24T15:52:19Z  local 2026-06-24 17:52:19 CEST
  expires  -
  note     session closed by claude
── last turn: #2 by codex
```

Le relais est clôturé. `state` vaut `DONE` et `holder` vaut `none`. Plus aucun
tour n'est attendu. Vous pouvez supprimer le dossier d'essai quand vous le
souhaitez :

```bash
cd ..
rm -rf /tmp/m8shift-toy
```

Félicitations — vous avez exécuté un relais M8Shift complet de bout en bout.

---

## Ce que vous avez appris

- **Le stylo est un mutex coopératif.** Un seul agent le détient à la fois ;
  vous travaillez uniquement tant que vous le détenez.
- **Le bloc LOCK est l'unique source de vérité.** Ses champs `holder`, `state`,
  `agents`, `lang`, `session`, `turn`, `since`, `expires` et `note` vous disent à
  qui est le tour et dans quelle session de relais vous êtes.
- **La boucle de base est `status` → `wait --once` → `claim` → travail →
  `append`.** `claim` prend le stylo de manière exclusive ; `append` enregistre
  votre tour et passe la main.
- **L'alternance stricte est imposée.** claude → codex → claude…, un tour
  numéroté à la fois, et un tour clôturé est immuable.
- **Les états que vous avez vus :** `IDLE` (libre), `WORKING_CLAUDE` /
  `WORKING_CODEX` (quelqu'un travaille), `AWAITING_CLAUDE` / `AWAITING_CODEX`
  (en attente de cet agent), `DONE` (session clôturée).
- **Entretien :** `archive` garde `M8SHIFT.md` court ; `done` clôture le relais.

---

## Étapes suivantes

Maintenant que la mécanique a du sens, allez plus loin :

- **Guides pratiques (how-to)** — recettes orientées tâche (récupérer un verrou
  périmé avec `claim --force`, écrire un corps de tour avec `--body`, passer la
  main sans tour avec `release`, adopter M8Shift dans un projet existant).
  Voir les docs how-to à côté de ce fichier.
- **Référence** — le protocole complet et la référence des commandes :
  [`M8SHIFT.protocol.md`](../../M8SHIFT.protocol.md) pour le protocole, et le doc
  de référence pour chaque commande, flag, champ de verrou et état.
- **Lisez le protocole une fois.** Avant de lancer M8Shift avec de vrais agents,
  lisez `M8SHIFT.protocol.md` §0 (la boucle copier-coller) pour que chaque agent
  puisse fonctionner par lui-même.
