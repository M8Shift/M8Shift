# RFC — Intégrations Stage 6 : reste à faire et valeur ajoutée

- **Statut :** RFC de planification, non implémentée
- **Périmètre :** intégrations autour de M8Shift : distribution, surfaces IDE, MCP,
  runners headless, adaptateurs fournisseurs, notifications locales et éventuel plan
  de contrôle runtime/hébergé
- **Invariant cœur :** les intégrations ne remplacent pas le cœur passif mono-fichier ;
  `m8shift.py` reste l'autorité pour le `LOCK`, l'ordre des tours et le mutex à stylo
  unique

## 1. Objectif

Le Stage 6 est la couche d'intégration autour d'un relais déjà utilisable. La question
n'est plus « est-ce que M8Shift peut coordonner des agents ? » Il le peut. La question
devient :

> Quelles intégrations rendent M8Shift plus simple à adopter et plus sûr à exploiter
> sans le transformer en runtime d'agents hébergé ?

Cette RFC évalue les candidats Stage 6 restants, leur valeur ajoutée, leur risque et
l'ordre d'implémentation recommandé.

## 2. Baseline actuelle

Déjà livré ou disponible aujourd'hui :

- cœur `m8shift.py` : stylo unique, roster N-agent, passations dirigées, historique,
  mémoire, registre de tâches, doctor, `status --json`, `watch` et garde-fous de boucle ;
- `m8shift-worktree.py` : compagnon optionnel pour travail parallèle isolé en
  worktrees, avec intégration sérialisée ;
- `examples/headless_runner.py` : référence pour boucles headless et heartbeat ;
- documentation et site pour quickstart, usage type VS Code, Linux/macOS/Windows,
  boîte à outils worktree, limites, roadmap et sécurité ;
- RFCs pour compagnon runtime, plan de contrôle runtime/hébergé, gestion fournisseurs
  et recherche degré > 1 dans un même working tree.

Le Stage 6 doit donc se concentrer sur l'adoption, la visibilité opérateur et
l'intégration hôte, pas sur un changement du mutex cœur.

## 3. Synthèse de décision

| Candidat | Valeur | Effort | Risque | Décision |
|----------|--------|--------|--------|----------|
| Artefacts de release et recettes d'installation | Haute | Faible | Faible | À faire en premier |
| Améliorations UX locales status/watch | Haute | Faible | Faible | Continuer par incréments |
| Durcissement du runner headless | Haute | Moyen | Moyen | À faire ensuite |
| Registre fournisseurs | Haute | Moyen | Moyen | Après le contrat runner |
| Panneau IDE / intégration tâches | Moyenne | Moyen | Moyen | Intégration locale fine |
| Notifications locales | Moyenne | Faible/Moyen | Moyen | Seulement compagnon opt-in |
| Adaptateur MCP | Moyenne/Haute | Moyen | Haut | Conception prudente, lecture seule d'abord |
| Intégration orchestrateur | Moyenne | Moyen/Haut | Haut | Recettes/adaptateurs, pas le cœur |
| Plan de contrôle runtime/hébergé | Haute pour équipes | Haut | Haut | Différer après preuves locales |
| Distribution par paquet | Moyenne | Moyen | Moyen | Utile, mais `cp m8shift.py` reste prioritaire |
| Vrai degré > 1 dans le même working tree | Faible/Recherche | Haut | Haut | Rejeté pour le cœur |

## 4. Plan priorisé

### 6A — Artefacts de release et recettes d'installation

**Reste à faire :**

- releases taguées ;
- téléchargements directs de `m8shift.py`, `m8shift-i18n.py`, `m8shift-worktree.py` ;
- checksums ;
- snippets courts Linux, macOS, Windows ;
- recette « copier le cœur + la boîte à outils worktree » ;
- recette d'upgrade et contrôle d'écart de version.

**Valeur ajoutée :**

- réduit l'ambiguïté pour les nouveaux utilisateurs ;
- rend explicite le fichier que les agents doivent utiliser ;
- limite les setups cassés à cause d'un script obsolète copié depuis le dépôt.

**Frontière :**

- pas de daemon d'installation ;
- aucun gestionnaire de paquet requis pour l'usage normal ;
- les artefacts sont des copies de confort des scripts suivis.

### 6B — UX opérateur locale

**Reste à faire :**

- refléter `watch` dans la roadmap/site et la référence CLI si nécessaire ;
- fournir des layouts de terminal recommandés pour sessions multi-agents ;
- ajouter des alias shell exemples :

