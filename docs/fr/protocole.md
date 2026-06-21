# COWORK · Protocole de relais mono-fichier (v1)

Instruction commune aux **deux agents actifs** (par défaut **Claude** et **Codex**)
pour coopérer via un seul fichier
`COWORK.md`, en alternance stricte (mutex), avec poll périodique. Portable : ce
protocole est identique dans tout projet ; seul le titre de `COWORK.md` change.

À lire **une fois en début de session** dès que tu vois un `COWORK.md` à la
racine d'un projet. Tu es **l'un des deux agents actifs** déclarés dans le champ
`agents:` de `COWORK.md` (par défaut `claude` et `codex`) — identifie-toi par ton
fichier d'ancrage.

---

## 0. TL;DR — opère sans aide humaine

Tu viens d'arriver dans le projet et tu vois un `COWORK.md` : voici la boucle
complète, copiable, **aucune autre instruction n'est nécessaire**. `<toi>` est ton
propre nom d'agent et `<autre>` l'autre agent actif (le couple déclaré dans
`agents:` ; par défaut `claude` / `codex`, via les ancrages `CLAUDE.md` / `AGENTS.md`).

```bash
# 1. Suis-je attendu ? (commandes NON bloquantes)
./cowork.py status                 # lis le champ `state`
./cowork.py wait <toi> --once      # rc 0 = tu peux acquérir ; rc 3 = pas encore

# 2. ACQUIERS le stylo AVANT de travailler (acquisition EXCLUSIVE : sur deux agents
#    qui tentent en même temps, un seul réussit) :
./cowork.py claim <toi>            # rc 0 = tu tiens le stylo ; rc != 0 = pas ton tour
#    • Si claim RÉUSSIT : lis le `ask:` que <autre> t'a laissé dans le dernier
#      tour (en démarrage IDLE/tour 0, rien à honorer), fais le travail dans le
#      dépôt, PUIS enregistre ton tour et passe la main :
./cowork.py append <toi> --to <autre> \
    --ask "ce que tu attends de l'autre" \
    --done "ce que tu viens de faire" \
    --files fichier1,fichier2
#    • Si claim ÉCHOUE : ce n'est pas (ou plus) ton tour → reviens à l'attente.

# 3. Pas ton tour : ne touche à RIEN. Bloque jusqu'à ton tour, puis reprends en 2 :
./cowork.py wait <toi>             # poll toutes les ~60 s (--interval N)
```

Règle d'or : **tu ne travailles et n'écris que si tu as acquis le stylo via
`claim`.** `claim` est exclusif ; `append` n'est accepté que si tu tiens le
stylo. Tout le reste de ce document n'est que le détail de cette boucle.

---

## 1. Modèle mental

- **Un seul fichier vivant** : `COWORK.md`. Tout le dialogue de travail y est.
- **Un seul stylo, acquis explicitement** : pour travailler, tu **prends** le
  stylo via `claim` → état `WORKING_<toi>`. `claim` est **exclusif** (deux agents
  qui tentent en même temps : un seul réussit). Tu ne modifies le dépôt **que**
  pendant que tu tiens le stylo.
- **`append` clôt ton tour** : il n'est accepté que depuis `WORKING_<toi>`, écrit
  le tour et passe la main (`AWAITING_<autre>`). Pas de `claim` ⇒ pas d'`append`.
- **Alternance stricte** : les deux agents actifs alternent (p. ex. `claude` →
  `codex` → `claude` …). Chaque passage de main est un *tour* (`TURN`) numéroté,
  encadré `BEGIN`/`END`.
- **Poll** : quand ce n'est pas ton tour, tu attends (`./cowork.py wait <toi>`,
  ~60 s) puis tu retentes `claim`.

---

## 2. Le bloc LOCK (le mutex)

Délimité par `<!-- COWORK:LOCK:BEGIN -->` … `<!-- COWORK:LOCK:END -->`.
Champs (un `clé: valeur` par ligne, faciles à `grep`) :

