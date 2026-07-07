# Projekt-Memo

Kurzer, chronologischer Abriss der Phasen — für den Wiedereinstieg ohne
das ganze Gespräch nochmal lesen zu müssen.

## Phase 1: Datenklärung

- `routes.csv` (OpenFlights, ~2014) und `airports.csv` lagen bereits vor.
- `airports.csv` entpuppte sich beim Nachsehen **nicht** als das
  beschriebene OurAirports-Format, sondern als klassisches
  OpenFlights-`airports.dat`: kein Header, 14 Spalten (u.a. steht
  `"OurAirports"` nur als Quellenangabe in der letzten Spalte, nicht als
  Formathinweis). Entscheidung: als OpenFlights-Format parsen, kein
  erneuter Download nötig.

## Phase 2: Pipeline (main.py)

Modular gebaut, damit einzelne Annahmen später isoliert änderbar sind:

- `distance.py` — Haversine-Distanz
- `flight_time.py` — Faustformel (30 Min + 1h/500 Meilen)
- `data_loading.py` — Einlesen/Filtern (gültiger IATA-Code, Koordinaten)
- `graph_builder.py` — gerichteter Graph, Kantengewicht = reine Flugzeit
- `travel_time.py` — Dijkstra ab virtuellem Knoten, der alle 5
  London-Flughäfen (LHR, LGW, LCY, STN, LTN) mit Gewicht 0 verbindet;
  Umstiegszeit (1,5h) wird erst hier addiert, nicht im Graphen selbst
- `config.py` — alle Stellschrauben zentral

Ergebnis: `travel_times.csv`, 3210 von 6071 gültigen Flughäfen ab London
erreichbar (362 direkt, Rest mit 1–6 Umstiegen).

## Phase 3: Verifikation der Ausgabe

Nutzer meldete scheinbar negative Reisezeiten. Ursache war kein Bug,
sondern verrutschtes Lesen: 12 Flughafennamen enthalten Kommas (z.B.
`"Sandefjord Airport, Torp"`), korrekt gequotet — beim Überfliegen der
Rohdatei mit dem Auge landete ein Längengrad optisch in der
falschen Spalte.

## Phase 4: Punktkarte (plot_map.py)

Vor Isochronen-Konturlinien erst eine reine Punktkarte, um die
räumliche Verteilung/Dichte der Flughäfen zu sehen. Grund: Konturlinien
sind eine Interpolation über die Fläche — bei unregelmäßig verteilten
Stützpunkten (dicht: Europa/Nordamerika/Ostasien; leer: Ozeane, Sahara,
Sibirien, Pazifik) würden global gezogene Konturen über leeren Flächen
erfundene Werte zeigen.

Technische Nebenbaustelle: Cartopys Küstenlinien-Download schlug wegen
eines SSL-Zertifikatsproblems der lokalen Python-Installation fehl —
gelöst, indem `plot_map.py` `certifi` statt der System-CA-Kette nutzt.

Ergebnis: `travel_times_map.png` — Muster ähnelt bereits Galtons
Original (heller Kern um Europa, dunkler Richtung Australien/Ozeanien).

## Phase 5: H3-Raster statt globaler Interpolation

Umsetzung der Idee aus Phase 4: statt einer echten Flächen-Interpolation
ein Uber-H3-Kachelraster (Resolution 4, ~288k Kacheln weltweit) über die
Welt legen und jeder Kachel die Reisezeit des **schnellsten** (nicht des
geografisch nächsten) Flughafens im 300-km-Radius zuweisen — Nähe heißt
nicht gute Anbindung. Kacheln ohne Flughafen im Radius bleiben leer statt
interpoliert.

Neue Module:

- `h3_grid.py` — erzeugt alle Kacheln einer Auflösung
- `nearest_airport.py` — BallTree (Haversine) über die Flughafen-
  Koordinaten aus `travel_times.csv`, Radius-Suche pro Kachel, Minimum
  der Reisezeit unter den Treffern
- `main_h3.py` — Orchestrierung, schreibt `h3_travel_times.csv`
- `plot_h3_map.py` — füllt die Kacheln farblich auf derselben
  Robinson-Karte; unbedeckte Kacheln bleiben leer

Ergebnis: 106.143 von 288.122 Kacheln (36,8 %) abgedeckt — plausibel
bei ~71 % Ozeanfläche plus dünn besiedelten Landflächen (Sahara,
Amazonas, Sibirien). `h3_travel_times_map.png` zeigt die Lücken deutlich
und ähnelt Galtons Original noch mehr als die reine Punktkarte.

