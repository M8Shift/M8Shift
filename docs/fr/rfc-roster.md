# RFC — Couple d'agents configurable (roster) pour CoWork

> **Statut** : `Implémenté (étape 1)` · **Livré dans** : v2.1 · **Auteur** : Claude (synthèse d'un panel de conception à 3 propositions) · **Date** : 2026-06-21
>
> L'étape 1 (couple configurable) est **implémentée** : `init --agents …`, le champ
> LOCK `agents:`, les états/validations conscients du roster, et l'injection d'ancrage
> par agent. Les questions ouvertes ci-dessous sont résolues en ligne. L'**étape 2**
> (N agents *simultanés*) reste à venir — voir [§10](#10-horizon-étape-2--n-agents-simultanés).

## 1. Résumé

Aujourd'hui CoWork câble en dur le couple **claude ⇄ codex**. Ce RFC généralise les
**participants** à un couple configurable tiré d'un **roster extensible**
(`claude`, `codex`, `lechat`, `gemini`, …) **sans changer le modèle de
concurrence** : il reste un **mutex de degré 1** (un stylo unique, alternance stricte
entre les deux agents choisis). C'est un *delta minimal* — le verrou, la sérialisation
`O_EXCL`, le bail TTL et le journal de tours restent intacts.

> Voir [architecture §1.8](architecture.md) — *un mutex, pas un sémaphore*. Ce RFC
> conserve le degré à 1 ; il élargit l'**alphabet** des noms d'agents, pas le nombre
> de détenteurs simultanés.

## 2. Objectifs / Non-objectifs

**Objectifs**
- Choisir *quels deux agents* font le relais, au moment du `init` : `cowork.py init --agents claude,lechat`.
- Par défaut (sans `--agents`) = `claude,codex` → **identique en comportement** (le
  `COWORK.md` généré gagne une ligne `agents:` et le tour d'amorçage nomme le couple
  actif ; les transitions du relais et l'injection d'ancrage sont inchangées).
- **Mapping d'ancrage** par agent pour que chaque outil charge automatiquement son propre fichier d'instructions.
- Gestion honnête des agents dont l'outil **ne charge automatiquement aucun fichier** (amorçage manuel).

**Non-objectifs (ce RFC)**
- **N agents travaillant simultanément** (degré > 1). C'est une étape distincte et plus large
  — voir [§10 Horizon étape 2](#10-horizon-étape-2--n-agents-simultanés).
- Politiques de routage (`--to any`, round-robin (tourniquet), files de travail). Reporté ; la passation
  reste **nommée** (`--to <l'autre>`), exactement comme le relais binaire.
- Découvrir le roster en scannant quels fichiers d'ancrage existent (trop implicite/fragile).

## 3. Vue d'ensemble de la conception

Le roster est **déclaré au `init`** et **stocké dans le bloc LOCK** (la seule
source de vérité, déjà lue par chaque commande). Un nouveau champ ; tout le reste est
une généralisation paramétrique de noms qui sont *déjà* par agent
(`WORKING_<X>` / `AWAITING_<X>`).

## 4. Roster & stockage

- CLI : `init --agents claude,codex,lechat` — ordonné, dédupliqué, normalisé en
  ASCII `[a-z][a-z0-9_-]*`, **au moins 2 membres**. Les **deux premiers** forment le
  couple actif ; tout nom supplémentaire est **stocké dans `agents:` mais inactif**
  jusqu'à l'étape 2 (*résolu* — voir §9 Q1).
- Stockage : une nouvelle ligne LOCK `agents:   claude,codex` (CSV), à côté de `lang`.
  Grep-able, versionnée, parsée par `get_lock` avec un simple `split(",")`.
- Lecture : `roster(lk)` → `lk["agents"].split(",")` si présent, sinon `("claude","codex")`
  (repli pour tout `COWORK.md` pré-RFC — **aucune migration requise**).
- `init` sans `--force` sur un `COWORK.md` existant **préserve** le roster en place
  (comme le reste du LOCK).

## 5. Mapping d'ancrage (le vrai nœud du problème)

Une table connue nom→ancrage, câblée en dur, avec un repli documenté :

```python
ANCHORS = {
    "claude":  "CLAUDE.md",
    "codex":   "AGENTS.md",        # + AGENTS.override.md
    "gemini":  "GEMINI.md",        # Gemini CLI auto-loads GEMINI.md
    "lechat":  "AGENTS.md",        # Le Chat / Mistral: AGENTS.md (au mieux) — see below
    # nested-path anchors (e.g. Copilot's .github/copilot-instructions.md) are out of
    # stage 1: ensure_canonical_anchor is not path-aware → manual-bootstrap fallback.
}
```

`init` itère sur le roster, résout le fichier de chaque agent et injecte la strophe
(idempotent — `ensure_canonical_anchor` + `inject_anchor` inchangés, simplement appelés par
agent).

Deux cas difficiles, gérés explicitement (pas silencieusement) :

1. **Collision d'ancrage.** Plusieurs outils « compatibles codex » (`codex`, `lechat`,
   `mistral`) chargent automatiquement `AGENTS.md`. On y injecte **une** strophe ; avec un roster
   qui partage un fichier, la strophe doit être **générique** (« tu es l'un des agents
   partageant ce fichier ; identifie-toi par ton outil hôte ») et lister les cibles
   `--to` valides. Limite honnête : un outil partageant `AGENTS.md` ne *sait* pas
   intrinsèquement quel nom de roster il est — l'identité d'agent reste une convention humaine/de lancement.
2. **Aucune convention de chargement automatique** (p. ex. Le Chat aujourd'hui, ou tout cron/CI lancé en dehors
   du projet, ou un outil sans mécanisme de doc projet). CoWork est **passif** : il
   peut fournir la strophe mais ne peut pas forcer une lecture. `init` écrit une ancre de
   repli au mieux et **affiche un avertissement** : *« agent `<X>` : aucune ancre auto-chargée connue
   — amorce-le manuellement en le pointant vers `COWORK.protocol.md`. »* L'
   agent reste un membre à part entière du roster (ses `claim`/`append` fonctionnent) ; seul l'amorçage automatique
   manque. **Ceci est documenté comme une limite assumée, pas un bug.**

## 6. Schéma LOCK & états

- Champs inchangés + `agents` (CSV). `holder ∈ roster ∪ {none}`.
- Les états restent **un par agent** — `WORKING_<X>` / `AWAITING_<X>` — calculés à partir du
  roster au lieu d'un tuple figé :

  ```python
  valid_states(roster) = {"IDLE", "DONE"} \
      ∪ {f"WORKING_{a.upper()}" for a in roster} \
      ∪ {f"AWAITING_{a.upper()}" for a in roster}
  ```

  `state.removeprefix("WORKING_").lower()` récupère l'agent. Pas de `queue`, pas de `next`,
  pas de broadcast — la prolongation stricte du modèle binaire. `holder` reste le
  détenteur **unique** du stylo.

## 7. Passation, CLI & invariant

- `append <self> --to <X>` : `X ∈ roster`, `X ≠ self`, accepté **uniquement depuis
  `WORKING_<self>`** (inchangé). Pose `holder=X`, `state=AWAITING_<X>`, `turn+1`.
  Avec le roster par défaut à 2 agents, `--to` ne peut nommer que l'autre → passation **inchangée**.
- `need_agent` valide contre le **roster courant** (lu depuis le LOCK), pas la
  constante du module ; l'erreur liste le roster effectif.
- `other(agent)` est conservé mais son rôle se réduit à la détection de verrou périmé dans
  `wait`/`claim`, généralisée à « dériver l'agent depuis `state` » plutôt que de supposer
  un unique homologue.
- Nouvelle surface CLI : juste `init --agents …`. `status` affiche en plus `agents: …`.
  Codes de retour inchangés.
- **Invariant (réénoncé) :** *à tout instant, au plus un agent du roster est en
  `WORKING_<X>` (⇔ `holder==X`) ; seul le détenteur modifie le dépôt ; chaque entrée dans
  `WORKING_<X>` requiert un `claim` réussi, et `claim` est exclusif sur l'ensemble du
  roster.* La preuve est **indépendante de la cardinalité du roster** : `state` est un scalaire
  unique, et `claim` ne réussit que depuis `IDLE`, `AWAITING_<self>`, son propre
  `WORKING_<self>` (rafraîchissement), ou `--force` sur un `WORKING_<other>` *périmé*. Ajouter
  des noms ne fait qu'agrandir l'ensemble des `<other>` ; cela ne crée aucune seconde route vers
  `WORKING`.

## 8. Rétrocompatibilité & migration

- `init` sans `--agents` → roster `claude,codex` ; tous les chemins de transition du
  relais sont inchangés. Le `COWORK.md` généré gagne en revanche une ligne `agents:`
  optionnelle (et le tour d'amorçage nomme le couple actif), donc le *fichier* n'est
  pas identique octet pour octet à la sortie pré-roster. Un script « roster-unaware »
  (pré-RFC) reste sûr **uniquement pour le couple par défaut** : il ignore `agents:`
  et traiterait un roster personnalisé comme `claude,codex`, ce qui peut le corrompre —
  un roster personnalisé exige un script conscient du roster.
- Un `COWORK.md` pré-RFC sans ligne `agents:` se charge via le repli `("claude","codex")`
  — pas de réécriture, pas d'outil de migration. `init --force` réécrit le LOCK et ajoute
  `agents:`.
- `other()` et `test_other` restent ; `stanza_for` conserve la formulation historique à 2 agents
  quand `len(roster)==2` (de sorte que `test_protocol_docs_in_sync` et `test_stanza_for` sont
  intacts). La strophe générique/plurielle ne s'active que pour un roster non par défaut.
- **Impact code** (petit, localisé) : helper `roster()` + normalisation `--agents` ;
  `valid_states(roster)` au lieu de la constante `VALID_STATES` ; `load_or_die`
  valide contre lui ; `need_agent` contre le roster ; `cmd_append` valide
  `--to ∈ roster` ; `cmd_init` boucle l'injection d'ancrage sur le roster via `ANCHORS` ;
  ligne `agents:` dans les templates LOCK `COWORK_*`. Intacts : `file_lock`, `write`
  atomique, `archive`, la mécanique TTL.

## 9. Questions ouvertes

1. **Taille du roster.** ✅ *Résolu.* `--agents` accepte **≥2 noms** ; les **deux
   premiers** font le relais dans cette version et tout nom supplémentaire est stocké
   (réservé à l'étape 2). On garde le relais binaire tout en laissant un projet
   déclarer son roster complet d'emblée.
2. **Préservation des champs `set_lock`.** ✅ *Résolu.* `agents` est transporté à
   travers chaque `lk.update(...)` (il vient de `get_lock`) ; verrouillé par
   `test_agents_field_survives_claim` (aller-retour get/set au fil d'un `claim`).
3. **Identité d'ancrage.** Quand plusieurs agents partagent `AGENTS.md`, comment chaque outil sait-il
   *quel* nom de roster il est ? Probablement insoluble purement dans le fichier → documenter la
   convention au moment du lancement.
4. **Synchro de la doc protocole.** ✅ *Résolu (étape 1) — implémenté.* La prose du
   protocole **et** la table des états du LOCK sont désormais **agnostiques au couple**
   (`WORKING_<X>`/`AWAITING_<X>`, « les deux agents actifs », `holder` générique) ; les
   indications de `init` et le tour d'amorçage interpolent le couple actif. Les
   templates `PROTOCOL_EN`/`PROTOCOL_FR` ont été généralisés et `docs/en/protocol.md` /
   `docs/fr/protocole.md` régénérés — le snapshot **a donc changé** (il n'est *pas*
   inchangé) et `test_protocol_docs_in_sync` a été re-référencé sur
   `cowork.PROTOCOL[lang]`. Le champ `agents:` reste un ajout **optionnel**
   rétrocompatible dans le protocole v1 (les anciens lecteurs l'ignorent).
5. **Ancrage `lechat`.** ✅ *Résolu (au mieux).* La convention n'est pas confirmée,
   donc `lechat`/`mistral` pointent vers `AGENTS.md` au mieux ; un agent sans ancrage
   connu (ou dont l'ancrage est déjà pris) déclenche un avertissement d'amorçage manuel
   plutôt que de bloquer `init`.

## 10. Horizon étape 2 — N agents *simultanés*

Une version **ultérieure** (l'« après-prochaine ») vise le **vrai multi-agent** : plus d'un
agent écrivant **en même temps**. C'est une autre bête — **degré > 1** — et
le mutex propre ne suffit plus :

- Cela devient un **sémaphore compteur** (k > 1 détenteurs) *ou* un ensemble de **sous-verrous
  partitionnés** (chaque agent possède une zone disjointe du dépôt).
- De nouveaux problèmes apparaissent que ce RFC évite délibérément : détection/fusion de conflits
  d'éditions concurrentes, partitionnement du dépôt, interblocage entre plusieurs verrous, équité.
- Le roster de ce RFC en est le substrat naturel, mais l'**invariant stylo unique
  serait remplacé** par un invariant par partition ou compté.

L'étape 2 est **hors périmètre ici** et devrait avoir son propre RFC. Ce RFC conserve la
garantie forte et simple (un seul rédacteur) tout en rendant configurable *qui* sont les deux
rédacteurs.
