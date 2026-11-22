# Nouveautés de TauDrive

Ce qui change pour l'opérateur, version par version (les plus récentes en
bas). Le détail de chaque changement, ses mesures et ses contrôles sont
dans la spécification de travail (`reference/specification.md`, non
publiée), à l'entrée EX indiquée.

Jusqu'à 1.0.267, le dernier chiffre était le numéro de la dernière entrée
EX. Depuis 1.268.0, comme VectorDrive, le chiffre du milieu monte de 1 à
chaque version publiée.

### v1.0.265 — un seul dossier de travail, une archive par version

- Le dépôt devient un seul dossier `TauDrive/` ; les dossiers des
  fournisseurs se rangent dans `fournisseurs/`, en lecture seule.
- Chaque version sort en archive zippée portable, vérifiée par l'autotest
  de l'exécutable (EX-265).

### v1.0.266 — démarrage rapide, combiner et décombiner

- Au lancement, seul l'onglet de devant s'ouvre ; les autres se chargent
  au premier clic. Avec quatre onglets dont un dessin de 220 000 points, la
  fenêtre paraît en 1 à 2 s au lieu de 8 à 10 (EX-266).
- Résumé du travail bien plus rapide quand plusieurs passes gravent les
  mêmes traits : 4,4 s → 0,3 s, mêmes valeurs.
- Combiner et Décombiner dans le menu *Forme* ; Alt+W centre la sélection
  dans le champ ; Ctrl+I importe un dessin.

### v1.0.267 — Q groupe, S dégroupe

- **Q** groupe la sélection, **S** la dégroupe — sur le plan de travail et
  la liste des formes seulement : dans un champ, la lettre s'écrit.
- **Ctrl+G** combine, **Ctrl+Maj+G** décombine, partout dans la fenêtre
  (EX-267).

### v1.268.0 — le numéro de version, comme VectorDrive

- Un seul numéro, `1.268.0`, affiché dans *? ▸ À propos*, inscrit dans les
  propriétés Windows de `TauDrive.exe` et `TauConvert.exe` (clic droit ▸
  *Propriétés* ▸ *Détails*, qui affichaient 1.0.0) et dans le nom des
  archives (EX-268).
- Le chiffre du milieu monte de 1 à chaque version publiée ; ce fichier
  dit ce que chacune apporte, et voyage dans l'archive.

### v1.269.0 — logiciel libre : MIT ou Apache-2.0

- TauDrive et TauConvert sont sous double licence **MIT ou Apache-2.0**,
  au choix, comme VectorDrive (EX-269).
- L'archive porte, à côté de l'exécutable, la licence (`LICENSE`…), la
  liste des composants tiers (`THIRD_PARTY_NOTICES.md`) et leurs licences
  (dossier `licences`) ; *? ▸ À propos* le rappelle.
- Les données relevées chez les fournisseurs (`extrait/`) restent hors
  licence.

### v1.270.0 — libre sans données d'atelier ; les plugins

- TauDrive est livré **sans aucune donnée d'atelier**, comme VectorDrive
  (EX-270) : ses préréglages sont cinq exemples neutres — repérage,
  marquage, deux passes, satinage, remplissage hachuré —, posés sur les
  couples constructeur de la source, outil 1. Ni process relevées sur une
  machine, ni process par matière, ni semence, ni magasin d'outils, ni
  dessins livrés, ni couples mesurés sur pièce.
- Les **couples constructeur** de la source JPT — les treize formes
  d'onde — restent.
- Ces données reviennent par le **plugin de l'atelier**, posé dans
  `plugins/` à côté de `TauDrive.exe`. L'édition de l'atelier
  (`TauDrive-NOM-x.y.z-portable.zip`) le porte et se comporte exactement
  comme la version précédente ; *? ▸ À propos* nomme les plugins chargés.
- Les documents se relisent comme avant ; le format ne change pas.

### v1.271.0 — aucune émission laser possible ; montage de l'atelier en plugin

- Le panneau *Source laser* lit l'état de la source et **coupe**
  l'émission ; il ne peut plus la déclencher, même par un appel direct :
  le client série refuse toute commande d'émission autre que l'arrêt
  (EX-271).
- Le **gabarit du montage en service** vient du plugin de l'atelier.
  Sans plugin, TauDrive propose un exemple à trois postes, référence
  `B000001`. L'édition de l'atelier se comporte exactement comme avant.
- Exemple de rayon de la bibliothèque : « Clients/Exemple ».
- Le module de trame de la carte CNC, dont l'application ne se sert pas,
  n'est plus embarqué.
- Le dépôt public a son propre README : ce que fait TauDrive, sécurité,
  indépendance vis-à-vis des fabricants, plugins.
