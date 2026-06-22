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
cp cowork.py /ton/projet/
cd /ton/projet
python3 cowork.py init
python3 cowork.py status
```

WSL fournit un vrai système de fichiers POSIX (vrai `O_EXCL`, `chmod`, `rename`
atomique) : le comportement est identique à Linux.

## Option B — Git Bash

Installe **Git pour Windows** (fournit Git Bash + git). Dans Git Bash :

```bash
cd /c/Users/toi/projet
python cowork.py init        # utilise `python`, pas ./cowork.py
python cowork.py status
```

- Appelle le script via `python cowork.py <cmd>` — Git Bash peut ne pas honorer le
  shebang `#!/usr/bin/env python3` de façon fiable.
- `git mv` (canonisation des ancrages) fonctionne car git est présent.

## Option C — PowerShell / cmd natif

```powershell
python cowork.py init
python cowork.py claim claude
python cowork.py append claude --to codex --ask "..." --done "..."
```

- Invoque toujours via `python cowork.py <cmd>` — `./cowork.py` est un idiome Unix et
  ne s'exécute pas directement.
- Si `python` est introuvable, utilise le lanceur : `py cowork.py <cmd>`.

## Fins de ligne

M8Shift écrit `COWORK.md` en LF (`\n`) ; les marqueurs de tour/verrou sont des
commentaires HTML et le parseur tolère les sauts de ligne, donc CRLF ne casse pas la
détection. Si tu committes `cowork.py` depuis Windows, garde du LF (`* text=auto
eol=lf` dans `.gitattributes`, ou `git config core.autocrlf input`). Dans *ce* dépôt source, `COWORK.md` est gitignoré, donc ses fins de ligne
n'atteignent jamais un commit ; un projet qui copie simplement `cowork.py` devrait
ajouter `COWORK.md` à son propre `.gitignore` (ou le garder en LF) pour éviter le bruit CRLF.

## Ce qui fonctionne à l'identique de Linux/macOS

Dossier vide ou dépôt git, chemins avec espaces/accents, le verrou inter-process
(`.cowork.lock`, `O_EXCL` + jeton de propriété), les écritures atomiques, la boucle de
relais complète (`wait → claim → travail → append`), le roster configurable
(`--agents`) et la sortie bilingue (`--lang en|fr`). La découverte / l'override de
`AGENTS.md` par Codex suivent les règles Windows propres à l'outil Codex.
