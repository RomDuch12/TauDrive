# Mise à jour du poste de production, et réglages

Le dossier `atelier` est un bac à sable ; c'est `dist/TauDrive` qui part
sur le poste de production. Ce document répond à la question qu'on se pose
juste avant de le copier : **qu'est-ce que je risque de perdre ?**

Réponse courte : **rien**, à une condition — que le poste reste sous le
même compte Windows.

---

## 1. Où vit ce que l'atelier accumule

Aucun de ces emplacements n'est **dans** le dossier du programme.

| Quoi | Où | Contenu type |
|---|---|---|
| **Bibliothèque de process** | `%LOCALAPPDATA%\Cielle\TauDrive\recettes.json` | les process réglées sur pièce |
| **Réglages du poste** | registre `HKCU\Software\Cielle\TauDrive` | dossiers, thème, couples, préréglages de code, coupon |
| **Dessins du poste** | `%USERPROFILE%\TauDrive\Bibliotheque` | la bibliothèque de dessins, rayons compris |
| **Vignettes** | `%USERPROFILE%\TauDrive\vignettes` | aperçus, reconstruits à la demande |
| **Onglets fermés** | `%USERPROFILE%\TauDrive\Onglets fermes` | archive par semaine (`26s34`) |
| *le programme* | *le dossier `TauDrive` copié* | *lui seul est remplacé* |

*Paramètres ▸ Où sont rangés mes réglages ?* affiche cette table avec les
chemins réels du poste.

---

## 2. La procédure

```
1. Fermer TauDrive sur le poste de production.
2. Remplacer le dossier TauDrive par le nouveau.
3. Relancer.
```

C'est tout. Process, dossiers, dessins et préréglages sont retrouvés au
lancement — ils n'ont pas bougé, seul le programme a changé.

> **Fermer d'abord.** Un `TauDrive.exe` en cours d'exécution verrouille
> son dossier : la copie échoue à moitié et laisse une installation
> mutilée. Une fenêtre d'explorateur ouverte **dans** le dossier suffit
> d'ailleurs à bloquer la suppression.

### Par prudence, avant de copier

*Paramètres ▸ Exporter les réglages…* range tout dans un fichier. Deux
minutes, et la question ne se pose plus. C'est aussi ce qu'on garde comme
sauvegarde : un disque finit toujours par tomber.

---

## 3. Les trois cas où il faut vraiment exporter

La mise à jour ne perd rien. Ces trois-là, si :

| Cas | Ce qui se passe |
|---|---|
| **changement de compte Windows** | le registre et `%USERPROFILE%` sont propres à chaque compte : le nouveau compte démarre vierge |
| **changement de machine** | idem, plus les dossiers réseau à revoir |
| **disque tombé** | rien à dire de plus |

### Exporter

*Paramètres ▸ Exporter les réglages…* produit un `.taudrive-reglages` —
un ZIP contenant :

```
reglages.json     les clés du registre, sauf les volatiles
recettes.json     la bibliothèque de process
montages.json     les gabarits de montage
codes.json        les préréglages de code
bibliotheque/     les dessins du poste, si on le demande
```

Une **note** libre l'accompagne — « poste production, avant mise à jour »
— et le nom du poste et la date y sont inscrits d'office.

Ce qui **ne voyage pas**, et pourquoi :

* `window/geometry`, `window/state` — une géométrie de fenêtre appartient
  à l'écran qui l'a vue. La rejouer sur un poste à un seul moniteur place
  la fenêtre hors champ, sans aucun moyen de la récupérer ;
* `session/open`, `recent/documents` — ils désignent des fichiers qui
  n'existent pas sur l'autre poste.

### Importer

*Paramètres ▸ Importer des réglages…* **montre d'abord** : date, poste
d'origine, note, liste des process, dossiers de l'origine, nombre de
dessins. On coche ensuite ce qu'on reprend.