## Phase 5b: Korrektur — Bodenzeit fehlte in der Auswahl

Nutzer wies auf einen echten Logikfehler hin: In Phase 5 wurde pro
Kachel nur die reine Reisezeit ab London zum Flughafen minimiert, der
300-km-Radius diente nur als Ja/Nein-Filter. Der Bodenweg vom Flughafen
zur Kachel selbst floss nicht in die Auswahl ein.

Richtig ist: `Gesamtzeit(Kachel) = Reisezeit(London→Flughafen) +
Bodenzeit(Flughafen→Kachel)`, minimiert über alle Kandidaten im Radius.
Weder "nächster Flughafen" noch "schnellster Flughafen ab London" allein
sind korrekt — ein weiter entfernter, aber besser angebundener Flughafen
kann trotz längerem Bodenweg insgesamt gewinnen, und umgekehrt.

`nearest_airport.py` berechnet die Bodenzeit jetzt aus der von der
BallTree gelieferten Distanz (`Distanz_km / GROUND_SPEED_KMH`, Default
80 km/h, neue Konstante in `config.py`) und minimiert die Summe. Neue
Spalte `bodenzeit_stunden` in `h3_travel_times.csv` zur Nachvollziehbarkeit.

## Phase 5c: 300-km-Radius fallen lassen, Land/Wasser-Maske statt Ozean-Cutoff

Da die Kostenfunktion seit Phase 5b Distanz korrekt bestraft (via
Bodenzeit), ist der 300-km-Suchradius keine Korrektheits-, sondern nur
noch eine Performance-Grenze — er wurde auf 3000 km angehoben (Herleitung:
maximale Flugzeitspanne ~34h × 80 km/h ≈ 2700 km, ab da kann kein
entfernterer Flughafen mehr gewinnen).

Neues Problem dadurch: Ozean-Kacheln fanden nun auch "Flughäfen" im
Radius und bekamen Bodenzeit-Werte, die eine Straße übers Wasser
unterstellen. Gelöst mit `land_mask.py` (`global-land-mask`): nur noch
Landkacheln bekommen einen Flughafen-basierten Wert.

Kleinerer Nachklapp: Auch auf "Land" gibt es Orte ohne echte
Verkehrsinfrastruktur (Antarktis-Küste, ~67h "Bodenzeit" zu einem
neuseeländischen Flughafen) — als bekannte Einschränkung akzeptiert,
da nur ~1 % der Kacheln betroffen.

## Phase 6: Seewege — Häfen als eigener Hub-Typ

Nutzeridee: Wasserkacheln sollen ebenfalls eine Reisezeit ab London
bekommen, aber ausschließlich ausgehend von Häfen (nicht von jeder
küstennahen Kachel aus). Zunächst diskutiert, ob eine echte
Schiffsrouten-Bibliothek (z.B. `searoute`, Kanal-/Küstenlinien-bewusst)
nötig ist, um Landüberquerungen bei der Distanzberechnung zu vermeiden.

Datensatz-Recherche ergab: **LINERLIB** (github.com/blof/LINERLIB, ein
akademischer Linienschifffahrts-Benchmark) liefert `ports.csv` (435
Häfen, u.a. mehrere UK-Häfen wie Felixstowe/Southampton) — mit
`dist_dense.csv` sogar bereits kanalbewusste Hafen-zu-Hafen-Distanzen.
Die Kernentscheidung des Nutzers: **Schiffsrouten zwischen Häfen werden
nicht gebraucht.** Ein Hafen ist einfach ein Punkt an Land wie jede
andere Kachel (nächster Flughafen + Bodenzeit) — Wasserkacheln bekommen
dann die Reisezeit des schnellsten Hafens im Umkreis plus Seezeit
(35 km/h). Kein Dijkstra über ein Schiffsnetzwerk nötig.

Umsetzung:

- `ports_loading.py` — lädt `ports.csv`, verwirft Zeilen ohne
  Koordinaten (102 von 435), korrigiert vertauschte Lon/Lat-Werte bei
  erkennbar ungültiger Breite
- `nearest_hub.py` (umbenannt von `nearest_airport.py`) — Logik aus
  Phase 5b verallgemeinert: Geschwindigkeit und Hub-ID-Spalte sind jetzt
  Parameter, damit dieselbe Funktion für Flughäfen (Landkacheln, 80 km/h)
  und Häfen (Wasserkacheln, 35 km/h) funktioniert
