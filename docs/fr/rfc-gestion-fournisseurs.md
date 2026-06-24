# RFC — Gestion des fournisseurs

- **Statut :** RFC de compagnon futur, non implémentée
- **Périmètre :** registre d'adaptateurs optionnel pour outils et surfaces d'agents
- **Invariant du cœur :** M8Shift coordonne des agents ; il ne devient pas fournisseur de modèle

## 1. Problème

M8Shift est volontairement neutre vis-à-vis des fournisseurs. Le roster peut contenir
`claude`, `codex`, `gemini`, `vibe` ou toute autre identité d'agent coopératif, mais
le cœur ne sait pas lancer ces outils, quelles permissions ils demandent, quelle
commande est sûre, ni comment leurs sessions doivent être reprises.

Cette neutralité est saine, mais un runtime autonome ou semi-autonome a besoin d'une
façon standard de décrire :

- comment lancer un agent pour un tour ;
- quelles capacités sont attendues ;
- quel fichier d'ancrage il lit ;
- si la surface est interactive ou headless ;
- quelles variables d'environnement ou identifiants l'hôte doit fournir ;
- quelle politique de sécurité s'applique avant exécution.

## 2. Décision

La gestion des fournisseurs appartient à une couche compagnon optionnelle. Le cœur
stocke des noms de roster et applique le stylo. Un gestionnaire de fournisseurs
associe ces noms à des commandes hôte, capacités et politiques.

## 3. Objectifs

- Maintenir un registre déclaratif d'adaptateurs fournisseur.
- Supporter Claude, Codex, Gemini, Vibe, modèles locaux, surfaces navigateur/IDE et
  outils futurs sans modifier `m8shift.py`.
- Décrire des commandes sous forme de vecteurs argv, sans interpolation shell.
- Déclarer des capacités : `read_repo`, `write_repo`, `run_tests`, `network`,
  `image_generation`, `legal_review`, etc.
- Garder l'authentification hors du journal du dépôt.
- Permettre au compagnon runtime de choisir la bonne invocation pour un tour M8Shift.
- Rendre les différences fournisseurs visibles à l'humain avant le run.

## 4. Non-objectifs

- Aucun SDK fournisseur dans `m8shift.py`.
- Aucun token API, OAuth ou compte dans `M8SHIFT.md`.
- Aucun broker de modèles hébergé.
- Aucun choix automatique de fournisseur par scoring caché.
- Aucune garantie que la sortie d'un fournisseur est sûre ou correcte.
- Aucun contournement de `claim → travail → append`.

## 5. Modèle de registre

Un futur compagnon peut utiliser une configuration hôte gitignorée :

```toml
[[agents]]
name = "codex"
provider = "openai-codex"
mode = "headless"
anchor = "AGENTS.md"
argv = ["codex", "exec", "$M8SHIFT_PROMPT"]
capabilities = ["read_repo", "write_repo", "run_tests"]
permissions = "workspace-write"

[[agents]]
name = "gemini"
provider = "google-gemini"
mode = "interactive"
anchor = "GEMINI.md"
capabilities = ["read_repo", "review", "image_reasoning"]

[[agents]]
name = "vibe"
provider = "vibe"
mode = "interactive"
anchor = "AGENTS.md"
capabilities = ["read_repo", "write_repo"]
```

Ce fichier n'est pas un fichier de protocole cœur. C'est une configuration hôte/runtime.

## 6. Contrat d'adaptateur

Chaque adaptateur devrait répondre à :

| Question | Exemple |
|----------|---------|
| Comment démarre-t-on un tour ? | `["codex", "exec", "$M8SHIFT_PROMPT"]` |
| La surface est-elle headless ? | `headless`, `interactive`, `hybrid` |
| Quel ancrage est chargé ? | `AGENTS.md`, `CLAUDE.md`, `GEMINI.md` |
| Peut-il lancer des commandes shell ? | oui/non |
| Peut-il éditer les fichiers ? | oui/non |
| Peut-il être repris automatiquement ? | oui/non |
| Comment les identifiants sont-ils fournis ? | environnement hôte uniquement |

L'adaptateur démarre un tour. Il ne possède pas le relais.

## 7. Contrat de prompt

Le gestionnaire fournisseur peut construire un prompt depuis :

- `status --json` courant ;
- dernier `peek` ;
- résumé du protocole ;
- messages opérateur en attente ;
- contraintes de sécurité ;
- commande exacte à lancer d'abord, généralement `next <agent>`.

Le prompt ne doit pas demander à l'agent de contourner le relais. Les détails
spécifiques fournisseur appartiennent aux templates d'adaptateur, pas à `M8SHIFT.md`.

## 8. Identifiants et secrets

Les secrets restent dans l'hôte :

- variables d'environnement ;
- stores d'auth des CLI fournisseur ;
- trousseaux OS ;
- secrets CI ;
- sessions interactives approuvées par l'utilisateur.

Les fichiers M8Shift doivent rester commitables. Si un gestionnaire fournisseur écrit
un état runtime contenant des identifiants ou ids de session, il doit vivre hors des
fichiers suivis ou être gitignoré par défaut.

## 9. Déclarations de capacités

Les capacités sont indicatives mais utiles :

```text
read_repo
write_repo
run_tests
network
browser
image_generation
legal_review
long_context
fast_review
```

Un runtime peut avertir lorsqu'une tâche demande `run_tests` mais que le fournisseur
choisi ne le déclare pas. Le cœur ne doit jamais bloquer `claim` ou `append` sur ces
métadonnées.

## 10. Règles de sécurité

- Utiliser des tableaux argv, pas des chaînes shell.
- Afficher la commande effective avant le premier run.
- Ne pas passer de secrets dans les prompts.
- Ne pas auto-approuver les commandes destructrices.
- Exiger l'approbation humaine explicite pour publication, déploiement, paiements ou
  messages externes.
- Journaliser quel adaptateur a exécuté quel tour.

## 11. Critères d'acceptation

Une première implémentation est acceptable si :

- une identité de roster peut être associée à une commande fournisseur sans éditer
  `m8shift.py` ;
- des fournisseurs non connus peuvent être ajoutés par configuration ;
- des identifiants manquants échouent avec une erreur hôte claire ;
- les fichiers cœur restent sans secret ;
- les fournisseurs headless et interactifs sont distingués ;
- l'exécution d'adaptateur effectue toujours un tour M8Shift ;
- les tests couvrent le rendu de commande sans injection shell.

## 12. Relation au cœur

Le cœur ne connaît que des noms :

```text
agents: claude,codex,gemini,vibe
```

La gestion des fournisseurs explique ce que ces noms signifient pour l'hôte. Elle ne
change jamais la sémantique du verrou.

## 13. Questions ouvertes

- Le format de registre doit-il être TOML, JSON ou YAML ?
- Faut-il un registre intégré d'ancrages connus pour les outils courants ?
- Les templates d'adaptateur doivent-ils être versionnés indépendamment du cœur ?
- La gestion fournisseur doit-elle vivre dans le package du plan de contrôle runtime
  plutôt que dans ce dépôt ?