| champ     | valeurs | sens |
|-----------|---------|------|
| `holder`  | un agent actif \| `none` | qui tient le stylo (défaut `claude`/`codex`) |
| `state`   | `IDLE` \| `WORKING_<X>` \| `AWAITING_<X>` \| `DONE` | état courant (`<X>` = un agent actif, en majuscules) |
| `agents`  | CSV, ex. `claude,codex` | le couple du relais (les 2 premiers déclarés) ; défaut `claude,codex` |
| `turn`    | entier | numéro du dernier tour clôturé |
| `since`   | ISO-8601 UTC | depuis quand cet état dure |
| `expires` | ISO-8601 UTC \| `-` | échéance de reprise anti-blocage (TTL 30 min) |
| `note`    | texte court | mémo lisible |

> `expires` ne porte une date **que** pendant `WORKING_*` (un agent travaille,
> TTL 30 min). Il repasse à `-` dès qu'on attend (`AWAITING_*`, `IDLE`, `DONE`) :
> personne ne tient le stylo, donc pas de péremption à surveiller.

**Lecture des états** (`<X>` = un agent actif — par défaut `claude`/`codex`) :
- `AWAITING_<X>` → c'est à `<X>` de jouer (l'autre agent attend).
- `WORKING_<X>` → `<X>` tient le stylo et travaille (l'autre attend, ne touche à rien).
- `IDLE` → personne n'a la main, le premier qui a quelque chose à dire démarre.
- `DONE` → session close, plus de relais attendu.

---

## 3. Format d'un tour

```
<!-- COWORK:TURN <n> <agent> BEGIN -->
- from:    <agent>           # un agent actif
- to:      <agent|none>      # à qui tu repasses la main
- ask:     <ce que tu attends de l'autre, précis et actionnable>
- done:    <ce que tu viens de faire>
- files:   <fichiers touchés, séparés par des virgules>
- handoff: <agent|none>      # = to ; redondance volontaire, grep-friendly
<ligne vide>
<corps libre : explications, questions, blocs de code, listes>
<!-- COWORK:TURN <n> <agent> END -->
```

Règles :
- Un tour **clôturé** (`END` posé) est **immuable**. Pour réagir, tu ouvres le
  tour suivant. Jamais de réécriture rétroactive.
- `ask` doit être actionnable : l'autre agent doit pouvoir démarrer sans te
  reposer de question. Si tu n'attends rien (juste un FYI), mets `ask: —`.
- Garde un tour **borné** : si ça dépasse ~150 lignes ou plusieurs sujets,
  découpe en plusieurs tours successifs (un sujet = un tour).

---

## 4. Cycle de travail (la boucle de chaque agent)

```
boucle:
  1. lire LOCK (status / wait)
  2. si state == AWAITING_<moi> ou IDLE :
       a. CLAIM  : ./cowork.py claim <moi>   → state=WORKING_<MOI>, expires=now+30min
                   EXCLUSIF : si un autre a déjà pris le stylo entre-temps,
                   claim ÉCHOUE → va en 3.
       b. TRAVAILLER dans le dépôt (tant que tu tiens le stylo, toi seul)
       c. APPEND  : ./cowork.py append <moi> --to <autre>
                   écrit mon tour <turn+1>, state=AWAITING_<AUTRE>
  3. sinon (WORKING_<autre> ou AWAITING_<autre>) :
       attendre ~60 s (wait), retourner en 1
  4. si state == DONE : sortir
```

En pratique : `claim` **acquiert** le stylo (exclusif), `append` **clôt** ton tour
et passe la main, `wait` attend ton tour. L'acquisition explicite avant de
travailler est ce qui garantit qu'un seul agent modifie le dépôt à la fois.

> **Modèle de concurrence (deux niveaux)** :
> 1. **Transitions** sérialisées par un verrou inter-process (`.cowork.lock`,
>    `O_CREAT|O_EXCL`, à jeton de propriété) : chaque read-modify-write du LOCK +
>    écriture atomique (temporaire unique + `os.replace`) est exclusif.
> 2. **Fenêtre de travail** protégée par l'état persistant `WORKING_<agent>` :
>    `claim` est la seule acquisition, et il échoue si quelqu'un d'autre tient ou
>    a déjà pris le stylo. Deux `claim` simultanés depuis `IDLE` ⇒ **un seul
>    réussit** ; l'autre doit attendre. Comme on ne travaille qu'après un `claim`
>    réussi, deux agents ne modifient jamais le dépôt en même temps.
>
> Un `.cowork.lock` abandonné (process tué) est repris après 60 s, jeton vérifié.
> *Limites* : verrou **conseillé** (une édition manuelle de `COWORK.md` le
> contourne) ; sur FS réseau (NFS) `O_EXCL`/`rename` sont moins fiables — cowork
> vise un dépôt sur disque local. Voir aussi §0/§4 (claim obligatoire).

---

## 5. Anti-blocage (lock périmé)

Si l'autre agent crashe en tenant le stylo, le verrou resterait coincé. Garde-fou :
- au CLAIM, on pose `expires = now + 30 min` ;
- si tu vois `state == WORKING_<autre>` **et** `now > expires`, le verrou est
  **périmé** : reprends-le avec `./cowork.py claim <toi> --force`, puis ouvre un
  tour notant la reprise (`done: reprise après lock périmé de <autre>`) ;
- **l'outil applique la règle** : `--force` est **refusé** sur un verrou encore
  valide. Tu ne peux donc pas voler le stylo d'un agent actif (c'est voulu) ;
