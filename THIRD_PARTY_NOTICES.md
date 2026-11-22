# Composants tiers

TauDrive et TauConvert sont sous double licence MIT ou Apache-2.0
(`LICENSE`). Les composants qu'ils embarquent gardent leurs propres
licences ; leurs textes sont dans le dossier `licences` de chaque archive.
Ceux que fournit la distribution Python installée y sont recopiés par
`outils/publier.py` au moment de la publication.

| Composant | Licence | Usage |
|---|---|---|
| PySide6 / Qt 6, shiboken6 | LGPL-3.0 | interface. Liaison dynamique : les bibliothèques Qt sont des fichiers séparés (`_internal/PySide6/Qt6*.dll`), remplaçables par l'utilisateur. Textes : `licences/LGPL-3.0.txt`, `licences/GPL-3.0.txt` |
| ezdxf | MIT | lecture et écriture DXF |
| fontTools | MIT | polices TrueType et OpenType du texte vectorisé |
| shapely / GEOS | BSD-3-Clause / LGPL-2.1 | couteau, décalage, opérations booléennes. GEOS en bibliothèques séparées (`_internal/Shapely.libs`) |
| numpy | BSD-3-Clause | calcul ; requis par les routines accélérées d'ezdxf |
| pypdf | BSD-3-Clause | lecture des PDF, donc d'Illustrator moderne |
| pySerial | BSD-3-Clause | ports série de la source laser JPT (`licences/pyserial-LICENSE.txt`) |
| Python 3.13 | PSF-2.0 | interpréteur embarqué, avec bzip2, libffi, OpenSSL, mpdecimal, expat (`licences/Python-LICENSE.txt`) |

**Embarqués par les dépendances**, sans être appelés par TauDrive :
Pillow (MIT-CMU), cryptography (Apache-2.0 OR BSD-3-Clause), lxml
(BSD-3-Clause), MarkupSafe (BSD-3-Clause), psutil (BSD-3-Clause),
charset-normalizer (MIT), Brotli (MIT), cffi (MIT).

**Bibliothèques d'exécution Microsoft Visual C++** (`VCRUNTIME140.dll`,
`MSVCP140*.dll`, `ucrtbase.dll`, `api-ms-win-*.dll`) : composants
redistribuables de Microsoft.

**Outil de fabrication**, non lié au code : **PyInstaller** (GPL-2.0 ou
ultérieure, avec l'exception qui laisse libre la licence des programmes
empaquetés ; son chargeur est dans `TauDrive.exe` et `TauConvert.exe`).

**Outil de test**, non embarqué : **zxing-cpp** (Apache-2.0), qui relit
les codes 2D dessinés (`outils/verif_codes_zxing.py`).

## Code partagé

Les encodeurs DataMatrix, QR Code, Code 39 et EAN-13
(`src/engrave/barcode.py`) ont été écrits pour TauDrive ; VectorDrive, du
même auteur, les a repris.

## Hors licence

Les données relevées dans les logiciels et sur la machine des
fournisseurs — le dossier `extrait/` (dictionnaire des paramètres de la
carte Cielle, magasin d'outils `dbpunte.mag`) et le dossier
`fournisseurs/`, qui ne quitte pas le poste de développement — restent à
leurs ayants droit : la double licence ne s'y étend pas.

Le plugin d'un atelier, posé dans `plugins/` à côté de l'exécutable, et
les données qu'il apporte (process, semence, magasin d'outils, dessins
livrés) restent à leur auteur, sous sa propre licence.
