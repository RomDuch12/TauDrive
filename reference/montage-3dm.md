# Montage à DataMatrix

Un montage machine porte trois pièces à la fois. Chacune reçoit son
DataMatrix et sa référence en clair — six formes, trois sous-ensembles.

Le bouton de la barre d'outils (trois DataMatrix empilés, `Ctrl+Maj+B`)
les pose d'un coup, aux cotes du montage physique.

---

## 1. Les cotes vivent dans un gabarit

**Elles ne sont pas dans le programme.** Ce sont celles de la mécanique :
le jour où l'entraxe change, ce doit être une valeur à corriger, pas un
exécutable à reconstruire. Et le jour où un deuxième montage arrive, une
entrée à ajouter, pas un module à écrire.

Le fichier est `montages.json`, à côté des process. *Barre d'outils ▸
flèche du bouton montage ▸ Où sont les gabarits ?* donne son chemin exact
et l'écrit s'il n'existe pas encore. On n'a plus besoin de l'ouvrir pour
le modifier : voir § 5.

```json
{
  "montages": [
    {
      "nom": "Montage 3 DataMatrix",
      "postes": ["HAUT", "MILIEU", "BAS"],
      "entraxe_mm": 23.0,
      "centre_y_mm": 0.2,
      "x_mm": 0.0,
      "donnee": "B000181",
      "code":  { "largeur_mm": 15.0, "hauteur_mm": 7.0,
                 "module_mm": 0.5, "marge_cadre_mm": 0.5 },
      "texte": { "largeur_mm": 6.2, "hauteur_mm": 1.2,
                 "dx_mm": -14.0, "dy_mm": -3.9 }
    }
  ]
}
```

**Entraxe ou positions.** Un montage régulier se décrit comme on le lit
sur un plan — un entraxe et un centre — et les ordonnées s'en déduisent :
+23,2 / +0,2 / −22,8. Un montage **irrégulier** donne ses positions une à
une, et l'entraxe est alors ignoré :

```json
"positions_y_mm": [30.0, 0.0, -12.0]
```

Les deux formes cohabitent : la première dit l'intention, la seconde
couvre ce qui n'en a pas.

**Un gabarit n'a à porter que ce qui change** du montage livré. Le reste
est complété — lui réclamer les douze autres valeurs le rendrait pénible
à écrire, donc faux.

**Un gabarit fautif est refusé, sans emporter les autres** : postes et
positions qui se contredisent, aucun poste, un module nul. Le refus est
retenu et se lit dans *? ▸ Ce qui a été rattrapé*.

**Le fichier n'est pas nécessaire.** Absent, illisible ou vide, le
montage livré fonctionne : personne ne doit avoir à écrire un fichier
pour graver. Il est écrit sur le poste pour être **lu et modifié** — on
ne corrige pas un entraxe dans un fichier dont on ignore l'existence.

Les gabarits partent avec *Paramètres ▸ Exporter les réglages*, aux
côtés des process : un poste qui recevrait les uns sans les autres
poserait ses montages de travers.

---

## 1 bis. Les cotes du montage en service

Relevées sur `Datamatrix.taudrive`, le fichier de production.

| Poste | Symbole (y) | Texte (y) |
|---|---|---|
| **HAUT** | +23,2 mm | +19,3 mm |
| **MILIEU** | +0,2 mm | −3,7 mm |
| **BAS** | −22,8 mm | −26,7 mm |

* symboles centrés en **x = 0**, entraxe **23,0 mm** ;
* symbole **16,0 × 8,0 mm** hors tout — fenêtre de 15 × 7 mm plus le
  cadre englobant de 0,5 mm ;
* module DataMatrix **0,5 mm** ;
* texte à **14 mm à gauche** et **3,9 mm plus bas** que le centre de son
  symbole — une étiquette latérale, pas une légende dessous.

Le cadre entoure **le symbole seul**. Le texte se grave nu : l'enfermer
à son tour creuserait un second rectangle autour de sept caractères, de
la surface dépensée pour rien.

---

## 2. Chaque texte suit son propre code

C'est la raison d'être de ce module.

Dans le fichier d'origine, les trois textes pointaient **tous** vers le
symbole du MILIEU :

```
texte HAUT    follows → 12625c80   (le code du MILIEU)
texte MILIEU  follows → 12625c80   (le sien)
texte BAS     follows → 12625c80   (le code du MILIEU)
```

