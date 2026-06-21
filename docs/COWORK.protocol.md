# COWORK · Protocole de relais mono-fichier (v1)

Instruction commune à **Claude** et **Codex** pour coopérer via un seul fichier
`COWORK.md`, en alternance stricte (mutex), avec poll périodique. Portable : ce
protocole est identique dans tout projet ; seul le titre de `COWORK.md` change.

À lire **une fois en début de session** dès que tu vois un `COWORK.md` à la
racine d'un projet. Tu es soit `claude`, soit `codex` — identifie-toi.

---

## 0. TL;DR — opère sans aide humaine

Tu viens d'arriver dans le projet et tu vois un `COWORK.md` : voici la boucle
complète, copiable, **aucune autre instruction n'est nécessaire**. `<toi>` vaut
`claude` ou `codex` (selon ton ancrage `CLAUDE.md` / `AGENTS.md`), `<autre>`
l'autre agent.

```bash
# 1. Suis-je attendu ? (commandes NON bloquantes)
./cowork.py status                 # lis le champ `state`
./cowork.py wait <toi> --once      # rc 0 = c'est à toi ; rc 3 = pas encore

# 2. Si c'est ton tour (state == AWAITING_<TOI> ou IDLE) : lis le `ask:` que
#    <autre> t'a laissé dans le dernier tour de COWORK.md — en IDLE / tour 0, il
#    n'y a pas d'`ask:` réel à honorer, tu démarres librement. Fais le travail
#    dans le dépôt, PUIS dépose ton tour et passe la main en une commande :
./cowork.py append <toi> --to <autre> \
    --ask "ce que tu attends de l'autre" \
    --done "ce que tu viens de faire" \
    --files fichier1,fichier2

# 3. Si ce n'est PAS ton tour : ne touche à rien d'autre. Soit tu fais autre
#    chose et reviendras, soit tu bloques jusqu'à ton tour :
./cowork.py wait <toi>             # poll toutes les ~60 s (--interval N)
```

Règle d'or : **tu n'écris dans le dépôt que si le verrou t'est attribué.** Tout
le reste de ce document n'est que le détail de cette boucle.

---

## 1. Modèle mental

- **Un seul fichier vivant** : `COWORK.md`. Tout le dialogue de travail y est.
- **Un seul stylo** : le bloc `LOCK` en tête dit qui le tient. Tu n'écris dans le
  fichier **que** si le verrou t'est attribué.
- **Alternance stricte** : claude → codex → claude → … Chaque passage de main
  est un *tour* (`TURN`) numéroté, encadré `BEGIN`/`END`.
- **Poll** : quand ce n'est pas ton tour, tu attends et tu relis `LOCK` toutes
  les **~60 s** (`./cowork.py wait <toi>`), jusqu'à ce que `state == AWAITING_<toi>`.

---

## 2. Le bloc LOCK (le mutex)

Délimité par `<!-- COWORK:LOCK:BEGIN -->` … `<!-- COWORK:LOCK:END -->`.
Champs (un `clé: valeur` par ligne, faciles à `grep`) :

| champ     | valeurs | sens |
|-----------|---------|------|
| `holder`  | `claude` \| `codex` \| `none` | qui tient le stylo |
| `state`   | `IDLE` \| `WORKING_CLAUDE` \| `WORKING_CODEX` \| `AWAITING_CLAUDE` \| `AWAITING_CODEX` \| `DONE` | état courant |
| `turn`    | entier | numéro du dernier tour clôturé |
| `since`   | ISO-8601 UTC | depuis quand cet état dure |
| `expires` | ISO-8601 UTC \| `-` | échéance de reprise anti-blocage (TTL 30 min) |
| `note`    | texte court | mémo lisible |

> `expires` ne porte une date **que** pendant `WORKING_*` (un agent travaille,
> TTL 30 min). Il repasse à `-` dès qu'on attend (`AWAITING_*`, `IDLE`, `DONE`) :
> personne ne tient le stylo, donc pas de péremption à surveiller.

