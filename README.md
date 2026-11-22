# TauDrive

Dessin, trajectoires et export **ISO / CLJOB** pour le laser de marquage
**Cielle TAU 10×10 SMART** (source fibre MOPA, tête galvanométrique XY2-100,
champ 110 × 110 mm).

**Logiciel libre**, sous double licence **MIT ou Apache-2.0**, au choix
([LICENSE-MIT](LICENSE-MIT), [LICENSE-APACHE](LICENSE-APACHE)). Les
composants tiers gardent leurs licences
([THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md), dossier `licences/`).

> **Logiciel indépendant.** TauDrive n'est ni développé, ni approuvé, ni
> soutenu par Cielle ni par JPT. *Cielle*, *TAU*, *ClTerm*, *Incicam* et
> *JPT* sont des marques ou des noms de leurs titulaires ; ils ne sont
> cités que pour dire avec quel matériel et quels logiciels TauDrive
> fonctionne. Ce dépôt ne contient aucun fichier, programme ni donnée de
> ces fabricants.

---

## Ce que fait TauDrive

- On dessine (textes, codes DataMatrix / QR / Code 39 / EAN-13 /
  Code 128, formes, dessins importés en DXF, SVG, PDF, Illustrator, EPS),
  on attribue une **process** (puissance, fréquence, impulsion, vitesse,
  passes, remplissage) à chaque forme, et TauDrive calcule les
  trajectoires et les ordonne.
- Il écrit des fichiers **`.ISO` + `.CLJOB`** que le logiciel de commande
  de la machine exécute, avec ses propres sécurités. **TauDrive ne pilote
  pas la carte de la machine.**
- Le panneau *Source laser* lit l'état de la source (puissance,
  fréquence, alarmes) et sait **couper** l'émission. Il ne sait pas la
  déclencher : le client série refuse toute commande d'émission autre que
  l'arrêt (`src/jpt/client.py`).

> **Sécurité.** La machine porte un laser de **classe 4**. Un programme
> produit par TauDrive s'essaie sur une chute avant toute série, machine
> fermée, sous la chaîne d'interlocks du constructeur. Le logiciel est
> fourni sans garantie (voir les licences).

---

## Démarrer

```bash
python TauDrive.py                       # TauDrive
python TauDrive.py --autotest            # vérifier l'installation
python TauDrive.py --autotest vectoriel  # une seule grappe
python TauConvert.py                     # convertisseur seul
```

Dépendances : `PySide6`, `fontTools`, `pyserial`, `ezdxf`,
`Pillow` (icône seulement), `PyInstaller` (empaquetage seulement).

**Distribution autonome**, sans Python sur les postes :

```bash
pyinstaller --clean --noconfirm TauDrive.spec
dist/TauDrive/TauDrive.exe --autotest
```

**Versions** — une par publication, décrite dans
[NOUVEAUTES.md](NOUVEAUTES.md) :

```bash
python outils/publier.py --monter
python outils/publier.py
python outils/publier.py --plugin DOSSIER_DU_PLUGIN --edition NOM
```

La publication empaquette TauDrive et TauConvert, lance l'autotest de
chaque exécutable et dépose les archives portables dans `dist/portable/`.
Avec `--plugin`, elle sort aussi l'édition d'un atelier : le même
TauDrive, son plugin posé dans `plugins/`.

**Essais**, sans matériel :

```bash
for t in engrave jpt jpt_client barcode session serialize; do python outils/test_$t.py; done
```

---

## Cœur libre et plugins

TauDrive ne livre **aucune donnée d'atelier** : ses préréglages sont cinq
exemples neutres posés sur les couples constructeur de la source, sans
semence, magasin d'outils, dessins livrés, couples mesurés sur pièce ni
montage en service. Un atelier les apporte par un **plugin**.

Un plugin est un paquet Python qui expose `PLUGIN` (nom, version, API,
licence) et `register(api)`. `api` (`src/engrave/plugins.py`) est la
seule porte vers le cœur ; ce qu'il déclare, le cœur le consulte :

| Méthode | Ce qu'elle apporte | Consulté par |
|---|---|---|
| `add_recipes(…)`, `add_recipes(…, material=True)` | préréglages (ils remplacent ceux du cœur), process par matière | `model.factory_recipes()` |
| `set_recipe_defaults(**valeurs)` | process neuve, forme neuve, champ absent d'un fichier | `model.default_recipe()` |
| `set_seed_dir(dossier)` | semence du premier lancement | `semence.dossier()` |
| `set_tool_store(outils.json)` | magasin d'outils de la machine | `toolstore.bundled_path()` |
| `add_couples(…)` | couples d'atelier nommés, mode expert | `couples.workshop()` |
| `set_drawings_dir(dossier)` | dessins livrés | `drawings.delivered_dir()` |
| `set_montage(gabarit)` | gabarit du montage en service | `gabarits.livre()` |
| `set_machine(nom)`, `add_about(ligne)` | *? ▸ À propos* | `app.machine_label()` |
| `add_autotest(nom, fn)` | contrôles de l'autotest, grappe `plugins` | `TauDrive.exe --autotest plugins` |

Les **couples constructeur** de la source (`couples.FACTORY`, treize
formes d'onde) sont des limites de la source, pas des données d'atelier :
ils restent au cœur.

**Où TauDrive cherche** : `plugins/` à côté de l'exécutable (à la racine
du dépôt en développement), `%LOCALAPPDATA%\TauDrive\plugins`, puis les
dossiers de `TAUDRIVE_PLUGINS` (séparés par `;`). `TAUDRIVE_NO_PLUGINS=1`
les écarte tous. Un plugin en erreur n'empêche jamais le démarrage ;
*À propos* le dit. Les grappes du cœur de l'autotest ne chargent aucun
plugin : elles éprouvent le cœur libre seul.

Les données qu'un plugin apporte restent à leur propriétaire : elles ne
sont pas couvertes par la licence de TauDrive.

---

## Arborescence

| Dossier | Contenu |
|---|---|
| `src/engrave/` | TauDrive : modèle, géométrie, trajectoires, codes 2D, export, interface, thèmes, icônes, plugins |
| `src/jpt/` | protocole et client série de la source laser : lecture d'état, réglages, arrêt |
| `outils/` | essais, publication, export du dépôt public |
| `reference/` | documentation : couteau, import vectoriel, réglages et mise à jour |
| `ressources/` | logo et icône |
| `TauDrive.spec`, `TauConvert.spec` | recettes d'empaquetage PyInstaller ; TauConvert est la version réduite, conversion et menu contextuel seuls |
| `NOUVEAUTES.md` | ce que chaque version change pour l'opérateur |
| `LICENSE`, `LICENSE-MIT`, `LICENSE-APACHE`, `NOTICE` | double licence MIT ou Apache-2.0, et son étendue |
| `THIRD_PARTY_NOTICES.md`, `licences/` | composants tiers : licence et usage de chacun, textes à joindre |

---

## Documents

* [`couteau.md`](reference/couteau.md) — donner une épaisseur à un
  tracé : contours fermés, sans auto-intersection.
* [`import-vectoriel.md`](reference/import-vectoriel.md) — PDF,
  Illustrator, EPS, SVG, CorelDRAW : ce qui est lu et comment, la
  conversion par le clic droit de Windows, et la version réduite
  *TauConvert*.
* [`mise-a-jour.md`](reference/mise-a-jour.md) — où vivent les réglages,
  comment mettre à jour sans rien perdre, import et export.

Ce dépôt est exporté du dépôt de travail, une version par commit.