```bash
alias m8s='python3 m8shift.py status --for'
alias m8w='python3 m8shift.py watch --interval 5 --for'
```

**Valeur ajoutée :**

- réduit la boucle manuelle « c'est à qui ? » ;
- rend l'usage avec UI interactives moins fragile ;
- augmente la confiance sans changer la sémantique du relais.

**Frontière :**

- `watch` reste en lecture seule ;
- aucune notification ou récupération automatique dans le cœur.

### 6C — Durcissement du runner headless

**Reste à faire :**

- transformer `examples/headless_runner.py` en compagnon supporté ou recette documentée ;
- définir un format stable de run-plan ;
- enregistrer les run ids dans des champs consultatifs comme `x_run_id` ;
- améliorer les modes d'échec : claim sans append, heartbeat répété sans progrès,
  processus interrompu, lane obsolète ;
- ajouter des tests sans invoquer de vrais CLIs fournisseurs.

**Valeur ajoutée :**

- permet des boucles non assistées ou semi-assistées fiables ;
- réduit le besoin de relancer manuellement chaque UI d'agent ;
- prépare la gestion fournisseurs et les notifications locales.

**Frontière :**

- le runner appelle toujours `m8shift.py claim` et `append` ;
- aucune décision de routage cachée ;
- aucun secret fournisseur dans les fichiers M8Shift.

### 6D — Registre fournisseurs

**Reste à faire :**

- implémenter ou prototyper une config fournisseur gitignorée, comme spécifié par
  [rfc-gestion-fournisseurs.md](rfc-gestion-fournisseurs.md) ;
- mapper les identités du roster vers commandes et capacités ;
- distinguer surfaces `interactive`, `headless` et `hybrid` ;
- produire des commandes en tableaux argv, jamais en chaînes shell ;
- signaler clairement les credentials manquants et capacités non supportées.

**Valeur ajoutée :**

- rend `claude`, `codex`, `gemini`, `vibe` et autres noms opérationnellement
  compréhensibles par un runner hôte ;
- évite les hypothèses codées en dur sur les CLIs fournisseurs ;
- expose aux humains le modèle de capacités avant lancement.

**Frontière :**

- aucun SDK fournisseur dans `m8shift.py` ;
- pas de sélection automatique cachée de fournisseur ;
- la claimabilité cœur ne dépend jamais des métadonnées fournisseur.

### 6E — Panneau IDE / intégration tâches

**Reste à faire :**

- commencer par des recettes légères avant une extension complète :
  - tâches VS Code pour `status`, `watch`, `next`, `append --wait` ;
  - recommandations de layout terminal ;
  - problem matcher optionnel pour verrous périmés ;
- plus tard, une extension fine peut lire `status --json` et afficher détenteur
  courant / action suivante.

**Valeur ajoutée :**

- place l'état M8Shift là où l'utilisateur pilote déjà les agents ;
- réduit l'écart entre processus terminal en attente et UI de chat interactive ;
- aide à éviter le blocage « Claude est attendu, mais l'utilisateur parle à Codex ».

**Frontière :**

- l'intégration IDE affiche et guide ; elle ne contourne pas les commandes cœur ;
- l'état d'extension ne devient jamais une deuxième source de vérité.

### 6F — Notifications locales

**Reste à faire :**

- commande compagnon optionnelle qui observe `status --json` ;
- notification sur :
  - « tu es attendu » ;
  - `WORKING_*` périmé ;
  - heartbeat répété sans append ;
  - demande de transfert coopératif si cette RFC est livrée ;
- backends spécifiques OS gardés optionnels.

**Valeur ajoutée :**

- utile pour un humain qui supervise plusieurs panneaux d'agents ;
- réduit les passations manquées.

**Frontière :**

- notification signifie « regarde ceci », pas « l'agent a été réveillé » ;
- aucun auto-claim ou auto-force.

### 6G — Adaptateur MCP

**Reste à faire :**

- outils MCP read-only d'abord :
  - `status` ;
  - `history` ;
  - `peek` ;
  - `task list` ;
  - snapshots type `watch` si l'hôte le supporte ;
- outils mutateurs plus tard seulement s'ils exposent les mêmes commandes explicites :
  - `claim` ;
  - `append` ;
  - `release` ;
  - `done` ;
  - `task add/done/drop` ;
- exigences d'approbation claires pour toute action mutante.

**Valeur ajoutée :**

- permet aux agents hôtes d'inspecter l'état du relais via un outil structuré plutôt
  que par parsing shell ;