Conséquence : changer la référence du HAUT ne mettait à jour aucun
texte, et changer celle du MILIEU en réécrivait trois. Une pièce serait
partie avec un code et un numéro lisible qui se contredisent — l'un
lisible à l'œil, l'autre au lecteur. C'est exactement ce que le lien
`follows` existe pour empêcher.

Le montage pose donc **trois liens distincts**, et l'autotest le
vérifie. Le formulaire l'affiche aussi : une ligne verte quand les trois
liens sont en place, une alerte sinon.

> **Une seule implémentation.** La règle vit dans
> `codeplate.propagate_data`, employée aussi bien par l'édition d'un
> code isolé que par le formulaire du montage. Deux versions d'une même
> règle finissent toujours par diverger.

---

## 3. Le formulaire

Trois champs — un par sous-ensemble — et un bouton **Appliquer à tous**
qui reprend la référence du HAUT sur les trois.

Le montage se charge de trois façons, et le formulaire sert les trois :

| Cas | Geste |
|---|---|
| trois pièces différentes | on tape trois références |
| trois pièces du même lot | on tape une fois, puis *Appliquer à tous* |
| une seule pièce remontée | on ne touche qu'un champ |

**Un bouton plutôt qu'une case « tous identiques ».** La case imposerait
un mode ; le bouton rend un service et laisse chaque champ libre
ensuite.

Le formulaire s'ouvre tout seul quand on pose le montage, et chaque fois
qu'on sélectionne ses six formes.

### L'appariement se fait par position

Du haut vers le bas, jamais par le nom. Un nom se modifie à la main et
ment vite : dans le fichier d'origine, les six formes s'appelaient
encore « B000179 » alors que la donnée valait « B000181 ». C'est en
lisant la liste des formes qu'on croit alors avoir posé la bonne pièce.

Les noms sont donc réécrits à chaque saisie, référence **et** poste
compris : `DataMatrix « A111 » HAUT`.

---

## 4. Les groupes

Les six formes sont groupées **deux à deux**, pas toutes ensemble : un
symbole et son texte vont sur la même pièce et se déplacent d'un bloc,
mais les trois postes restent indépendants — ce sont trois pièces
différentes.

---

## 5. Retoucher, enregistrer, retrouver

Ce qu'on retouche sur un montage posé s'enregistre dans son gabarit, et
revient à la pose suivante. Trois endroits :

| Où | Ce qu'on y fait |
|---|---|
| **formulaire de la pose**, section *Cadre, taille et positions* | retoucher le montage posé d'un bloc, puis *Enregistrer dans le gabarit* ou *Comme nouveau…* |
| **flèche du bouton Montage**, *Prochain montage* | choisir le montage que pose le bouton, régler ses cotes — chaque champ s'enregistre aussitôt — ou *Reprendre le montage sélectionné* |
| **bouton *Montages…***, à côté de la bibliothèque | tous les montages : créer, dupliquer, ranger, supprimer, importer, exporter, éditer chaque poste, avec l'aperçu |

Les champs : cadre (rectangle, cercle, aucun), marge, taille du symbole
L × H, entraxe, centre X / Y, fenêtre du texte L × H et sa place par
rapport au code dX / dY. Le gestionnaire ajoute le nom, la symbologie,
la forme du DataMatrix, le module, et le tableau des postes : nom,
ordonnée, abscisse, référence proposée.

**Le poste du haut fait foi.** Relu sur le plan, un montage prend le
symbole et le texte de son premier poste ; chaque poste garde sa propre
position. Des postes régulièrement espacés donnent un entraxe, sinon des
positions une à une, et un poste décalé en X garde son abscisse :

```json
"positions_x_mm": [0.0, 0.4, 0.0]
```

**Le formulaire proposé à la pose.** *Retenir aussi les références
saisies* les écrit, poste par poste, dans le gabarit ; une case vide
reprend `donnee` :

```json
"donnees": ["B000181", "", "B000190"]
```

**Rien n'est perdu.** La première écriture de chaque séance garde le
fichier d'avant à côté de lui, sous le nom `montages.avant.json`. Un
montage que le programme refuse — une faute de frappe dans le fichier —
est réécrit tel quel, et un fichier illisible n'est jamais écrasé : on
le corrige, ou on le supprime pour repartir du montage livré. Le
gestionnaire n'écrit rien avant *Enregistrer*, ne se referme pas sur des
modifications en suspens sans demander, et n'écrase pas sans le dire un
fichier changé pendant qu'il était ouvert.

**Un montage tourné ne se reprend pas** : ses positions sont tournées,
le gabarit non. On le retouche droit, ou l'on règle le gabarit au
gestionnaire.
