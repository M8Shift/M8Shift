# Guide — Lancer M8Shift sous Windows

M8Shift est **du Python 3.8+ pur, bibliothèque standard uniquement** — il n'y a **rien
à `pip install`**. Il tourne sous Windows de trois façons : WSL (le plus proche de
Linux/macOS), Git Bash, ou PowerShell/cmd natif.

## Prérequis

- **Python 3.8+** — installe depuis [python.org](https://www.python.org/downloads/)
  (coche *« Add python.exe to PATH »*), ou `winget install Python.Python.3.12`, ou le
  Microsoft Store. Vérifie : `python --version` (ou `py --version`).
- **Aucune dépendance** — M8Shift est stdlib-only, il n'y a rien d'autre à installer.
- *(Optionnel)* **Git pour Windows** — utile seulement pour le renommage de casse des
  ancrages via `git mv`. Sans lui, M8Shift fonctionne quand même (l'étape Git est
  sautée).

## Option A — WSL (recommandé : au plus proche de Linux/macOS)

```powershell
wsl --install            # une fois ; redémarrer si demandé
```

Puis, dans le shell WSL (Ubuntu, …) :

```bash
cd /ton/projet
curl -fsSL https://raw.githubusercontent.com/M8Shift/M8Shift/main/install.sh | bash -s -- --verify --agents claude,codex
python3 m8shift.py status
```

L'installateur télécharge `m8shift.py` et le compagnon optionnel
`m8shift-worktree.py`, les vérifie avec `checksums.sha256`, puis lance `init`.

WSL fournit un vrai système de fichiers POSIX (vrai `O_EXCL`, `chmod`, `rename`
atomique) : le comportement est identique à Linux.

## Option B — Git Bash

Installe **Git pour Windows** (fournit Git Bash + git). Dans Git Bash :

```bash
cd /c/Users/toi/projet
curl -fsSL https://raw.githubusercontent.com/M8Shift/M8Shift/main/install.sh | bash -s -- --verify --agents claude,codex
python m8shift.py status
```

- Appelle le script via `python m8shift.py <cmd>` — Git Bash peut ne pas honorer le
  shebang `#!/usr/bin/env python3` de façon fiable.
- `git mv` (canonisation des ancrages) fonctionne car git est présent.

## Option C — PowerShell / cmd natif

Dans PowerShell :

```powershell
irm https://raw.githubusercontent.com/M8Shift/M8Shift/main/install.ps1 | iex
python m8shift.py status
```

Depuis `cmd.exe` :

```bat
powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://raw.githubusercontent.com/M8Shift/M8Shift/main/install.ps1 | iex"
python m8shift.py status
```

L'installateur PowerShell télécharge `m8shift.py` et la boîte à outils optionnelle
`m8shift-worktree.py`, les vérifie par défaut avec `checksums.sha256`, puis lance `init`.

Alternative manuelle :

```powershell
python m8shift.py init
python m8shift.py claim claude
python m8shift.py append claude --to codex --ask "..." --done "..."
```

Si vous n'utilisez pas l'installateur, téléchargez ou copiez d'abord `m8shift.py`
dans le projet ; copiez [`m8shift-worktree.py`](../en/rfc-worktree-companion.md)
à côté seulement si vous utilisez les worktrees parallèles isolés.

`claude` et `codex` sont des noms de roster d'exemple. Remplacez-les par `gemini`,
`vibe` ou tout agent coopératif qui respecte le protocole du relais.

- Invoque toujours via `python m8shift.py <cmd>` — `./m8shift.py` est un idiome Unix et
  ne s'exécute pas directement.
- Si `python` est introuvable, utilise le lanceur : `py m8shift.py <cmd>`.

## Fins de ligne

M8Shift écrit `M8SHIFT.md` en LF (`\n`) ; les marqueurs de tour/verrou sont des
commentaires HTML et le parseur tolère les sauts de ligne, donc CRLF ne casse pas la
détection. Si tu committes `m8shift.py` depuis Windows, garde du LF (`* text=auto
eol=lf` dans `.gitattributes`, ou `git config core.autocrlf input`). Dans *ce* dépôt source, `M8SHIFT.md` est gitignoré, donc ses fins de ligne
n'atteignent jamais un commit ; un projet qui copie simplement `m8shift.py` devrait
ajouter `M8SHIFT.md` à son propre `.gitignore` (ou le garder en LF) pour éviter le bruit CRLF.

## Ce qui fonctionne à l'identique de Linux/macOS

Dossier vide ou dépôt git, chemins avec espaces/accents, le verrou inter-process
(`.m8shift.lock`, `O_EXCL` + jeton de propriété), les écritures atomiques, la boucle de
relais complète (`wait → claim → travail → append`) et le roster actif configurable
(`--agents`). Le cœur du dépôt est anglais uniquement (`--lang en`) ; les variantes
mono-fichier construites avec `m8shift-i18n.py` peuvent inclure d'autres choix
`--lang <code>`. La découverte / l'override de `AGENTS.md` par Codex suivent les règles
Windows propres à l'outil Codex.