- réduit la dérive de prompt et les erreurs de commande manuelle.

**Frontière :**

- MCP ne doit pas interpréter le contenu des tours pour router le travail ;
- aucun outil ne doit écrire silencieusement le dépôt ;
- les outils mutateurs conservent exactement la sémantique et l'auditabilité M8Shift.

### 6H — Intégration orchestrateur

**Reste à faire :**

- recettes d'usage depuis orchestrateurs externes ;
- contrat strict : un tour M8Shift en entrée, un tour M8Shift en sortie ;
- vérification post-run avec `status --json` ;
- pas de merge/deploy/publish automatique sans approbation hôte.

**Valeur ajoutée :**

- permet à M8Shift de compléter les runtimes d'agents complets sans les concurrencer ;
- garde la propriété du dépôt explicite même lorsqu'un runtime lance les agents.

**Frontière :**

- le routage orchestrateur ne remplace pas le bâton cœur ;
- M8Shift reste la couche de coordination au niveau dépôt.

### 6I — Plan de contrôle runtime/hébergé

**Reste à faire :**

- implémenter seulement après preuve d'utilité des compagnons locaux ;
- définir rétention sidecar, auth, audit, propriété de lane et notifications ;
- décider si cela appartient à ce dépôt ou à un projet/package séparé.

**Valeur ajoutée :**

- forte pour des équipes avec nombreuses sessions ou workflows headless longs ;
- permet dashboards, lanes, inbox opérateur et vues de progression persistantes.

**Frontière :**

- doit rester optionnel ;
- supprimer les sidecars runtime doit laisser le relais cœur utilisable ;
- jamais de secrets fournisseur dans `M8SHIFT.md`.

## 5. Ordre recommandé

1. **Discipline release/install** : artefacts, checksums, recettes copy/upgrade.
2. **Sync site/docs** : exposer clairement `watch`, l'état Stage 4 et les limites Stage 6.
3. **Durcissement runner headless** : contrat local stable et gestion d'échec.
4. **Prototype registre fournisseurs** : mapper les noms du roster vers argv sûrs.
5. **Recettes IDE/tâches** : pas besoin d'extension au début ; tâches et terminaux d'abord.
6. **Adaptateur MCP read-only** : inspection structurée avant mutation.
7. **Notifications locales optionnelles** : compagnon uniquement, aucune garantie de réveil.
8. **Plan de contrôle runtime/hébergé** : différer jusqu'à retours d'usage locaux.

## 6. Non-objectifs

Le Stage 6 ne doit pas introduire :

- credentials fournisseur dans les fichiers cœur ;
- daemon obligatoire ;
- service hébergé obligatoire ;
- courtage modèle/fournisseur dans `m8shift.py` ;
- sélection automatique cachée d'agent ;
- écriture filesystem automatique sans `claim` réussi ;
- auto-force d'un `WORKING_*` encore valide ;
- distribution par paquet qui rende `cp m8shift.py` secondaire.

## 7. Critères d'acceptation

Le Stage 6 est sain lorsque :

- un nouvel utilisateur peut installer ou copier les bons scripts sans lire l'arbre source ;
- un opérateur peut surveiller le relais sans relancer `status` en boucle ;
- un run headless peut exécuter un tour et prouver qu'il n'a pas contourné le bâton ;
- un registre fournisseur peut lancer ou décrire des agents sans modifier `m8shift.py` ;
- une intégration IDE ou MCP peut inspecter l'état sans créer une deuxième autorité ;
- toute action mutante d'intégration est auditable comme une commande M8Shift normale ;
- le cœur fonctionne toujours offline, avec la stdlib Python, en un seul fichier.

## 8. Relation avec les RFC existantes

Cette RFC est un chapeau Stage 6. Elle ne remplace pas :

- [rfc-plan-controle-runtime-heberge.md](rfc-plan-controle-runtime-heberge.md) :
  frontière du plan de contrôle runtime/hébergé ;
- [rfc-gestion-fournisseurs.md](rfc-gestion-fournisseurs.md) : registre d'adaptateurs
  fournisseurs ;
- [rfc-demande-reprise-cooperative.md](rfc-demande-reprise-cooperative.md) :
  négociation coopérative du bâton contre les blocages d'UI interactives ;
- les RFC anglaises non encore traduites autour du compagnon runtime local.

Le Stage 6 doit avancer par incréments, en commençant par les améliorations locales
faibles risques avant toute surface hébergée ou exécutant réellement des fournisseurs.
