# Guide utilisateur — piloter le relais CoWork dans VS Code

> **Note Claude —** Guide opérationnel : comment lancer concrètement un relais
> Claude ⇄ Codex depuis les extensions VS Code. Pour l'installation du kit
> (`cp cowork.py` + `init`), voir le [README](../../README_fr.md) ; pour le
> protocole lui-même, voir [`COWORK.protocol.md`](../COWORK.protocol.md).

Dans VS Code, **les panneaux Claude et Codex *sont* les agents**. Tout le travail
se résume à deux gestes : les pointer vers la **bonne racine de projet**, et
**démarrer des conversations neuves** après `init`.

Ce guide est orienté tâches. Effectuez les étapes dans l'ordre ; chacune vous
indique ce que vous devez voir avant de passer à la suivante.

---

## Ce qu'il vous faut d'abord

- `cowork.py` déployé à la racine du projet, et `python3 cowork.py init` déjà
  exécuté (cela génère `COWORK.md`, `COWORK.protocol.md`, `CLAUDE.md` et
  `AGENTS.md`).
- Les deux extensions VS Code installées : **Claude Code** et **Codex**.

Si vous n'avez pas encore exécuté `init`, faites-le d'abord — voir le
[README](../../README_fr.md). Les étapes ci-dessous supposent que les quatre
fichiers existent.

---

## Étape 1 — Ouvrir une fenêtre VS Code par dépôt

Les fichiers d'instructions imbriqués (`CLAUDE.md` / `AGENTS.md`) ne se chargent
de façon fiable que lorsque la fenêtre est ouverte **exactement sur la racine du
dépôt**. Une fenêtre ouverte trop haut dans l'arborescence (par exemple
`/home/user/Documents/Code`) ne garantit **pas** leur chargement.

Pour ouvrir **Example Project** :

1. Choisissez `File → New Window`.
2. Choisissez `File → Open Folder…`.
3. Ouvrez exactement ce chemin :

   ```text
   /home/user/Documents/Code/example-workspace/Example Project
   ```

**Résultat attendu :** une fenêtre VS Code dont la racine est le dépôt lui-même,
avec `COWORK.md`, `CLAUDE.md` et `AGENTS.md` visibles au niveau supérieur de
l'Explorateur.

Ouvrez **une fenêtre distincte** pour chaque autre dépôt (par exemple GSE),
chacune sur sa propre racine. La règle est : un dépôt = une fenêtre.

> **Si `COWORK.md` n'est pas en haut de l'Explorateur, alors** vous avez ouvert
> un dossier parent. Fermez la fenêtre et rouvrez le dossier sur la racine exacte
> du dépôt.

---

## Étape 2 — Recharger après `cowork.py init`

Une session déjà ouverte ne sait rien des ancrages que `init` vient d'injecter.
Donc, juste après avoir exécuté `init` :

1. Appuyez sur `Cmd+Shift+P` pour ouvrir la palette de commandes.
2. Lancez `Developer: Reload Window`.
3. Démarrez une **nouvelle conversation** dans chaque interface (ne réutilisez
   pas un ancien fil).

**Résultat attendu :** les deux panneaux se rechargent, et la prochaine
conversation que vous ouvrez dans chacun lit son fichier d'ancrage à neuf.