| Case | Par défaut | Pourquoi |
|---|---|---|
| Reprendre les process | ✓ | c'est ce qu'on vient chercher |
| Comment : **reprendre** / ajouter seulement les nouvelles / remplacer tout | reprendre | on importe pour reprendre le poste de production : ses valeurs l'emportent sur celles de même nom, signalées dans la liste ; les autres s'ajoutent |
| Reprendre les réglages | ✓ | thème, couples, préréglages |
| Reprendre aussi les **dossiers** | ✗ | ce sont des chemins absolus : le partage d'un atelier n'est pas celui d'un autre |
| Reprendre les dessins | ✗ | seulement s'ils sont dans l'archive |

Un dessin de même nom n'est jamais écrasé : il reçoit un rang, comme à
l'ajout ordinaire.

Une archive écrite par une version **plus récente** de TauDrive est
refusée plutôt que mal lue.

Un fichier **nu** — `recettes.json`, `codes.json` ou `montages.json`
copié depuis le dossier de réglages de l'autre poste — passe par la
même entrée : *Importer des réglages* le reconnaît à son contenu et le
montre entrée par entrée avant de le reprendre.

### Porter seulement des préréglages

Trois process de laiton à donner au poste de production n'ont pas
besoin de l'archive complète. Chaque gestionnaire a ses boutons
*Importer…* / *Exporter…* :

| Où | Fichier | Contenu |
|---|---|---|
| *Process…* (Ctrl+M) | `<nom>.process.json` | toute la bibliothèque de process, telle qu'affichée |
| *Préréglages…* d'un code | `<nom>.codes.json` | tous les préréglages de code |

Le fichier est le JSON de la bibliothèque elle-même, daté et signé du
nom du poste : il se relit à la main en cas de doute. À l'import,
chaque entrée est **montrée et cochée** avant d'entrer, avec la mention
« remplace celle du poste » quand un nom est déjà pris — on décoche ce
qu'on tient à garder. Un fichier de process donné au gestionnaire de
codes est refusé en le disant.

---

## 4. Le défaut qui a motivé ce document

Le renommage de « recette » en « process » à l'écran a suivi jusque dans
le **nom du fichier** de bibliothèque : `recettes.json` est devenu
`recipes.json`. Les postes qui avaient une bibliothèque ne la trouvaient
plus et repartaient sur les process d'usine — **sans que rien ne
l'annonce**, puisqu'une bibliothèque absente est un cas parfaitement
normal au premier lancement.

Constaté sur ce poste : huit process, dont *Similicuir* et *Balayage
Pz0.1*, réglées à la main, devenues invisibles.

Trois corrections :

1. le nom canonique est **figé** à `recettes.json`, avec un commentaire
   qui dit pourquoi il ne suit pas l'habillage de l'interface ;
2. les anciens noms — `recipes.json`, `process.json` — sont **relus**, et
   la bibliothèque est réécrite sous le nom canonique au premier
   enregistrement. L'ancien fichier est **laissé en place** : on ne
   supprime pas les données de quelqu'un pour faire propre ;
3. un contrôle automatique vérifie les deux.

### Et un second, du même genre

`--autotest` créait son `QApplication` **sans identité Qt**.
`QStandardPaths` retombe alors sur le nom de l'exécutable : `python` en
source, `TauDrive` en figé — deux bibliothèques différentes selon la
façon de lancer, et aucune n'était celle de l'atelier.

L'autotest s'annonce désormais comme `Cielle / TauDrive-autotest` : il
exerce le vrai chemin de résolution, sous un nom qui ne peut pas entrer
en collision avec la bibliothèque de production.

---

## 5. Vérifier après coup

```bash
python outils/test_engrave.py
dist/TauDrive/TauDrive.exe --autotest
```

Et dans l'application, *Paramètres ▸ Où sont rangés mes réglages ?* :
les chemins affichés doivent être ceux du tableau §1, et le nombre de
process celui qu'on connaît.