- tu peux **rafraîchir ton propre** verrou avant péremption : `./cowork.py claim
  <toi>` quand tu le détiens déjà repose `expires` à +30 min ;
- `release` et `done` n'agissent que si **tu** tiens le stylo (ou si personne ne
  le tient) ; `--force` outrepasse, réservé à la récupération.

---

## 6. Tenue dans le temps (longueur bornée)

`COWORK.md` ne doit pas gonfler indéfiniment :
- garde dans `COWORK.md` le bloc `LOCK` + les **~6 derniers tours** ;
- `./cowork.py archive --keep 6` déplace les tours plus anciens (déjà clôturés)
  vers `COWORK.archive.md` (append), sans jamais toucher au verrou ni au dernier
  tour ouvert.
- L'archive est consultable mais n'est **jamais** relue par la boucle : seule la
  partie vivante de `COWORK.md` pilote le relais.

---

## 7. Outil `cowork.py`

```
./cowork.py init [--name PROJET] [--agents a,b] [--lang en|fr] [--force]  # (re)génère le kit ici
./cowork.py status                                # verrou + dernier tour (NON bloquant)
./cowork.py wait <agent> [--once] [--interval N]  # attend ton tour ; --once = 1 check (rc 3 si pas ton tour)
./cowork.py claim <agent> [--force]               # ACQUIERS le stylo (exclusif) — depuis ton tour /
                                                  #   IDLE / ton propre verrou ; --force = verrou périmé SEULEMENT
./cowork.py append <agent> --to <autre> \
     --ask "..." --done "..." [--files a,b] [--body fichier.md|-]   # clôt ton tour + passe la main
./cowork.py release <agent> --to <autre> [--force]  # repasser la main sans corps (ne ré-incrémente PAS turn)
./cowork.py done <agent> [--force]                 # clore la session (state=DONE)
./cowork.py archive [--keep N]                     # purge les vieux tours clôturés (jamais le tour #0)
```

- **`claim` d'abord** : tu dois tenir le stylo (`WORKING_<toi>`) pour `append`.
  `claim` est **exclusif** (un seul gagnant si deux agents tentent ensemble).
- `append` n'est accepté **que depuis `WORKING_<toi>`** ; il écrit le tour et
  passe la main. `--body -` lit le corps depuis stdin ; `--body f.md` depuis un
  fichier ; sans `--body`, le tour n'a que l'en-tête.
- `--to` doit viser **l'autre** agent (auto-passation refusée : alternance stricte).
- Inspection **non bloquante** : `status` ou `wait <toi> --once`. `wait <toi>`
  **sans** `--once` bloque jusqu'à ton tour — ne l'utilise pas si tu dois rendre
  la main à ta boucle entre-temps.

