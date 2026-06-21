# Manuel utilisateur — opérer le relais Cowork dans VS Code

> **Note Claude —** guide opérationnel : comment lancer concrètement un relais
> Claude ⇄ Codex depuis les extensions VS Code. Pour l'installation du kit
> (`cp cowork.py` + `init`) voir le [README](../README.md) ; pour le protocole
> lui-même, [`COWORK.protocol.md`](COWORK.protocol.md).

Dans VS Code, **les panneaux Claude et Codex *sont* les agents**. L'essentiel se
résume à deux gestes : leur donner la **bonne racine de projet** et **démarrer de
nouvelles conversations** après `init`.

---

## 0. Prérequis

- `cowork.py` déployé à la racine du projet, et `python3 cowork.py init` exécuté
  (génère `COWORK.md`, `COWORK.protocol.md`, `CLAUDE.md`, `AGENTS.md`).
- Les deux extensions installées dans VS Code : **Claude Code** et **Codex**.

---

## 1. Une fenêtre VS Code par dépôt

Les instructions imbriquées (`CLAUDE.md` / `AGENTS.md`) ne se chargent de façon
fiable que si la fenêtre est ouverte **exactement sur la racine du dépôt**. Une
fenêtre ouverte trop haut (ex. `/home/user/Documents/Code`) ne garantit pas le
chargement.

Pour **Example Project** :

1. `File → New Window`
2. `File → Open Folder…`
3. Ouvrir exactement :

   ```text
   /home/user/Documents/Code/Books and Journals/Example Project
   ```

Faire **une autre fenêtre** pour GSE, avec sa propre racine. Un dépôt = une fenêtre.

---

## 2. Après `cowork.py init`

Une session déjà ouverte n'a pas connaissance des ancrages fraîchement injectés.
Après avoir lancé `init` :

1. `Cmd+Shift+P`
2. `Developer: Reload Window`
3. Créer une **nouvelle conversation** dans chaque UI.

> **Pourquoi** : Codex charge `AGENTS.md` au démarrage d'un **nouveau thread** ;
> Claude charge `CLAUDE.md` au début de **chaque session**. *Ouvrir simplement un
> fichier ne recharge pas nécessairement les instructions.*
>
> Réf. : [Codex — AGENTS.md](https://developers.openai.com/codex/guides/agents-md) ·
> [Claude Code — memory](https://code.claude.com/docs/en/memory)

---

## 3. Ouvrir les deux UI

Dans la **même fenêtre** (ici Example Project) :

- ouvrir le panneau **Claude Code** (icône ✱) ;
- ouvrir le panneau **Codex** ;
- placer les panneaux côte à côte si souhaité ;
- pour **Codex** : utiliser le **mode Agent** (lecture, modification et exécution
  de commandes dans le dossier de travail —
  [doc extension Codex](https://developers.openai.com/codex/ide)) ;
- pour **Claude** : le mode normal demandera des validations ; le **mode
  auto-accept** permet un relais plus autonome.

---

## 4. Amorcer Claude en premier

Dans l'UI **Claude**, coller (en remplaçant `[MISSION]`) :

```text
Lis CLAUDE.md et COWORK.protocol.md.

Tu es l'agent claude du relais Cowork. Prends le stylo avant toute
modification et réalise cette mission :

[MISSION]

Après ton append vers codex, ne termine pas la boucle : attends de nouveau
ton tour avec `python3 cowork.py wait claude`, puis poursuis le protocole
jusqu'à DONE ou jusqu'à un blocage nécessitant mon intervention.
```

Attendre de voir apparaître dans son transcript :

```text
verrou pris par claude
```

---

## 5. Démarrer Codex

Dans une **nouvelle conversation Codex**, coller :

```text
Lis AGENTS.md et COWORK.protocol.md.

Tu es l'agent codex du relais Cowork. Lance
`python3 cowork.py wait codex`, puis prends le stylo lorsque ton tour arrive.
Traite le dernier ask, repasse la main à claude, puis continue d'attendre.
Ne modifie jamais le dépôt sans claim réussi. Continue jusqu'à DONE ou blocage.
```

Le mode Agent de l'extension permet à Codex de lire, modifier et exécuter les
commandes dans le dossier de travail.

---

## Limite & dépannage

- **Une conversation UI déjà terminée ne se réveille pas** toute seule à une
  modification de `COWORK.md`. C'est pourquoi on demande explicitement aux deux
  agents de **rester dans la boucle** avec `wait` (étapes 4 et 5).
- **Si un panneau s'arrête** malgré tout, lui renvoyer simplement :

  ```text
  Reprends la boucle Cowork depuis `python3 cowork.py status`.
  ```

- **Vérifier à tout moment** l'état du relais, dans un terminal à la racine :
  `python3 cowork.py status` (qui tient le stylo, dernier tour, verrou périmé).