**Lecture des états :**
- `AWAITING_CLAUDE` → c'est à Claude de jouer (Codex attend).
- `WORKING_CODEX` → Codex tient le stylo et travaille (Claude attend, ne touche à rien).
- `IDLE` → personne n'a la main, le premier qui a quelque chose à dire démarre.
- `DONE` → session close, plus de relais attendu.

---

## 3. Format d'un tour

```
<!-- COWORK:TURN <n> <agent> BEGIN -->
- from:    <agent>           # claude | codex
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
  1. lire LOCK
  2. si state == AWAITING_<moi>  (ou IDLE et j'ai qqch à dire) :
       a. CLAIM  : holder=moi, state=WORKING_<MOI>, since=now, expires=now+30min
       b. (re-lire LOCK : confirmer que turn n'a pas bougé → sinon abandonner, conflit)
       c. TRAVAILLER (éditer le code/contenu hors COWORK.md)
       d. APPEND  : écrire mon tour <turn+1> BEGIN…END en bas du journal
       e. RELEASE : holder=<autre>, state=AWAITING_<AUTRE>, turn=<turn+1>, since=now
  3. sinon si state == WORKING_<autre> ou AWAITING_<autre> :
       attendre ~60 s, retourner en 1
  4. sinon si state == DONE :
       sortir
```

En pratique, `./cowork.py` fait CLAIM+APPEND+RELEASE en une commande atomique
(`append`), et la boucle d'attente (`wait`).

> **Modèle de concurrence** : les commandes qui mutent l'état prennent d'abord un
> **verrou inter-process** (`.cowork.lock`, créé en `O_CREAT|O_EXCL`), puis font
> le read-modify-write *à l'intérieur* de ce verrou et une écriture atomique
> (fichier temporaire unique + `os.replace`). Deux `cowork.py` concurrents sont
> donc **sérialisés** : le double-démarrage depuis `IDLE` est impossible (le 2ᵉ
> relit le LOCK et voit que ce n'est plus son tour). Un `.cowork.lock` abandonné
> (process tué) est récupéré après 60 s.
> *Limites* : le verrou est **conseillé** (une édition manuelle de `COWORK.md`
> hors outil le contourne) ; sur un FS réseau (NFS) les sémantiques `O_EXCL` /
> `rename` peuvent être plus faibles — cowork vise un dépôt sur disque local.

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
./cowork.py init [--name PROJET] [--force]        # (re)génère le kit dans CE dossier
./cowork.py status                                # verrou + dernier tour (NON bloquant)
./cowork.py wait <agent> [--once] [--interval N]  # attend ton tour ; --once = 1 check (rc 3 si pas ton tour)
./cowork.py claim <agent> [--force]               # prendre le verrou (ton tour / IDLE / ton propre verrou ;
                                                  #   --force = verrou périmé UNIQUEMENT)
./cowork.py append <agent> --to <autre> \
     --ask "..." --done "..." [--files a,b] [--body fichier.md|-]   # tour + passe la main
./cowork.py release <agent> --to <autre> [--force]  # repasser la main sans corps (ne ré-incrémente PAS turn)
./cowork.py done <agent> [--force]                 # clore la session (state=DONE)
./cowork.py archive [--keep N]                     # purge les vieux tours clôturés (jamais le tour #0)
```

- `append` est l'opération principale : elle ouvre le tour suivant **et** repasse
  la main en un seul geste. `--body -` lit le corps depuis stdin ; `--body f.md`
  depuis un fichier ; sans `--body`, le tour n'a que l'en-tête.
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
- injecte un bloc « Co-work relais » dans `CLAUDE.md` et `AGENTS.md` (créés s'ils
  manquent), entre marqueurs `COWORK:STANZA` → ré-injection **idempotente**
  (remplace le bloc existant au lieu de le dupliquer), le reste du fichier intact.
  La détection est **insensible à la casse** : un `claude.md`/`agents.md`
  préexistant est réutilisé tel quel (pas de doublon majuscule créé).

Claude lit `CLAUDE.md`, Codex lit `AGENTS.md` : les deux ancrages pointent vers ce
protocole, et chaque agent sait alors quoi faire en voyant un `COWORK.md`.