---

## 8. Adoption par tout projet (portabilité)

`cowork.py` est **auto-suffisant** : il embarque ce protocole, le gabarit de
`COWORK.md` et les ancrages. Pour adopter le relais dans un projet :

```bash
cp /chemin/vers/cowork.py .      # copier le seul fichier nécessaire
./cowork.py init                 # nom du projet = nom du dossier (sinon --name)
```

`init` :
- écrit `COWORK.protocol.md` (ce document) et `COWORK.md` (verrou IDLE neuf) ;
  `COWORK.md` n'est **pas** écrasé s'il existe déjà (sauf `--force`) → l'état du
  relais en cours est préservé ;
- injecte en **tête** un bloc « Co-work relais » dans **l'ancrage de chaque agent
  actif** (par défaut `CLAUDE.md` et `AGENTS.md` ; créés s'ils manquent), entre
  marqueurs `COWORK:STANZA` → ré-injection **idempotente** (déplace/actualise le bloc
  sans dupliquer, contenu existant préservé ; le fichier précédent est sauvegardé dans
  `<ancrage>.cowork.bak`) ;
- si `CLAUDE.md` existait mais qu'aucune instruction Codex (`AGENTS.md` ou
  `AGENTS.override.md`) n'existait, crée automatiquement dans `AGENTS.md` un pont
  demandant à Codex de lire les instructions communes de `CLAUDE.md`. Un ancrage
  Codex préexistant n'est jamais complété ou remplacé automatiquement ;
- renomme une variante unique `claude.md`/`agents.md` vers le nom canonique
  auto-chargé, y compris sur un FS insensible à la casse. Plusieurs variantes
  coexistantes sont refusées plutôt que fusionnées silencieusement. Si Git est
  disponible et que la variante est suivie, emploie `git mv -f` pour actualiser
  aussi l'index ;
- si `AGENTS.override.md` existe, y synchronise aussi la stanza : Codex charge
  cet override à la place de `AGENTS.md` dans le même dossier.

### Amorçage / prise en compte par les agents

cowork est **passif** : il n'« appelle » aucune IA. Il s'appuie sur la convention de
chaque outil hôte — **Claude lit `CLAUDE.md`, Codex lit `AGENTS.md`**, et tout autre
agent actif lit son propre ancrage — au démarrage de session/exécution. La chaîne
d'amorçage est donc :

```
cowork.py init  ──▶  injecte la STANZA dans l'ancrage de chaque agent actif (CLAUDE.md, AGENTS.md, …)
                          │
   chaque IA charge son ancrage au démarrage ──▶ lit la stanza ──▶
   « si un COWORK.md existe, applique COWORK.protocol.md (claim → travail → append) »
```

- **Après `init`** : démarre une nouvelle session/exécution de l'agent. Une session
  déjà ouverte a généralement construit sa chaîne d'instructions avant l'injection.
- **Codex interactif ou `codex exec`** : `AGENTS.md` est chargé si la commande part
  de la racine du projet ou d'un de ses sous-dossiers. Le mode *headless* n'est pas
  en soi une limite ; un cron/CI lancé hors du projet, en revanche, ne découvre pas
  l'ancrage.
- **Override Codex** : `AGENTS.override.md` masque `AGENTS.md` dans un même dossier ;
  `init` injecte donc la stanza dans les deux lorsqu'il est présent.
- **Taille Codex** : Codex empile les fichiers d'instructions jusqu'à un plafond
  *combiné* (`project_doc_max_bytes`, 32 Kio par défaut) et tronque le fichier qui
  dépasse au nombre d'octets restant. Mettre la stanza en tête la conserve donc en
  priorité (et un fichier plus proche du cwd prime) ; garde néanmoins les ancrages
  **légers**.
- **Limite générale** : cowork ne peut pas forcer une IA à lire quoi que ce soit.
  Sans racine/contexte projet, pointe explicitement l'agent vers
  `COWORK.protocol.md`.

Référence Codex : https://developers.openai.com/codex/guides/agents-md