- `main_ports.py` — gibt jedem der 333 gültigen Häfen seine eigene
  Reisezeit ab London (wie eine Landkachel), schreibt
  `ports_travel_times.csv`
- `main_h3.py` — teilt das Raster per Landmaske in Land-/Wasserkacheln,
  weist Land über Flughäfen und Wasser über Häfen zu, kombiniert beides
  in `h3_travel_times.csv`

Zwei Nachjustierungen währenddessen:

1. **Bug:** 8 der 333 Häfen sind selbst unerreichbar (`NaN`-Reisezeit).
   `numpy.argmin` gibt bei `NaN` im Array `NaN` zurück statt es zu
   ignorieren — bei großem Suchradius tauchten diese Häfen praktisch
   immer als Kandidaten auf und vergifteten reihenweise Ergebnisse
   (erst 0/206.280 Wasserkacheln abgedeckt). Fix: unerreichbare Hubs
   werden in `nearest_hub.py` vor der Kandidatensuche verworfen.
2. **Darstellung:** Bei 333 Häfen und riesigen Ozeanflächen liegt eine
   Wasserkachel im Schnitt 33,6h Seezeit von ihrem nächsten Hafen
   entfernt — mit unbegrenztem Suchradius (Nutzerwunsch: jede
   Wasserkachel soll einen Wert bekommen) reicht die Farbskala bis
   ~135h und verschluckt jede Land-/Küstenstruktur. Gelöst wie bei
   Galtons Original: `COLOR_CAP_HOURS` (48h) in `config.py`, Farbskala
   kappt statt linear bis zum Extremwert zu strecken
   (`plot_h3_map.py`, `matplotlib`-`Normalize` + `extend="max"`).

Ergebnis: 282.473 von 288.122 Kacheln (98,0 %) abgedeckt, davon alle
206.280 Wasserkacheln. Karte zeigt jetzt auch feine helle Ringe um
einzelne Pazifikinseln, wo ein naher Hafen die Seezeit lokal drückt.

## Phase 6b: Zwei Nutzer-Korrekturen — Pol-Bug und Häfen-Modell

Nutzer meldete zwei Probleme am `h3_travel_times_map.png` aus Phase 6:

1. **Landmassen einheitlich lila statt eingefärbt.** Ursache: Kacheln
   direkt an den Polen haben Eckpunkte, deren Längengrade legitim fast
   360° überspannen (am Pol laufen alle Meridiane zusammen). Die
   Antimeridian-Korrektur in `plot_h3_map.py`
   (`if span > 180: lon += 360`) hat das fälschlich als
   Datumsgrenzen-Überquerung behandelt und daraus ein absurd breites
   Riesenpolygon gemacht, das — da als letztes im selben `PolyCollection`
   gezeichnet — große Teile der Karte überdeckt hat. Kein Farb-, sondern
   ein Geometrie-Bug; die zugrunde liegenden Reisezeit-Daten waren die
   ganze Zeit korrekt (verifiziert: Mitte-USA-Kacheln zeigten korrekt
   ~14h in `h3_travel_times.csv`, aber ~40h-Farbe im Bild). Fix: Kacheln
   mit einer Rohspanne > 300° (596 von 288.122, praktisch nur Pol-Nähe)
   gelten als Pol-Degeneration und werden gar nicht gezeichnet, statt
   falsch korrigiert zu werden.
2. **Häfen brauchen keinen eigenen Flughafen-Bezug.** Nutzer-Korrektur:
   Ein Hafen ist einfach ein Punkt an Land, der schon über die
   Landkacheln eine Reisezeit hat — statt dafür separat die
   Flughafen-Suche zu wiederholen (wie in Phase 6 via `main_ports.py`),
   nimmt man einfach die Reisezeit der dem Hafen nächstgelegenen
   Landkachel. `nearest_hub.py` bekam dafür eine neue, einfache
   Nachbarschafts-Lookup-Funktion `nearest_value` (kein Hub-Mechanismus,
   keine Summe aus Hub-Zeit + letzter Meile). `main_ports.py` entfällt
   dadurch komplett; die Logik wandert in `main_h3.py`, das jetzt in
   fester Reihenfolge arbeitet: Land zuerst, dann Häfen (Lookup gegen
   Land-Ergebnis), dann Wasser (gegen Häfen). Ergebnis: jetzt alle
   333 Häfen abgedeckt (vorher 325, da die eigenständige
   Flughafen-Suche für 8 Häfen keinen Treffer im Radius fand).

