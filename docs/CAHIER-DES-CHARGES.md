# Cahier des charges — cowork

> **Note Claude —** spécification rédigée et maintenue par Claude ; source de
> vérité du comportement attendu, alignée sur `cowork.py` et la suite `tests/`.

> **Statut** : `Validé` · **Version** : protocole v1 · **Dernière revue** : 2026-06-21

---

## 1. Objet

`cowork` permet à **deux agents IA** (Claude et Codex) de travailler sur un même
dépôt **sans se marcher dessus**, en se coordonnant via un **unique fichier
partagé** `COWORK.md`, en alternance stricte (mutex coopératif). Le système doit
être **portable sur tout projet** et **utilisable par les agents sans
intervention ni explication humaine**.

## 2. Périmètre

| Inclus | Exclu |
|--------|-------|
| Verrou mono-fichier, journal de tours, CLI de pilotage | Orchestration réseau / multi-machines |
| Auto-installation idempotente (`init`) dans tout projet | Plus de deux agents simultanés |
| Anti-blocage par TTL, archivage borné | Daemon résident, file d'attente persistante |
| Ancrages `CLAUDE.md` / `AGENTS.md` | Authentification / chiffrement du fichier d'état |

## 3. Acteurs

| Acteur | Rôle |
|--------|------|
| **claude** | Agent IA, lit `CLAUDE.md`, opère le relais côté Claude |
| **codex** | Agent IA, lit `AGENTS.md`, opère le relais côté Codex |
| **mainteneur** | Humain ; déploie le kit, arbitre, lit le journal |

## 4. Exigences fonctionnelles

