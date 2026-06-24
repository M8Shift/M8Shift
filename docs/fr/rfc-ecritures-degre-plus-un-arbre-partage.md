# RFC — Écritures de degré > 1 dans un même working tree

- **Statut :** RFC de recherche ; rejetée pour le cœur actuel
- **Périmètre :** écritures concurrentes par plusieurs agents dans le même checkout
- **Invariant du cœur :** le cœur M8Shift livré reste degré 1

## 1. Problème

Après un roster à N agents, l'étape tentante est de laisser plusieurs agents écrire
dans le même working tree lorsque leurs fichiers ne se chevauchent pas. En théorie :

- Claude édite `docs/` ;
- Codex édite `src/parser.py` ;
- Gemini édite images ou prompts ;
- tous travaillent en concurrence dans le même checkout.

C'est du **vrai degré > 1** dans un working tree partagé. Ce n'est pas le modèle livré
par `m8shift-worktree.py`, qui isole chaque worker dans un worktree git séparé et
sérialise l'intégration.

## 2. Décision

Ne **pas** implémenter ceci dans le cœur M8Shift.

La réponse actuelle au travail parallèle est le compagnon worktree : arbres isolés,
commits indépendants, un stylo d'intégration sérialisé. Le degré > 1 dans un même
arbre reste un sujet de recherche et ne doit pas affaiblir la garantie cœur du stylo
unique.

## 3. Pourquoi c'est tentant

Bénéfices possibles :

- débit plus élevé pour des zones de fichiers indépendantes ;
- moins de worktrees à gérer ;
- modèle mental plus simple pour les utilisateurs qui n'aiment pas les branches ;
- un checkout visible pour tous les agents et l'humain.

Le coût est que le système de fichiers devient la surface de coordination. Un relais
mono-fichier passif ne peut pas l'appliquer de façon fiable.

## 4. Exigences dures pour toute expérimentation future

Un vrai système degré > 1 dans le même arbre exigerait tout ceci :

| Exigence | Pourquoi |
|----------|----------|
| Leases par chemin | chaque rédacteur possède des fichiers/plages explicites |
| Surveillance filesystem | détecter les edits hors chemins loués |
| Snapshots d'état sale | savoir ce qui a changé avant/après chaque rédacteur |
| Détection de conflit | attraper overlaps, fichiers générés, renames, deletes |
| Politique de merge | définir acceptation ou rollback des changements concurrents |
| Propriété des tests | savoir quelles vérifications valident quel lease |
| Override humain | résoudre les conflits ambigus ou politiques |
| Récupération crash | libérer ou mettre en quarantaine les leases abandonnés |

Ce n'est plus un petit mutex. C'est un orchestrateur local et un moniteur filesystem.

## 5. Risques

### 5.1 Chevauchement caché

Deux tâches peuvent toucher des fichiers différents et quand même entrer en conflit :

- code + documentation générée ;
- schéma + migration ;
- fichier package + lockfile ;
- rename + mise à jour d'import ;
- formatter qui touche tout l'arbre.

### 5.2 Comportement des outils

Les outils agents et formatters peuvent éditer hors périmètre prévu. Un script passif
ne peut pas empêcher cela.

### 5.3 Rollback ambigu

Si deux agents éditent le même checkout et que l'un crashe, revenir uniquement sur son
travail est difficile sauf si chaque écriture a été suivie au niveau filesystem.

### 5.4 Fausse sécurité

Un lease par chemin indicatif peut ressembler à de l'enforcement. Ce serait pire que
le modèle honnête actuel à stylo unique.

## 6. Design cœur rejeté : leases par chemin

Forme rejetée :

```text
claim codex --paths src/parser.py,tests/test_parser.py
claim gemini --paths assets/
```

Pourquoi rejeté pour le cœur :

- cela autorise plusieurs rédacteurs dans le même checkout ;
- cela force le cœur à raisonner sur chemins, globs, artefacts générés, deletes,
  renames et formatters ;
- cela transforme des métadonnées indicatives en autorité de routage ;
- cela casse la propriété « copier un fichier et fonctionner par discipline ».

## 7. Alternative acceptée : worktrees isolés

Le modèle accepté est déjà documenté dans
[rfc-worktree-companion.md](../en/rfc-worktree-companion.md) :

```text
checkout main          → intégration sérialisée seulement
worktree feat-a        → agent A travaille
worktree feat-b        → agent B travaille
worktree feat-c        → agent C travaille
```

Cela donne du vrai parallèle sans deux agents qui écrivent le même checkout au même moment.

## 8. Expérience future hors cœur possible

Un compagnon expérimental séparé pourrait tenter le degré > 1 dans le même arbre s'il
assume honnêtement être une autre surface produit.

Propriétés minimales :

- opt-in explicite `--experimental-shared-tree` ;
- leases par chemin stockés hors du `LOCK` cœur ;
- watcher filesystem ;
- snapshots avant/après ;
- quarantaine automatique sur écriture inattendue ;
- aucune interaction avec `claim` cœur hors passation d'intégration ;
- avertissements forts que ce n'est pas le modèle de sûreté par défaut.

## 9. Barre d'acceptation pour réexamen

Le sujet ne devrait pas être réexaminé pour le cœur sauf si un prototype prouve :

- les écritures inattendues sont détectées ;
- les formatters globaux sont gérés ;
- renames/deletes sont sûrs ;
- le rollback crash est fiable ;
- l'override humain est audité ;
- aucun lease par chemin ne contourne la provenance `append` ;
- les tests couvrent rédacteurs simultanés et récupération de conflits.

D'ici là, le cœur reste degré 1 et le compagnon worktree reste l'histoire de parallélisme.

## 10. Position finale

Cette RFC documente l'idée pour éviter de la redécouvrir en boucle. La décision actuelle :

- **cœur :** rejeté ;
- **compagnon :** utiliser les worktrees isolés ;
- **recherche :** possible seulement comme orchestrateur expérimental séparé.