Zusätzlich auf Nutzerwunsch: Flughäfen (orange) und Häfen (magenta) als
kleine Punkte auf der Karte eingezeichnet, damit sichtbar ist, welcher
Hub die Farbe einer Region bestimmt.

## Phase 6c: Häfen mitten in der Antarktis

Beim Betrachten der neuen Hafen-Punkte fiel dem Nutzer auf, dass einige
(u.a. Caibarien/Kuba, St Johns/USA, Punta Arenas/Chile) tief im
Süden auf der Karte lagen, obwohl es dort keine echten Häfen gibt.

Ursache: `ports.csv` hat bei etlichen Zeilen Longitude/Latitude
vertauscht - der bisherige Check (Phase 6, `ports_loading.py`) erkannte
das nur, wenn der vertauschte "Latitude"-Wert außerhalb von [-90, 90]
lag. Bei Häfen, deren reale Longitude zufällig auch als plausible
Breite durchgeht (z.B. Punta Arenas: reale Position -53.08/-70.56, aber
in der Datei als 70.56/-53.08 vertauscht - beide Werte einzeln gültig),
blieb die Vertauschung unentdeckt und landete als "Breite -70" mitten
in der Antarktis.

Fix (erster Versuch): zweiter Plausibilitätstest in `ports_loading.py` -
`IMPLAUSIBLE_SOUTH_LATITUDE = -55` (der südlichste echte Handelshafen
im Datensatz, Punta Arenas, liegt bei ca. -53; alles südlicher ist
also eine Vertauschung, keine echte Position). Betraf 13 von 333 Häfen.

## Phase 6d: Doch noch mehr vertauschte Häfen — robuster Fix über die Country-Spalte

Der -55°-Schwellenwert war noch zu eng: Nutzer entdeckte weitere falsch
platzierte Häfen mitten im Südatlantik/Südpazifik (u.a. "Argentia",
Kanada, und "Belem", Brasilien). Beide Fälle zeigten, dass die
Vertauschung nicht an einem festen Muster (z.B. "nur extreme Werte")
festzumachen ist: Argentia landete bei Breite -54.0 (knapp über dem
-55°-Schwellenwert, damit unentdeckt), Belem bei -48.3 (weit über dem
Schwellenwert, aber trotzdem falsch - reale Position ist nahe des
Äquators). Manche Zeilen in `ports.csv` sind korrekt, manche vertauscht,
ohne erkennbares Muster in der Größenordnung der Werte.

Grundlegender Fix: Statt einer Wertebereichs-Heuristik wird jetzt die
in `ports.csv` mitgelieferte `Country`-Spalte als Kontrolle genutzt.
Für beide Lesarten einer Zeile (Datei-Reihenfolge und vertauscht) wird
per `reverse_geocoder` (offline, GeoNames-Städtedatenbank) das Land der
Koordinate bestimmt; welche Lesart zum in `ports.csv` angegebenen Land
passt (Abgleich der Ländernamen zu ISO-3166-Alpha-2-Codes via
`pycountry`, mit einer kleinen Override-Liste für Schreibweisen wie
"U. A. E." oder "Ivory Coast", die pycountry nicht kennt), gewinnt. Für
die zwei Häfen ohne Country-Angabe (Cap-Haitien, Torshavn) greift
weiterhin der alte Schwellenwert als Fallback.

Ein Implementierungs-Stolperstein dabei: `pandas.Series.map()` wandelt
den `None`-Rückgabewert der Lookup-Funktion für fehlende Länder
stillschweigend in `float('nan')` um - `nan is not None` ist `True`,
was die ursprüngliche `is None`-Prüfung lautlos falsch auswerten ließ.
Behoben durch `pd.isna()` statt `is None`.

Ergebnis: alle 333 Häfen korrekt platziert (bis auf zwei erwartbare
Falsch-Positive direkt an Landesgrenzen - Tangier/Marokko direkt an der
Straße von Gibraltar, ein Hafen in der Torres-Strait an der Grenze
Australien/Papua-Neuguinea - dort tippt `reverse_geocoder` auf den
geografisch nächsten Ort im Nachbarland, obwohl die Koordinate selbst
stimmt).

## Phase 7 (geplant): Isochronen-Konturlinien

Auf Basis des kombinierten Land+See-H3-Rasters aus Phase 6 echte
Isolinien zeichnen. Noch nicht umgesetzt.