| ID | Exigence | Vérifié par |
|----|----------|-------------|
| EF-1 | **`claim` obligatoire et exclusif avant de travailler** : il acquiert `WORKING_<soi>` depuis `IDLE`/`AWAITING_<soi>` ; deux `claim` simultanés (claude/codex) ⇒ un seul réussit, l'autre est exclu. | `test_claim_exclusive_sequential`, `test_concurrent_claim_claude_vs_codex_single_winner` |
| EF-1b | `append` n'est accepté **que depuis `WORKING_<soi>`** (donc après `claim`) → garantit l'exclusivité de la **fenêtre de travail** dans le dépôt, pas seulement du journal. | `test_append_requires_claim_from_idle`, `test_append_requires_claim_from_awaiting` |
| EF-2 | `append` écrit le tour suivant **et** repasse la main (`AWAITING_<autre>`) en une opération atomique ; `turn` est incrémenté. | `test_handoff_increments_and_alternates` |
| EF-3 | Un tour clôturé (`END`) est immuable (par convention : l'outil ne le réécrit jamais). | (revue) |
| EF-4 | `--to` doit viser l'autre agent (auto-passation interdite). | `test_self_handoff_refused` |
| EF-5 | `wait <agent>` attend le tour de l'agent ; `--once` ne fait qu'un contrôle (rc 0 = son tour, rc 3 sinon). | `test_wait_once_return_codes` |
| EF-6 | `claim --force` ne reprend **qu'un verrou périmé** ; refusé sur un verrou actif. | `test_force_refused_on_fresh_lock`, `test_force_accepted_on_stale_lock` |
| EF-7 | Le détenteur peut reprendre son propre verrou (rafraîchir le TTL). | `test_reclaim_own_lock_refreshes` |
| EF-8 | `release` / `done` n'agissent que si l'appelant tient le stylo (ou personne) ; `--force` outrepasse. | `test_release_done_require_holder`, `test_release_done_force_overrides` |
| EF-9 | `archive --keep N` purge les anciens tours clôturés sans jamais déplacer le tour d'amorçage `#0` ni toucher au verrou. | `test_archive_preserves_system_turn0` |
| EF-10 | `init` génère `COWORK.md`, `COWORK.protocol.md` et injecte les ancrages ; idempotent (stanza non dupliquée, contenu existant préservé, `COWORK.md` non écrasé sauf `--force`). | `test_reinit_idempotent_preserves_content`, `test_init_force_resets_lock` |
| EF-11 | Détection des ancrages insensible à la casse (`claude.md` réutilisé, pas de doublon). | `test_anchor_case_insensitive_no_duplicate` |

## 5. Exigences non fonctionnelles

| ID | Exigence |
|----|----------|
| ENF-1 **Portabilité** | Fonctionne sur dossier vide ou dépôt git, chemins à espaces/accents, FS sensible ou non à la casse. Python 3.8+, **stdlib uniquement**, aucun paquet tiers. |
| ENF-2 **Atomicité** | Toute écriture (y compris l'archive) passe par fichier temporaire **unique** + `os.replace`, en **préservant le mode** du fichier cible ; sérialisée par un verrou inter-process (`.cowork.lock`, `O_EXCL`, jeton d'ownership). |
| ENF-3 **Autonomie agents** | Toute la marche à suivre est embarquée : `COWORK.protocol.md` (§0 quickstart) + stanza des ancrages. Aucune explication humaine requise. |
| ENF-4 **Robustesse** | Entrées invalides (agent inconnu, `--body` absent, `COWORK.md` manquant, **LOCK au schéma invalide** : `state`/`turn`/`holder`) → sortie propre `sys.exit`, jamais de traceback, jamais d'état corrompu. |
| ENF-5 **Tenue dans le temps** | `COWORK.md` reste borné via `archive` ; l'archive n'est jamais relue par la boucle. |
| ENF-6 **Lisibilité** | État et tours lisibles à l'œil et au `grep` ; marqueurs en commentaires HTML invisibles au rendu Markdown ; versionnable en clair. |

## 6. Modèle de données — le bloc `LOCK`

En tête de `COWORK.md`, entre `<!-- COWORK:LOCK:BEGIN -->` et `:END` :

| champ | type | valeurs |
|-------|------|---------|
| `holder` | enum | `claude` \| `codex` \| `none` |
| `state` | enum | `IDLE` \| `WORKING_CLAUDE` \| `WORKING_CODEX` \| `AWAITING_CLAUDE` \| `AWAITING_CODEX` \| `DONE` |
| `turn` | entier | numéro du dernier tour clôturé |
| `since` | ISO-8601 UTC | depuis quand l'état dure |
| `expires` | ISO-8601 UTC \| `-` | TTL anti-blocage ; date **seulement** pendant `WORKING_*` |
| `note` | texte | mémo lisible |

**Machine à états** (transitions légitimes) :

```text
IDLE ──claim X──▶ WORKING_X ──append──▶ AWAITING_Y ──claim Y──▶ WORKING_Y …
  └──────────────────────────────────────────────────────────────▶ DONE (done)
WORKING_X(périmé) ──claim Y --force──▶ WORKING_Y
```

## 7. Interface en ligne de commande

`init` · `status` · `wait <agent> [--once] [--interval N]` · `claim <agent> [--force]` ·
`append <agent> --to <autre> --ask … --done … [--files …] [--body f|-]` ·
`release <agent> --to <autre> [--force]` · `done <agent> [--force]` · `archive [--keep N]`

Codes retour : `0` succès · `1` refus/erreur (état, garde-fou, entrée invalide) ·
`2` usage argparse · `3` `wait --once` quand ce n'est pas le tour de l'agent.

## 8. Contraintes & limites connues

- **Exclusivité de la fenêtre de travail** : garantie par `claim` (acquisition
  exclusive de `WORKING_<soi>`) + `append` restreint à `WORKING_<soi>`. Repose sur
  la **discipline** claim→travail→append ; cowork ne peut pas verrouiller le
  système de fichiers, donc un agent qui édite le dépôt **sans** avoir claim n'est
  pas empêché par l'outil (mais ne pourra pas `append`).
- **Mutex coopératif, non applicatif** : un agent malveillant peut, avec `--force`,
  outrepasser `release`/`done`. Le modèle suppose deux agents coopératifs.
- **Concurrence sérialisée par verrou conseillé** : `.cowork.lock` (`O_CREAT|O_EXCL`,
  jeton d'ownership) sérialise le read-modify-write + écriture atomique. Verrou
  *conseillé* : une édition manuelle de `COWORK.md` le contourne ; sur FS réseau
  (NFS) `O_EXCL`/`rename` sont moins fiables (cowork vise un disque local).
- **Immutabilité par convention** : l'outil ne réécrit jamais un tour clôturé,
  mais rien au niveau du système de fichiers ne l'empêche (édition manuelle).
- **Deux agents** : le protocole est binaire (claude ⇄ codex) par conception.

## 9. Recette / validation

- Suite `tests/test_cowork.py` : **39 tests** (unitaires + non-régression : modèle
  claim, mutex, concurrence claude/codex, archive, robustesse, anti-injection),
  `python3 -m unittest discover -s tests`, sans dépendance externe.
- Vérification adversariale multi-agents + 3 revues Codex successives, chaque
  constat reproduit puis corrigé puis re-testé.
- Test de non-régression documentaire : `docs/COWORK.protocol.md` doit rester
  byte-identique à `cowork.PROTOCOL_TEMPLATE` (`test_protocol_doc_in_sync`).

## 10. Versionnement

Protocole **v1**. Tout changement du format `LOCK`/`TURN` ou des marqueurs
incrémente la version du protocole et doit préserver la lecture des `COWORK.md`
existants ou fournir une migration.