> **Pourquoi c'est important :** Codex charge `AGENTS.md` au démarrage d'un
> **nouveau thread** ; Claude charge `CLAUDE.md` au début de **chaque session**.
> *Le simple fait d'ouvrir un fichier ne recharge pas nécessairement les
> instructions.*
>
> Réfs : [Codex — AGENTS.md](https://developers.openai.com/codex/guides/agents-md) ·
> [Claude Code — memory](https://code.claude.com/docs/en/memory)

---

## Étape 3 — Ouvrir les deux interfaces dans la même fenêtre

Travaillez dans la **même fenêtre** (ici, Example Project) :

1. Ouvrez le panneau **Claude Code** (l'icône ✱).
2. Ouvrez le panneau **Codex**.
3. Placez les panneaux côte à côte si vous le souhaitez.
4. Pour **Codex**, utilisez le **mode Agent** afin qu'il puisse lire, modifier et
   exécuter des commandes dans la fenêtre de travail
   ([documentation de l'extension IDE Codex](https://developers.openai.com/codex/ide)).
5. Pour **Claude**, le mode normal vous demandera d'approuver les actions ; le
   **mode auto-accept** laisse le relais s'exécuter de façon plus autonome.

**Résultat attendu :** deux panneaux actifs dans une seule fenêtre, chacun prêt à
recevoir un prompt.

---

## Étape 4 — Amorcer Claude en premier

Dans l'interface **Claude**, collez le prompt ci-dessous, en remplaçant
`[MISSION]` par votre tâche réelle :

```text
Lis CLAUDE.md et COWORK.protocol.md.

Tu es l'agent claude du relais CoWork. Prends le stylo avant toute modification,
et réalise cette mission :

[MISSION]

Après ton append vers codex, ne termine pas la boucle : attends de nouveau ton
tour avec `python3 cowork.py wait claude`, puis continue à suivre le protocole
jusqu'à DONE, ou jusqu'à ce que tu rencontres un blocage qui nécessite mon
intervention.
```

**Résultat attendu :** Claude prend le stylo (le tour initial / l'amorçage), et
sa transcription affiche la ligne de confirmation de l'outil, qui dit :

```text
✓ verrou pris par claude (...)
```

C'est la sortie littérale de `cowork.py claim claude` : elle confirme que Claude
détient désormais le stylo et que l'état du verrou est `WORKING_CLAUDE`.

> **Si cette ligne de confirmation n'apparaît jamais, alors** Claude n'a pas
> acquis le stylo. Vérifiez `python3 cowork.py status` dans un terminal à la
> racine du dépôt pour voir le `holder`, le `state` et le `turn`, puis renvoyez
> le prompt ci-dessus.

---

## Étape 5 — Démarrer Codex

Dans une **nouvelle conversation Codex**, collez :

```text
Lis AGENTS.md et COWORK.protocol.md.

Tu es l'agent codex du relais CoWork. Lance `python3 cowork.py wait codex`,
puis prends le stylo quand ton tour arrive. Traite la dernière demande, repasse
la main à claude, puis continue à attendre. Ne modifie jamais le dépôt sans un
claim réussi. Continue jusqu'à DONE ou un blocage.
```

Le mode Agent de l'extension permet à Codex de lire, modifier et exécuter des
commandes dans la fenêtre de travail.

**Résultat attendu :** Codex se bloque sur `wait codex` jusqu'à ce que le tour
lui passe, puis prend le stylo (état `WORKING_CODEX`), traite la demande, repasse
la main à `claude`, et revient en attente. L'alternance stricte entre les deux
agents est désormais en marche.

> **Si Codex se met à modifier sans attendre, alors** il a sauté la séquence
> `wait`/`claim`. Arrêtez-le et renvoyez le prompt ci-dessus — il ne doit jamais
> toucher au dépôt sans un claim réussi.

---

## Limites et dépannage

- **Une conversation d'interface terminée ne se réveille pas toute seule** quand
  `COWORK.md` change. C'est exactement pour cela que les deux prompts (étapes 4
  et 5) demandent explicitement à chaque agent de **rester dans la boucle** avec
  `wait`.

- **Si un panneau s'arrête malgré tout**, envoyez-lui simplement :

  ```text
  Reprends la boucle CoWork à partir de `python3 cowork.py status`.
  ```

- **Vérifiez l'état du relais à tout moment** depuis un terminal à la racine du
  dépôt :

  ```text
  python3 cowork.py status
  ```

  C'est non bloquant et cela montre qui détient le stylo (`holder`), le dernier
  `turn`, et si le verrou est périmé (un verrou expiré laissé par un agent qui a
  planté alors qu'il détenait le stylo).

> **Si `status` affiche un verrou périmé, alors** le détenteur précédent ne l'a
> jamais relâché. Récupérez avec `python3 cowork.py claim <agent> --force`, qui
> ne réclame qu'un verrou expiré — il ne peut pas voler le stylo à un agent dont
> le verrou est encore valide.
