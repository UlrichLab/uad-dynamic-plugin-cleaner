# UAD Dynamic Plugin Cleaner

A conservative, dynamic macOS cleanup assistant for Universal Audio UAD, UADx, UAD-2, and Apollo systems using Audio Unit (AU), VST2, VST3, and AAX plug-ins. **It never removes anything by default.**

[Deutsche Version](#deutsche-version)

## Quick start

First check that Python 3.9 or newer is available:

```bash
python3 --version
```

*(If this command is unavailable or reports a version older than 3.9, see [Install Python on macOS](#install-python-on-macos) at the end of the English guide.)*

Then continue:

```bash
git clone https://github.com/UlrichLab/uad-dynamic-plugin-cleaner.git
cd uad-dynamic-plugin-cleaner
python3 uad-dynamic-plugin-cleaner.py --preview
```

1. Start UA Connect and make sure you are signed in. Connect and power on Apollo/UAD-2 hardware when DSP licenses should be checked.
2. Run the commands above. Nothing is removed.
3. Open `~/Desktop/UAD Cleanup Reports/` and review both `REMOVE CANDIDATES` and `UNKNOWN / MANUAL REVIEW`.
4. The tool automatically reads both current UADx cloud licenses and current UAD-2/Apollo hardware authorizations. Use the fallback allowlist only for an exceptional product that neither source can map.
5. Only after reviewing the final preview, move explicitly identified candidates into a recoverable backup:

```bash
sudo python3 uad-dynamic-plugin-cleaner.py --delete --yes \
  --report-dir "$HOME/Desktop/UAD Cleanup Reports" \
  --backup-dir "$HOME/Desktop/UAD Cleanup Backups"
```

No Git? Use **Code → Download ZIP** on GitHub, extract it, open that folder in Terminal, and continue with step 1.

## Why it is different

Many cleanup scripts rely on a manually exported `UADSystemProfile.txt` or on one fixed list of products. Such snapshots can become outdated after a purchase, license change, or UA Connect update.

UAD Dynamic Plugin Cleaner combines two current local sources automatically:

1. It reads the local UA Cloud Helper in real time using HTTP GET requests only for UADx/cloud licenses.
2. For classic UAD-2/DSP licenses, it asks the installed UAD Meter & Control Panel to create a fresh system profile, reads only its authorization section, and immediately removes that temporary profile. The UA Helper disk manifests safely bridge installed package names to UAD Meter display names.

A cloud plug-in is dynamically considered licensed only when both conditions are true:

```text
license_state == full_active
cloud_licenses contains at least one entry with:
  name == full
  is_demo == false
  deposit_status == deposited
```

`not_licensed`, `demo_available`, and an empty `cloud_licenses` list do not qualify. A UAD-2/DSP product qualifies when the fresh profile reports `Authorized for ...`; demo, expired, and non-authorized states do not. The tool creates this profile itself, so no manual export is required and no profile snapshot is committed or retained.

In short: **dynamic UADx license plus dynamic UAD-2/Apollo authorization; optional static fallback only as a final safety net.** An explicit negative match can become a preview candidate; inconclusive entries remain `UNKNOWN / MANUAL REVIEW`. Missing data alone is never treated as proof that a plug-in is unlicensed.

## Safety model

- Preview is the default, even when no mode is supplied.
- The Helper is read-only: no activation, download, purchase, or sync commands are sent.
- UAD Meter only generates a fresh local profile. The tool parses its authorization section and deletes the temporary full profile immediately because it can contain hardware identifiers.
- If the Helper is unavailable, invalid, or returns no plug-ins, the program stops without classifying or changing files.
- If UAD Meter reports `No UAD-2 devices found` for the profile, the program stops. A disconnected or powered-off Apollo/UAD-2 device is never interpreted as an unlicensed collection.
- A file becomes a removal candidate only after a manifest-backed match to an explicitly negative Cloud or UAD-2 status. Any positive license source wins. Inconclusive products are marked for manual review and cannot be moved by `--delete`.
- Standard system and user plug-in locations are scanned recursively for `UAD ` and `uaudio_` packages ending in `.component`, `.vst`, `.vst3`, or `.aaxplugin`. This includes Universal Audio's nested category folders and mono VST2 variants.
- `--delete` also requires `--yes` and moves candidates to a timestamped backup. It does not permanently erase them.
- Human-readable TXT and machine-readable JSON reports are created before any change.

## Compatibility

The project is designed for supported macOS installations that have:

- Python 3.9 or newer;
- UA Connect / UA Cloud Helper running locally at `127.0.0.1:4793`;
- UAD Meter & Control Panel plus connected hardware when UAD-2/DSP licenses should be detected;
- UAD plug-ins installed in the standard system or user AU, VST2, VST3, or AAX folders.

It is architecture-independent Python and does not assume an Intel or Apple-silicon CPU. However, “every Mac” cannot be guaranteed: old macOS/Python releases, non-standard install paths, permissions, or a future UA Connect API change may require adjustment. The fail-closed behavior is intentional.

## Neutral example

Imagine a Mac with 12 UAD plug-in packages. The Cloud Helper confirms six full licenses, including popular product types such as an 1176 compressor, an LA-2A compressor, a Pultec EQ, and a tape echo. The current Apollo/UAD-2 authorization confirms two DSP products. One matching product is explicitly reported as unlicensed, while three files have no conclusive data.

The preview could look like this:

```text
Installed UAD AU/VST2/VST3/AAX found: 12
Would keep: 8
Remove candidates: 1
Unknown / manual review: 3
```

Those numbers and product categories are illustrative only; they are not copied from a real user's system. The explicitly unlicensed match is only a candidate, and the three inconclusive files cannot be moved by `--delete`.

## Usage

Always start with a preview:

```bash
python3 uad-dynamic-plugin-cleaner.py --preview
```

Reports are written to `~/Desktop/UAD Cleanup Reports/` by default. Carefully review both `REMOVE CANDIDATES` and `UNKNOWN / MANUAL REVIEW`.

Only after reviewing the preview:

```bash
sudo python3 uad-dynamic-plugin-cleaner.py --delete --yes \
  --report-dir "$HOME/Desktop/UAD Cleanup Reports" \
  --backup-dir "$HOME/Desktop/UAD Cleanup Backups"
```

With this command, the shell expands `$HOME` before privilege elevation and keeps these paths on the current user's Desktop. Candidates are moved into a dated subfolder and can be restored.

### Existing or manually generated UAD-2 profile

Normally no manual profile is needed. If UAD Meter cannot be started automatically, create a current `UADSystemProfile.txt` in UAD Meter and run:

```bash
python3 uad-dynamic-plugin-cleaner.py --preview --uad2-profile /path/to/UADSystemProfile.txt
```

The automatic refresh refuses to overwrite an existing `~/Desktop/UADSystemProfile.txt`; move or rename that file first. Never publish it because it can contain hardware identifiers. `--skip-uad2` deliberately disables DSP detection and will usually produce more `UNKNOWN` items.

### Optional static fallback allowlist

Edit `uad-static-fallback-allowlist.txt` only when an owned product cannot be mapped by either dynamic source, and add one product or filename per line:

```text
# My older DSP products
UAD Example Product
Another Example Product.component
```

The distributed file intentionally contains no real user's collection. It may remain empty when dynamic Helper coverage is sufficient. It does not replace or override the dynamic license check. A different fallback file can be selected with:

```bash
python3 uad-dynamic-plugin-cleaner.py --preview --allowlist /path/to/my-allowlist.txt
```

## Tests

```bash
python3 -m unittest discover -s tests -v
```

## Known limitations

Matching uses UA disk manifests and normalized product/package names. Universal Audio does not document the local Helper endpoint or UAD Meter's `-gsp` switch as stable public APIs, so a software update could change either interface. The program deliberately stops on invalid data and does not replace manual review of the preview report.

## Privacy

The program contacts only the local loopback Helper URL by default. The temporary full UAD system profile is deleted after parsing and is never copied into the repository. Reports remain local and are excluded from Git; they can contain licensed product names and filesystem paths, so review them before sharing.

## Related topics

Universal Audio cleanup, Universal Audio Apollo, Apollo audio interface, UAD cleanup tool, UA Connect cleanup, UADx license detection, UAD-2 DSP plug-ins, macOS Audio Units, VST3 plug-ins, music production, audio engineering, studio maintenance, Apple Silicon, Intel Mac, Python CLI, safe plug-in removal, and recoverable plug-in backup.

## License and trademarks

MIT. This independent project is not affiliated with or endorsed by Universal Audio. UAD, Universal Audio, and third-party product names are trademarks of their respective owners.

## Install Python on macOS

Skip this section when `python3 --version` already reports Python 3.9 or newer.

1. Check whether Homebrew is installed:

```bash
brew --version
```

2. If the command is not found, install Homebrew with its official installer. Review the script and prompts before approving them:

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

3. Install Python and verify it:

```bash
brew install python3
python3 --version
```

If the current Homebrew release does not support your macOS version, use the signed installer from the official [Python releases for macOS](https://www.python.org/downloads/macos/) page instead. This project does not require extra Python packages.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Deutsche Version

Ein vorsichtiges, dynamisches macOS-Werkzeug zum Prüfen installierter Universal-Audio-Plug-ins für UAD-, UADx-, UAD-2- und Apollo-Systeme mit Audio Unit (AU), VST2, VST3 und AAX. **Standardmäßig wird niemals etwas entfernt.**

## Schnellstart

Zuerst prüfen, ob Python 3.9 oder neuer vorhanden ist:

```bash
python3 --version
```

*(Ist dieser Befehl nicht verfügbar oder zeigt er eine Version unter 3.9, siehe [Python unter macOS installieren](#python-unter-macos-installieren) am Ende der deutschen Anleitung.)*

Danach fortfahren:

```bash
git clone https://github.com/UlrichLab/uad-dynamic-plugin-cleaner.git
cd uad-dynamic-plugin-cleaner
python3 uad-dynamic-plugin-cleaner.py --preview
```

1. UA Connect starten und anmelden. Apollo-/UAD-2-Hardware anschließen und einschalten, wenn DSP-Lizenzen geprüft werden sollen.
2. Die Befehle oben ausführen. Dabei wird nichts entfernt.
3. In `~/Desktop/UAD Cleanup Reports/` sowohl `REMOVE CANDIDATES` als auch `UNKNOWN / MANUAL REVIEW` prüfen.
4. Das Tool liest automatisch sowohl aktuelle UADx-Cloud-Lizenzen als auch aktuelle UAD-2-/Apollo-Hardware-Autorisierungen. Die Fallback-Allowlist ist nur für seltene Ausnahmen gedacht, die keiner der beiden Wege zuordnen kann.
5. Erst nach dem abschließend geprüften Preview die ausdrücklich erkannten Kandidaten in ein wiederherstellbares Backup verschieben:

```bash
sudo python3 uad-dynamic-plugin-cleaner.py --delete --yes \
  --report-dir "$HOME/Desktop/UAD Cleanup Reports" \
  --backup-dir "$HOME/Desktop/UAD Cleanup Backups"
```

Ohne Git: Auf GitHub **Code → Download ZIP** wählen, entpacken, den Ordner im Terminal öffnen und mit Schritt 1 fortfahren.

## Warum dieser Ansatz anders ist

Viele Cleanup-Skripte arbeiten mit einem manuell exportierten `UADSystemProfile.txt` oder einer festen Produktliste. Solche Momentaufnahmen können nach einem Kauf, einer Lizenzänderung oder einem UA-Connect-Update veraltet sein.

UAD Dynamic Plugin Cleaner kombiniert automatisch zwei aktuelle lokale Quellen:

1. Der lokale UA Cloud Helper wird für UADx-/Cloud-Lizenzen in Echtzeit und ausschließlich über HTTP-GET gelesen.
2. Für klassische UAD-2-/DSP-Lizenzen lässt das Tool UAD Meter & Control Panel selbst ein frisches Systemprofil erzeugen, liest nur den Autorisierungsabschnitt und entfernt die temporäre Profildatei sofort wieder. Die Disk-Manifeste des UA Helpers verbinden installierte Paketnamen sicher mit den Anzeigenamen des UAD Meters.

Ein Cloud-Plug-in gilt dynamisch nur dann als lizenziert, wenn beide Bedingungen erfüllt sind:

```text
license_state == full_active
cloud_licenses enthält mindestens einen Eintrag mit:
  name == full
  is_demo == false
  deposit_status == deposited
```

`not_licensed`, `demo_available` und eine leere `cloud_licenses`-Liste reichen nicht aus. Ein UAD-2-/DSP-Produkt gilt als lizenziert, wenn das frische Profil `Authorized for ...` meldet; Demo-, abgelaufene und nicht autorisierte Zustände reichen nicht aus. Das Tool erzeugt dieses Profil selbst: Ein manueller Export ist nicht nötig, und die Profildatei wird weder behalten noch veröffentlicht.

Kurz gesagt: **dynamische UADx-Lizenz plus dynamische UAD-2-/Apollo-Autorisierung; eine statische Allowlist nur als letzte Sicherheitsstufe.** Ein ausdrücklich negativer Treffer kann Preview-Kandidat werden; nicht eindeutige Einträge bleiben `UNKNOWN / MANUAL REVIEW`. Fehlende Daten allein sind niemals ein Beweis für eine fehlende Lizenz.

## Sicherheitsmodell

- Preview ist immer der Standardmodus.
- Der Helper wird nur gelesen; das Tool sendet keine Aktivierungs-, Download-, Kauf- oder Sync-Befehle.
- UAD Meter erzeugt lediglich ein frisches lokales Profil. Das Tool liest dessen Autorisierungsabschnitt und entfernt das vollständige temporäre Profil sofort, weil es Hardwarekennungen enthalten kann.
- Bei einem nicht erreichbaren, ungültigen oder leeren Helper-Ergebnis stoppt das Tool ohne Änderungen.
- Meldet UAD Meter im Profil `No UAD-2 devices found`, stoppt das Tool ebenfalls. Ein getrenntes oder ausgeschaltetes Apollo-/UAD-2-Gerät wird niemals als nicht lizenzierte Sammlung interpretiert.
- Eine Datei wird nur nach einer manifestgestützten Zuordnung zu einem ausdrücklich negativen Cloud- oder UAD-2-Status Remove Candidate. Jede positive Lizenzquelle hat Vorrang. Nicht eindeutige Produkte bleiben in der manuellen Prüfung und werden von `--delete` nicht verschoben.
- Die üblichen systemweiten und benutzerbezogenen Plug-in-Ordner werden rekursiv nach Paketen durchsucht, deren Name mit `UAD ` oder `uaudio_` beginnt und auf `.component`, `.vst`, `.vst3` oder `.aaxplugin` endet. Dadurch werden auch verschachtelte Universal-Audio-Kategorieordner und Mono-VST2-Varianten erfasst.
- `--delete` erfordert zusätzlich `--yes` und verschiebt Kandidaten in ein datiertes Backup. Es löscht sie nicht endgültig.
- Vor jeder Änderung entstehen TXT- und JSON-Reports.

## Kompatibilität

Das Projekt ist für unterstützte macOS-Installationen mit folgenden Voraussetzungen ausgelegt:

- Python 3.9 oder neuer;
- laufendes UA Connect bzw. UA Cloud Helper unter `127.0.0.1:4793`;
- UAD Meter & Control Panel sowie angeschlossene Hardware, wenn UAD-2-/DSP-Lizenzen erkannt werden sollen;
- UAD-Plug-ins in den üblichen systemweiten oder benutzerbezogenen AU-, VST2-, VST3- oder AAX-Ordnern.

Der Python-Code ist nicht an Intel oder Apple Silicon gebunden. Eine Garantie für „jeden Mac“ wäre trotzdem unseriös: Alte macOS-/Python-Versionen, abweichende Installationspfade, Berechtigungen oder eine künftige Änderung der UA-Connect-Schnittstelle können Anpassungen erfordern. In solchen Fällen stoppt das Tool bewusst sicher.

## Neutrales Beispiel

Angenommen, auf einem Mac liegen zwölf UAD-Plug-in-Pakete. Der Cloud Helper bestätigt Voll-Lizenzen für sechs Produkte, darunter bekannte Produktarten wie einen 1176-Kompressor, einen LA-2A-Kompressor, einen Pultec-EQ und ein Tape-Echo. Die aktuelle Apollo-/UAD-2-Autorisierung bestätigt zwei DSP-Produkte. Ein eindeutig zugeordnetes Produkt wird ausdrücklich als nicht lizenziert gemeldet; für drei Dateien gibt es keine eindeutigen Daten.

Der Preview könnte dann so aussehen:

```text
Installed UAD AU/VST2/VST3/AAX found: 12
Would keep: 8
Remove candidates: 1
Unknown / manual review: 3
```

Diese Zahlen und Produktkategorien sind rein beispielhaft und stammen nicht von einem realen Nutzersystem. Der ausdrücklich negative Treffer ist nur ein Kandidat; die drei nicht eindeutig bewertbaren Dateien können von `--delete` nicht verschoben werden.

## Verwendung

Immer zuerst Preview ausführen:

```bash
python3 uad-dynamic-plugin-cleaner.py --preview
```

Die Reports liegen standardmäßig in `~/Desktop/UAD Cleanup Reports/`. Sowohl `REMOVE CANDIDATES` als auch `UNKNOWN / MANUAL REVIEW` sorgfältig prüfen.

Nur nach geprüftem Preview:

```bash
sudo python3 uad-dynamic-plugin-cleaner.py --delete --yes \
  --report-dir "$HOME/Desktop/UAD Cleanup Reports" \
  --backup-dir "$HOME/Desktop/UAD Cleanup Backups"
```

Bei diesem Befehl ersetzt die Shell `$HOME` vor dem Wechsel der Rechte, sodass Report und Backup auf dem Desktop des aktuellen Benutzers landen. Kandidaten werden in einen datierten Unterordner verschoben und können wiederhergestellt werden.

### Vorhandenes oder manuell erzeugtes UAD-2-Profil

Normalerweise ist kein manueller Export nötig. Falls UAD Meter nicht automatisch gestartet werden kann, dort ein aktuelles `UADSystemProfile.txt` erzeugen und so verwenden:

```bash
python3 uad-dynamic-plugin-cleaner.py --preview --uad2-profile /pfad/UADSystemProfile.txt
```

Die automatische Aktualisierung überschreibt kein vorhandenes `~/Desktop/UADSystemProfile.txt`; diese Datei vorher verschieben oder umbenennen. Sie niemals veröffentlichen, denn sie kann Hardwarekennungen enthalten. `--skip-uad2` schaltet die DSP-Erkennung bewusst ab und führt gewöhnlich zu mehr `UNKNOWN`-Einträgen.

### Optionale statische Fallback-Allowlist

In `uad-static-fallback-allowlist.txt` wird nur dann pro Zeile ein eigenes Produkt oder ein Dateiname eingetragen, wenn ein gekauftes Produkt von beiden dynamischen Quellen nicht zugeordnet werden kann:

```text
# Meine älteren DSP-Produkte
UAD Beispielprodukt
Weiteres Beispielprodukt.component
```

Die veröffentlichte Datei enthält bewusst keine Sammlung eines realen Nutzers. Sie darf leer bleiben, wenn die dynamische Helper-Abdeckung ausreicht. Sie ersetzt oder überstimmt die dynamische Lizenzprüfung nicht. Eine andere Fallback-Datei lässt sich so auswählen:

```bash
python3 uad-dynamic-plugin-cleaner.py --preview --allowlist /pfad/meine-liste.txt
```

## Tests

```bash
python3 -m unittest discover -s tests -v
```

## Bekannte Grenzen

Die Zuordnung erfolgt über UA-Disk-Manifeste und normalisierte Produkt-/Dateinamen. Universal Audio dokumentiert weder den lokalen Helper-Endpunkt noch den `-gsp`-Schalter des UAD Meters als stabile öffentliche API; ein Software-Update kann beide Schnittstellen ändern. Das Tool stoppt bei ungültigen Daten absichtlich sicher und ersetzt nicht die manuelle Prüfung des Preview-Reports.

## Datenschutz

Standardmäßig kontaktiert das Programm nur die lokale Loopback-Adresse des Helpers. Das vollständige temporäre UAD-Systemprofil wird nach dem Einlesen gelöscht und niemals ins Repository kopiert. Reports bleiben lokal und werden von Git ausgeschlossen; da sie lizenzierte Produktnamen und Dateipfade enthalten können, sollten sie vor einer Weitergabe geprüft werden.

## Verwandte Suchbegriffe

Universal Audio Cleanup, Universal Audio Apollo, Apollo Audio Interface, UAD Cleanup Tool, UA Connect Cleanup, dynamische UADx-Lizenzerkennung, UAD-2 DSP-Plug-ins, macOS Audio Units, VST3-Plug-ins, Musikproduktion, Audio Engineering, Studio-Wartung, Apple Silicon, Intel Mac, Python CLI, sichere Plug-in-Bereinigung und wiederherstellbares Plug-in-Backup.

## Lizenz und Marken

MIT. Dieses unabhängige Projekt steht in keiner Verbindung zu Universal Audio und wird nicht von Universal Audio unterstützt. UAD, Universal Audio und Produktnamen Dritter sind Marken ihrer jeweiligen Eigentümer.

## Python unter macOS installieren

Diesen Abschnitt überspringen, wenn `python3 --version` bereits Python 3.9 oder neuer ausgibt.

1. Prüfen, ob Homebrew installiert ist:

```bash
brew --version
```

2. Wird der Befehl nicht gefunden, Homebrew mit dem offiziellen Installer installieren. Skript und Rückfragen vor der Bestätigung prüfen:

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

3. Python installieren und die Version kontrollieren:

```bash
brew install python3
python3 --version
```

Unterstützt die aktuelle Homebrew-Version das verwendete macOS nicht, stattdessen den signierten Installer von der offiziellen Seite [Python für macOS](https://www.python.org/downloads/macos/) verwenden. Dieses Projekt benötigt keine zusätzlichen Python-Pakete.
