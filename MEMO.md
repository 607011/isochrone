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

## Phase 8: Karten ab beliebigem Flughafen (map_from_airport.py)

Nutzerfrage: Wie sieht die Karte von einem Flughafen aus, der selbst nur
über 5 Umstiege ab London erreichbar ist? Kandidaten dafür in
`travel_times.csv` (`anzahl_umstiege == 5`, 9 Flughäfen): Thule Air Base
(Grönland, 18,22h), Attawapiskat, Salluit, Bunia, Kalemie, Santana do
Araguaia, sowie Birdsville und Thargomindah (beide australisches
Outback, 31,69h bzw. 33,75h). Interpretation "5 Hops" = 5 Umstiege
(unsere `anzahl_umstiege`-Spalte), nicht 5 Flugsegmente - dem Nutzer
mitgeteilt, falls anders gemeint.

Neues Skript `map_from_airport.py` verallgemeinert main.py/main_h3.py/
plot_h3_map.py auf einen beliebigen Start-Flughafen (nicht mehr fest auf
`config.ORIGIN_AIRPORTS`), inklusive neu berechneter Hafen-Reisezeiten
(hängen ja vom Start ab). `plot_h3_map.py` bekam dafür einen
`origin_label`-Parameter statt hartcodiertem "London" in Titel/Legende.

Ergebnis: Thule zeigt einen winzigen hellen Fleck in der Arktis, fast
die ganze Welt >48h entfernt (extrem schlecht angebundener Militär-
Flugplatz). Birdsville dagegen hat trotz eigener Abgeschiedenheit ein
sichtbar größeres helles Umfeld (ganz Australien/Neuseeland), weil die
nahen Drehkreuze (Sydney, Melbourne, Brisbane) selbst gut vernetzt sind
- Abgeschiedenheit vom Flugnetz und Abgeschiedenheit von der Welt sind
nicht dasselbe.

Auf Nutzerwunsch ab dieser Phase: alle erzeugten Karten (auch die
London-Standardkarten) bekommen sprechende Dateinamen statt der
generischen `travel_times_map.png`/`h3_travel_times_map.png` -
`config.py` entsprechend angepasst, bestehende Dateien umbenannt.

## Phase 9: Friction Surface - anisotrope Bodenzeit (Birdsville-Demo)

Rückgriff auf die Melbourne-Diskussion (siehe Anfang des Gesprächs):
Nutzer wollte sehen, wie sich die Birdsville-Karte mit einem
anisotropen (straßenbasierten) statt isotropem (Kreis-)Bodenzeitmodell
verändert.

Technischer Weg dahin nicht ganz reibungslos:

1. **Live-Overpass-API nicht erreichbar.** `osmnx.graph_from_point()`
   (der übliche Weg, Straßendaten für eine Region zu holen) schlug mit
   `ConnectionError`/406 fehl - getestet gegen mehrere Overpass-Mirrors
   (overpass-api.de, overpass.kumi.systems), auch direkt per `curl`
   reproduzierbar. Einfache GET-Requests an dieselben Hosts funktionierten,
   nur die eigentliche Query (POST) nicht - vermutlich eine Einschränkung
   der Sandbox-Umgebung, keine osmnx-spezifische Ursache.
2. **Workaround: direkter Download statt Live-Abfrage.** Geofabrik
   (`download.geofabrik.de`) stellt fertige, regionale OSM-Extrakte als
   normalen HTTPS-Download bereit (kein Overpass nötig) - Queensland-
   Extrakt (~196 MB) geladen, mit `pyrosm` auf eine Bounding Box um
   Birdsville gefiltert (61.480 Knoten, 61.829 Kanten, ~2 Minuten).
   Nicht ins Git-Repo aufgenommen (zu groß, reproduzierbar), die
   gefilterten Parquet-Dateien fürs Birdsville-Gebiet dagegen schon
   (klein, sparen die 2 Minuten Filterzeit).

`friction_surface_demo.py` (bewusst eigenständig, nicht Teil der
globalen Pipeline - echtes Routing weltweit wäre unverhältnismäßig
aufwändig, siehe frühere Diskussion): baut aus den OSM-Kanten einen
`networkx`-Graphen (Fahrzeit je Kante = Länge / Geschwindigkeit nach
Straßenklasse, grobe Default-Tabelle mangels `maxspeed`-Tags), Dijkstra
ab dem nächsten Netzknoten zu Birdsville Airport, und vergleicht das
Ergebnis mit dem bisherigen isotropen Modell für dieselbe Region
(H3 Res. 6, ~330 km Kantenlänge der Region).

Ergebnis (`birdsville_friction_surface_vs_isotropic.png`): deutlicher
Unterschied. Isotrop = perfekte Kreise. Straßenbasiert = "Finger"
entlang der tatsächlichen Straßen (genau wie beim historischen
Melbourne-Vorbild), plus ein klar abgegrenztes dunkles Gebiet
südöstlich von Birdsville, wo das Straßennetz dünn ist und die
isotrope Annahme die Erreichbarkeit deutlich überschätzt hätte.

## Phase 10: Friction Surface global (statt nur Birdsville)

Nutzerfrage: "Soll ich via Torrent die restliche Welt von OpenStreetMap
laden?" - Antwort: nein. Grund: nur noch 19 GB freier Speicher zu dem
Zeitpunkt, ein vollständiger `planet.osm.pbf` liegt bei ~80+ GB. Und
selbst mit genug Platz wäre der eigentliche Flaschenhals nicht die
Downloadgröße gewesen, sondern dass man sinngemäß für jeden der 3210
Flughäfen einzeln einen Straßengraphen bräuchte, mit Logik zum sauberen
Zusammenfügen an Ländergrenzen - ein Vielfaches des Aufwands der
Birdsville-Demo. Stattdessen empfohlen und (nach Nutzer-Zustimmung)
umgesetzt: ein fertiges, vorgerechnetes globales Friction-Surface-Raster
statt eigenem Routing.

**Datensatz:** Malaria Atlas Project, "2020 motorized friction surface"
(Weiss et al.), via `data.malariaatlas.org` direkt herunterladbar (kein
Overpass-Problem wie bei OSM) - 744 MB entpackt, GeoTIFF, 43200×17400px,
~1 km Auflösung, Werte in Minuten/Meter, Abdeckung 85°N-60°S (keine
Antarktis). Überraschung beim Prüfen: das Raster hat auch über offenem
Ozean gültige, langsame Werte (~3-30 km/h, vermutlich für Fähren
gedacht) statt "nodata" - hätte mit dem bestehenden Häfen-Seemodell
kollidiert (Boots-Shortcuts quer über den Atlantik). Deshalb bewusst auf
reines Land maskiert (`global-land-mask`, wie im Rest des Projekts) und
Wasserpixel komplett aus dem Graphen entfernt statt als langsame Kanten
zuzulassen.

**Rechnerische Machbarkeit:** volle Auflösung wäre ~752 Mio. Pixel
(~3 GB allein als Rohdaten) auf einer 16-GB-RAM-Maschine riskant für
eine globale Multi-Source-Kostendistanz. Auf ~11 km heruntergerechnet
(Faktor 12, Min-Pooling statt Mittelwert, damit dünne schnelle Straßen
beim Vergröbern nicht verschwinden) - immer noch feiner als unsere
H3-Kacheln (~22 km bei Res. 4), aber nur noch ~5,2 Mio. Pixel, davon
~1,55 Mio. Land.

**Umsetzung** (`friction_surface_global.py`, drei Phasen, jede
gecacht):

1. Downsampling (Min-Pooling, ~15s).
2. Graph nur über Landpixeln bauen: 8er-Nachbarschaft, Kantengewicht =
   Reibung × echte Distanz. Erster Versuch hatte einen Vorzeichenfehler
   in der `np.roll`-basierten Nachbar-Verschiebung, der gültige
   Landknoten mit Wasser-Platzhalterindex (-1) verband und beim
   Bauen der Sparse-Matrix crashte - `np.roll` (umschließt Kartenränder
   zirkulär) durch explizites, klar herleitbares Array-Slicing ersetzt.
   Ergebnis: 1.545.928 Knoten, 12.157.216 Kanten.
3. Virtueller Superknoten -> jeder Flughafen-Pixel, Kantengewicht =
   dessen eigene Reisezeit ab London (in Minuten) - derselbe Trick wie
   der virtuelle Ursprungsknoten in `travel_time.py`/`nearest_hub.py`,
   nur über einen Rastergraphen statt einer Radius-Suche. Ein einziges
   `scipy.sparse.csgraph.dijkstra` liefert direkt Flugzeit + echte
   anisotrope Bodenzeit kombiniert - lief in unter einer Sekunde.

Sanity Checks: London-Pixel ~5 Minuten, Birdsville-Pixel exakt 31,69h
(= reine Flugzeit, da praktisch am Flughafen selbst), 98,7 % der
Landpixel erreichbar (Rest: isolierte Inseln ohne Nachbarpixel im Raster).

`friction_surface_map.py` ordnet jeder globalen H3-Landkachel den
nächstgelegenen Friction-Graph-Knoten zu, Wasserkacheln bleiben
unverändert aus der bestehenden Pipeline.

Ergebnis (`h3_travel_times_map_london_friction_surface_land.png`):
deutlich sichtbare dunklere Flecken über Sahara, Amazonas, Zentralasien
und australischem Outback - schwer passierbares Gelände, das die
isotrope Karte als "genauso gut erreichbar wie die Umgebung" gezeigt
hätte. Antarktis fällt auf den nächstgelegenen verfügbaren
Friction-Graph-Knoten zurück (Datensatz endet bei 60°S) - ähnlich
unschön wie das frühere Ground-Speed-Modell dort, aber eine
akzeptierte, dokumentierte Lücke.

## Phase 10b: Moiré-Muster in den H3-Karten

Nutzer bemerkte ein Moiré-Muster in allen H3-Kachel-Karten (feine,
gitterartige Interferenzlinien). Ursache: `matplotlib` glättet
(antialiased) standardmäßig auch bei `edgecolors="none"` die Ränder
jedes einzelnen Polygons im `PolyCollection` - bei hunderttausenden
dicht aneinandergrenzenden Sechsecken erzeugt das sichtbare, sich
überlagernde Kantenartefakte.

Nutzervorschlag ("Hexagone vollflächig ohne Rand füllen", sprich leicht
überlappen lassen) getestet und funktioniert - aber ein Vergleich mit
der einfacheren Alternative `antialiased=False` auf dem `PolyCollection`
zeigte: beide beheben das Problem gleich gut, `antialiased=False` ohne
jede Geometrie-Verzerrung. Umgesetzt in `plot_h3_map.py` und
`friction_surface_demo.py`, alle betroffenen Karten neu gerendert (reine
Render-Schritte, keine Neuberechnung nötig).

## Phase 12: Friction Surface für beliebigen Start-Flughafen

Nutzer bemerkte an der Thule-Karte, dass Grönlands Inlandeis dort
verdächtig gut erreichbar aussah. Ursache gefunden: `map_from_airport.py`
nutzte für Thule/Birdsville nie die Friction Surface, sondern weiterhin
das alte isotrope Kreismodell - die Friction Surface war bis dahin nur
für London fest verdrahtet (`friction_surface_global.py` liest
`config.OUTPUT_CSV`, also immer die London-Flugzeiten).

Statt Thule/Birdsville einzeln zu reparieren, wollte der Nutzer lieber
den ganzen Workflow parametrisierbar machen. Umsetzung:

- `friction_surface_global.py`: `run_dijkstra()` bekommt einen
  `output_path`-Parameter (statt fest `land_travel_minutes.npy`), neue
  Funktion `load_graph()` lädt den gecachten Rastergraphen. Wichtige
  Erkenntnis dabei: der Graph selbst (Knoten, Kanten, Reibungswerte)
  hängt gar nicht vom Start-Flughafen ab - nur die Gewichte des
  virtuellen Superknotens tun das. Ein neuer Ursprung braucht also nur
  einen erneuten Dijkstra-Lauf (< 1s), nicht den ~30s-Graphenbau.
- `map_from_airport.py`: Häfen-/Wasserkacheln-Logik aus `build_h3()` in
  eine eigene `build_sea(land_result)`-Funktion ausgelagert, die eine
  bereits fertige Landkachel-Reisezeit als Eingabe nimmt - unabhängig
  davon, ob die isotrop (Kreismodell) oder via Friction Surface
  zustande kam. Slug-Erzeugung ebenfalls in `slug_for()` ausgelagert.
- Neues Skript `friction_map_from_airport.py`: kombiniert beides -
  `map_from_airport.build_travel_times()` für die Flugzeiten ab dem
  neuen Ursprung, `friction_surface_global.load_graph()` +
  `run_dijkstra()` für die anisotrope Landkachel-Reisezeit, dann
  `map_from_airport.build_sea()` für Häfen/Wasser. Setzt voraus, dass
  `friction_surface_global.py` mindestens einmal gelaufen ist (für den
  gecachten Graphen).

Getestet für Thule und Birdsville: Grönlands Inlandeis zeigt jetzt
korrekt als kaum erreichbar (>48h, gekappte Farbe), nur der schmale
Küstenstreifen um Thule bleibt hell - anders als vorher, wo das ganze
Eisschild wie leicht befahrbares Gelände aussah.

## Phase 14: --galton-Modus (diskrete Farbbänder statt stufenloser Skala)

Nutzeridee: ein `--galton`-Schalter, der die Karte optisch näher an
Galtons Original bringt (diskrete Isochronen-Bänder statt fließendem
Farbverlauf). Vorher gemeinsam durchdacht, bevor implementiert wurde:

- Frage vorab: Wie sehen "zerfranste" Gebiete wie Sahara/Amazonas mit
  Bändern aus? Antwort: schlechter als bei Galton, nicht besser - die
  Friction-Daten rauschen dort schon roh sehr kleinräumig (Flüsse,
  Dünen), harte Bandgrenzen zwischen Nachbarkacheln würden das eher
  betonen als kaschieren. Galtons glatte Ringe kamen von Hand-
  Generalisierung, nicht von den Rohdaten.
- Nutzer-Entscheidung: Glättung und Bänderung an denselben Schalter
  koppeln - ohne `--galton` bleibt alles wie bisher (roh, stufenlos),
  mit `--galton` beides zusammen (Retro-Look).

Umsetzung in `plot_h3_map.py`, durchgereicht durch `map_from_airport.py`,
`friction_surface_map.py`, `friction_map_from_airport.py`:

- `_smooth_values()`: jede Kachel wird über ihre H3-Nachbarn gemittelt
  (`h3.grid_disk(cell, GALTON_SMOOTHING_RINGS)`, Default 1 Ring). Reiner
  Rendering-Schritt - die CSVs bleiben unangetastet, nur das PNG glättet.
- Statt `Normalize` (stufenlose Skala) wird `BoundaryNorm` mit fester
  Bandbreite (`GALTON_BAND_HOURS`, Default 4h) auf eine diskrete
  `ListedColormap` angewandt; der `COLOR_CAP_HOURS`-Deckel bleibt als
  letztes offenes Band (`extend='max'`) erhalten.
- PNG-Dateiname bekommt `_galton`-Suffix, damit nichts überschrieben wird.

Getestet an der London-Friction-Surface-Karte (Res. 4, 288k Kacheln):
~1,5 Minuten Renderzeit (Glättung in einer Python-Schleife über alle
Kacheln ist der Flaschenhals bei dieser Kachelzahl). Ergebnis wie
erwartet: sichtbare 4h-Farbstufen, Sahara/Amazonas bleiben fleckig statt
zu glatten Ringen zu werden - die Vorhersage aus der Diskussion hat
gestimmt.

## Phase 14b: --galton sah trotzdem schlechter aus als ohne - contourf statt Kachel-Glättung

Nutzer-Feedback nach Phase 14: Sieht schlechter aus als ohne `--galton`,
keine echten Bänder wie 1881. Ursache im Nachhinein klar: 1-Ring-H3-
Nachbarschaftsmittel (~7 Kacheln) glättet viel zu lokal - die
Bandgrenzen folgten weiterhin fast demselben Rauschen wie die Rohdaten,
nur in Kachelschritten statt stufenlos. Galtons Bänder sind aber glatte,
zusammenhängende, von Hand generalisierte Flächen - ein grundlegend
anderes Darstellungsprinzip als "viele kleine Polygone einfärben".

Vorher gemeinsam durchdacht (nicht direkt implementiert): Diagnose plus
Lösungsvorschlag, dann Bestätigung durch den Nutzer, dann Umsetzung -
diesmal ausdrücklich in der Reihenfolge angefragt ("noch nichts
implementieren").

Neuer Ansatz in `plot_h3_map.py`:

1. `_build_galton_grid()`: Kachelwerte per Nearest-Neighbor (`BallTree`)
   auf ein reguläres Lat/Lon-Raster übertragen (`GALTON_GRID_DEG`,
   Default 0,25°).
2. Land und Wasser GETRENNT mit `scipy.ndimage.gaussian_filter`
   glätten (`GALTON_SIGMA_DEG`, Default 3°) - sonst verschmiert die
   Küstenlinie. `_nan_gaussian_filter()` dafür: fehlende Werte durch 0
   ersetzen, Werte UND eine 0/1-Gültigkeitsmaske glätten, dann
   durcheinander teilen - der Standard-Trick, damit NaN-Bereiche das
   Ergebnis nicht verwässern statt einfach aus dem gewichteten Mittel
   herauszufallen.
3. `ax.contourf()` mit festen Stundenstufen zeichnet daraus echte,
   glatte Konturflächen (Marching Squares) statt einzelne Kachelkanten
   einzufärben.

`GALTON_SMOOTHING_RINGS` (Kachel-Nachbarschaft) ersetzt durch
`GALTON_GRID_DEG`/`GALTON_SIGMA_DEG` (Rasterauflösung/Gauß-Radius).

Ergebnis: 39s statt 91s Renderzeit (kleines Raster + vektorisierter
Gauß-Filter schlägt die Python-Schleife über 288k Kacheln deutlich) UND
sichtbar bessere Bänder - echte konzentrische Ringe, Sahara/Amazonas
jetzt als kleine, aber saubere lokale Vertiefungen statt Flecken-Rauschen.

## Phase 14c: Bandbreite und Colormap wählbar

Zwei weitere Regler auf Nutzerwunsch, direkt im Anschluss an Phase 14b:

- Bandbreite (bisher fest 4h) über `--band-hours` einstellbar. Namensfrage
  kurz besprochen: Nutzer schlug `--steps` vor, stattdessen `--band-hours`
  gewählt, weil es eine Breite in Stunden ist, kein Zähler - der Name soll
  keine Mehrdeutigkeit über die Einheit offenlassen. Spiegelt außerdem
  `config.GALTON_BAND_HOURS` direkt.
- Farbskala (bisher fest `viridis_r`) über `--cmap` einstellbar - jeder
  gültige `matplotlib`-Colormap-Name, keine feste Auswahlliste. Andere
  perzeptuell gleichmäßige Optionen besprochen (`plasma_r`, `inferno_r`,
  `magma_r`, `cividis_r`) - `plasma_r` kommt Galtons warmer Gelb-zu-Dunkel-
  Palette optisch am nächsten.

Beide Parameter durch `plot_h3_map()` und alle drei Wrapper-Skripte
(`map_from_airport.py`, `friction_surface_map.py`,
`friction_map_from_airport.py`) durchgereicht. Getestet mit
`--cmap plasma_r --band-hours 8`.

## Phase 14d: --cmap galton - Originalfarben statt nur Originalstruktur

Nutzeridee: `--cmap galton` als Sonderwert, der Galtons echtes Farbschema
nachbildet statt nur seine Bänder-Struktur. Nutzer hat dafür einen Scan
von Galtons "Isochronic Passage Chart for Travellers" (1881) samt
Legende gepostet: Grün (<10 Tage) - Gelb (10-20) - Rosa (20-30) -
Blau (30-40) - Braun (>40 Tage).

Wichtige Klarstellung vorab (bevor Farben übernommen wurden): die
10-Tage-Bandbreite selbst NICHT mit übernehmen, nur die Farbstimmung.
Grund: unsere Reisezeiten liegen maximal bei 48h (2 Tage) - Galtons
"<10 Tage"-Kategorie würde bei uns die gesamte Welt in eine einzige
Farbe packen. Bandbreite bleibt weiter unabhängig über `--band-hours`
steuerbar.

Umsetzung: `GALTON_COLORS` in `plot_h3_map.py`, fünf Hex-Werte grün→gelb→
rosa→blau→braun, per Augenmaß vom Scan abgelesen (keine pixelgenaue
Farbextraktion, dafür bräuchte man das Originalbild als Datei statt nur
im Chat gepostet). `cmap_name == "galton"` baut daraus eine
`LinearSegmentedColormap` statt eines matplotlib-Namens nachzuschlagen -
`contourf` diskretisiert die wie jede andere Colormap automatisch in die
per `--band-hours` gewählte Bandzahl.

Getestet mit `--cmap galton --band-hours 8`: gedämpfte Grün-Gelb-Rosa-
Blau-Braun-Abfolge, optisch klar an das Original angelehnt.

## Phase 14e: --labels - Kontinente und Städte beschriften

Nutzerwunsch, wie bei Galtons Original Kontinent- und Stadtnamen
einzuzeichnen. Vorher besprochen (noch nicht implementiert): zwei
getrennte Probleme.

- **Kontinente**: trivial, sieben feste Positionen von Hand, ändern
  sich nie.
- **Städte**: eigene Flughafendaten ungeeignet - `name` ist der
  Flughafenname ("Heathrow"), nicht der Stadtname ("London"), und es
  gibt keine Wichtigkeits-Rangfolge. Stattdessen Cartopy/Natural
  Earth's `populated_places`-Layer (schon für Küstenlinien im Einsatz)
  mit echtem `SCALERANK`-Feld genutzt: 0 = wichtigste ~27 Weltstädte.
  SSL-Zertifikatsfehler beim ersten Download (derselbe bekannte
  macOS-Python-Fehler wie bei den Küstenlinien) - mit `certifi` gelöst.

Nutzer-Entscheidung zur Kopplung: eigener `--labels`-Schalter, nicht an
`--galton` gebunden.

Umsetzung in `plot_h3_map.py`: `CONTINENT_LABELS` (fest), `_load_city_labels()`
(Natural Earth, gefiltert nach `SCALERANK <= CITY_LABEL_MAX_SCALERANK`),
`_draw_labels()` zeichnet beides mit weißer Kontur (`patheffects.withStroke`)
für Lesbarkeit über jeder Bandfarbe. Durchgereicht durch alle drei
Wrapper-Skripte, PNG-Dateiname bekommt `_labels`-Suffix.

Getestet mit `--galton --cmap galton --band-hours 8 --labels`: gut
lesbar, aber vereinzelte Überlappungen in dichten Regionen (Rio/São
Paulo laufen ineinander, Europe/London-Stern, Afrika/Lagos) - kein
Auto-Decluttering (z.B. `adjustText`) eingebaut, nur der
`SCALERANK`-Schwellenwert begrenzt die Dichte. Als bekannte
Einschränkung akzeptiert, kein Blocker.

## Phase 14f: Anthrazit statt Grau/Weiß-Kontur

Nutzerfeedback direkt nach Phase 14e: Galtons Original lebt von scharfen,
dunklen Küstenlinien und Schrift ohne störenden weißen Rand. Umgesetzt:
neue Konstante `ANTHRACITE = "#2b2e33"` in `plot_h3_map.py`, ersetzt das
bisherige Grau (`#888888` Küstenlinien, `#333333`/`#222222` Beschriftung)
überall, `patheffects.withStroke`-Weißkontur bei den Labels entfernt,
Küstenlinien-Strichstärke leicht erhöht (0,5→0,7) für mehr Druckschärfe.

## Phase 14g: Typografie - Playfair Display + kursive Baskerville

Nutzerwunsch: Hauptüberschrift in Playfair Display, Orts-/Kontinentnamen
in kursiver Garamond oder Baskerville, wie beim Original.

Erst geprüft statt angenommen: Baskerville liegt als macOS-Systemschrift
bereits vor (inkl. Kursiv-Schnitt, von matplotlib direkt auffindbar) -
Garamond nicht. Playfair Display ist kein Systemfont, aber ein offener
Google Font (OFL-Lizenz) - als Variable Font heruntergeladen
(`fonts/PlayfairDisplay-Variable.ttf`, nicht committet). matplotlib kann
keine Variable-Font-Achsen ansteuern (würde nur die Default-Instanz,
meist Regular, rendern) - deshalb mit `fonttools varLib.instancer
wght=700` eine echte statische Bold-Instanz erzeugt
(`fonts/PlayfairDisplay-Bold.ttf`, committet, ~195 KB) und die per
`matplotlib.font_manager.fontManager.addfont()` registriert.

Kleiner Bug beim ersten Rendern: Playfair Display hat kein griechisches
Sigma (`σ`) im Zeichensatz - im Titel ("Gauß-σ...") erschien es als
Tofu-Box statt als Fehler. matplotlib macht kein automatisches
Font-Fallback pro Zeichen wie ein Browser. Behoben, indem der Titeltext
das Sigma-Symbol durch Klartext ("Gauß-Radius") ersetzt.

Umsetzung in `plot_h3_map.py`: `TITLE_FONT` (Playfair Display Bold) für
`ax.set_title()`, `LABEL_FONT` (Baskerville, `style="italic"`) für
Kontinent- und Stadtnamen in `_draw_labels()`.

## Phase 14h: Kontinente fett statt kursiv, echte Originalfarben

Zwei Korrekturen vom Nutzer nach Phase 14g:

1. Kontinente sollten fett sein, nicht kursiv (Städte bleiben kursiv).
   `LABEL_FONT` in zwei Schriften aufgeteilt: `CONTINENT_FONT`
   (Baskerville fett) und `CITY_FONT` (Baskerville kursiv).
2. Nutzer hat zehn RGB-Werte direkt von der Originalkarte abgelesen -
   je ein dunkler und ein heller Ton pro Farbe (Grün/Gelb/Rosa/Blau/
   Braun), keine Schätzung per Augenmaß mehr wie in Phase 14d.
   `GALTON_COLORS` von 5 auf 10 Ankerfarben erweitert (dunkel vor hell
   je Farbe, folgt weiter der Legenden-Reihenfolge nah→fern).
   `LinearSegmentedColormap` interpoliert automatisch über beliebig
   viele Bänder, keine Codeänderung an der Farblogik nötig.

Ergebnis: sichtbar gedämpftere, dem Original näherstehende Papierton-
Farbgebung; Kontinent-Beschriftung jetzt klar von Stadtnamen
unterscheidbar (fett vs. kursiv).

## Phase 14i: Mercator als Standardprojektion

Nutzerfrage, ob Mercator wie im Original 1881 machbar wäre - ja, Cartopy
hat `ccrs.Mercator()` fertig. Ein Nebeneffekt vorher erklärt: Mercator
kann die Pole nicht darstellen (Distanz wird unendlich), Karte muss auf
z.B. ±85° Breite begrenzt werden statt `ax.set_global()` - erklärt auch,
warum Grönland/Spitzbergen auf Galtons Original so übergroß wirken
(echte Mercator-Verzerrung, kein Fehler).

Nutzer-Entscheidung: Mercator wird Standard, bisheriges Robinson über
neuen `--robinson`-Schalter weiter wählbar (umgekehrtes Muster zu den
bisherigen Schaltern, wo das Neue optional war).

Stolperstein beim ersten Testlauf: `ax.set_extent([-180, 180, -85, 85])`
lässt Cartopys Mercator-Randberechnung bei exakt ±180° Länge auf NaN
laufen (`ValueError: Axis limits cannot be NaN or Inf`). Behoben mit
einem winzigen Inset (±179.9°) statt der exakten Grenze.

Durchgereicht durch alle drei Wrapper-Skripte, PNG-Dateiname bekommt
`_robinson`-Suffix nur noch, wenn die alte Projektion gewählt wird
(Mercator als neuer Standard bekommt keinen Suffix mehr).

## Phase 14j: Originaler Mercator-Zuschnitt (80°N/60°S) im --galton-Modus

Direkte Nachbesserung zu Phase 14i: Nutzer wollte den exakten,
asymmetrischen Zuschnitt des Originals (80°N/60°S) statt des generischen
symmetrischen ±85°-Werts - aber nur, wenn `--galton` aktiv ist; der
normale Mercator-Modus (ohne `--galton`) bleibt beim symmetrischen Wert.
Ein Zweizeiler in `plot_h3_map.py` (`lat_max, lat_min = (80, -60) if
galton else (85, -85)`), keine neuen Parameter nötig, da `galton` schon
als Argument vorhanden war.

## Phase 14k: --grid - Längen-/Breitengrad-Raster

Nutzer wollte ein Gradnetz alle 20°, in derselben Strichstärke wie die
Küstenlinien - "Gerne auch ein anderer Schalter, der dir passender
erscheint", aber `--grid` passte schon. Dafür zunächst die bislang
hartkodierte Küstenlinien-Strichstärke in eine Konstante
`COASTLINE_LINEWIDTH = 0.7` ausgelagert (statt sie ein zweites Mal als
Magic Number für die Gitterlinien hinzuschreiben), dazu
`GRID_STEP_DEG = 20`. Direkt nach `ax.coastlines(...)`:

```python
if grid:
    ax.gridlines(
        xlocs=range(-180, 181, GRID_STEP_DEG), ylocs=range(-90, 91, GRID_STEP_DEG),
        linewidth=COASTLINE_LINEWIDTH, color=ANTHRACITE, linestyle="-", zorder=2,
    )
```

Funktioniert unverändert unter Mercator und Robinson, da `ax.gridlines()`
projektionsunabhängig in PlateCarree-Koordinaten rechnet. `grid=False`
als neuer Parameter durch alle vier Kartenskripte durchgereicht
(`plot_h3_map.py`, `map_from_airport.py`, `friction_surface_map.py`,
`friction_map_from_airport.py`), Dateiname bekommt bei aktivem Schalter
das Suffix `_grid` (letztes Glied der Suffix-Kette, nach `_robinson`).

## Phase 14l: Dezentere Punkte/Linien (alpha=0.8), Rahmen + Randbeschriftung im --galton-Modus

Drei kleine, direkt aufeinanderfolgende Nachbesserungen am Retro-Look:

1. `--grid`-Linien bekamen `alpha=0.8` statt voller Deckkraft - wirkten
   sonst zu dominant neben den Küstenlinien und Bändern.
2. Dieselbe Überlegung für die Flughafen-/Hafen-Punkte (`ax.scatter(...,
   alpha=0.8)`) - der rote London-Stern bleibt bewusst voll deckend,
   da er der auffälligste Punkt der Karte sein soll.
3. Auf Wunsch des Nutzers (Vergleich mit der Originalkarte): ein
   doppelter Rahmen und Gradzahlen an allen vier Rändern, aber nur im
   `--galton`-Modus. Für die Randbeschriftung reicht cartopys
   `ax.gridlines(draw_labels=True)` - das funktioniert nur bei
   rechteckigen Projektionen (Mercator), nicht bei Robinson, daher
   `draw_labels = galton and not robinson`. Die eigentlichen inneren
   Gitterlinien sollen weiterhin nur bei `--grid` sichtbar sein, auch
   wenn `--galton` ohne `--grid` läuft - gelöst über `alpha=0.8 if grid
   else 0`, statt die Linien ganz wegzulassen: die Tick-Labels an den
   Enden bleiben so erhalten, nur die Linien selbst werden unsichtbar.
   Für den Doppelrahmen genügt die ohnehin vorhandene "geo"-Spine der
   Achse als äußere Linie, dazu ein zweites `Rectangle`, ein paar
   Prozent nach innen versetzt, über `ax.transAxes` gezeichnet (damit
   projektionsunabhängig, funktioniert also gleichermaßen unter
   Mercator und Robinson):

```python
ax.spines["geo"].set_edgecolor(ANTHRACITE)
ax.spines["geo"].set_linewidth(COASTLINE_LINEWIDTH)
ax.add_patch(Rectangle(
    (0.015, 0.015), 0.97, 0.97, transform=ax.transAxes,
    fill=False, edgecolor=ANTHRACITE, linewidth=COASTLINE_LINEWIDTH, zorder=5,
))
```

## Phase 14m: Nackte Randzahlen, gleichmäßiger Doppelrahmen, --title, Papierhintergrund

Vier Nachbesserungen zum Vergleich mit der Originalkarte:

1. **Randbeschriftung ohne °/N/E/S/W**: cartopys Gridliner formatiert
   Längen-/Breitengrade standardmäßig mit Gradzeichen und
   Himmelsrichtung (`LongitudeFormatter`/`LatitudeFormatter`). Ersetzt
   durch einen simplen `FuncFormatter(lambda v, pos: f"{v:g}")` für
   `gl.xformatter`/`gl.yformatter` - reine Zahl, negatives Vorzeichen
   statt S/W, wie in der Vorlage.
2. **Gleichmäßiger Doppelrahmen**: der bisherige Rechteck-Versatz war
   ein fester Achsen-Bruchteil (`0.015` in beide Richtungen), aber die
   Karte ist nicht quadratisch - horizontal und vertikal ergaben sich
   dadurch unterschiedliche Pixelabstände. Jetzt wird der Abstand in
   Punkten festgelegt (`FRAME_GAP_PT = 3.0`) und über die tatsächliche
   Pixel-Bounding-Box der Achse (`ax.get_window_extent()`, dafür ein
   früher `fig.canvas.draw()` nötig - günstig, weil zu diesem Zeitpunkt
   im Code noch keine Konturen/Punkte gezeichnet sind) in
   Achsen-Koordinaten zurückgerechnet. Ergebnis: exakt gleicher Abstand
   in beide Richtungen, dazu insgesamt viel enger als vorher.
3. **`--title`**: Überschrift ist jetzt standardmäßig aus, nur mit
   `--title` sichtbar - die Originalkarte hat schließlich auch keine
   Überschrift *auf* der Karte selbst, sondern nur die Legende unten
   links. `title=False` als neuer Parameter durch alle vier
   Kartenskripte durchgereicht, Dateiname bekommt bei `--title` das
   Suffix `_title` (letztes Glied der Kette).
4. **Papierhintergrund**: `BACKGROUND_COLOR = "#dad4bb"`, mittig
   zwischen den zwei vom Nutzer vorgegebenen RGB-Werten
   rgb(220,212,183) und rgb(215,212,191) - für die gesamte PNG-Fläche
   außerhalb der eigentlichen Kartenfläche (Titelbereich, Legende,
   Colorbar-Rand), nicht nur für Land/Meer. Gesetzt über
   `fig.patch.set_facecolor(...)` und zusätzlich explizit an
   `fig.savefig(..., facecolor=...)` übergeben, da `bbox_inches="tight"`
   beim Speichern neu rendert und sich sonst nicht zwangsläufig auf die
   zuvor gesetzte Figure-Facecolor verlässt.

## Phase 14n: Kleinerer Legenden-Stern, Playfair für Legende/Entfernungsstrahl, --galton10

Drei weitere Nachbesserungen:

1. **Stern in der Legende halbieren**: der Stern auf der Karte selbst
   (`s=200`) soll unverändert auffällig bleiben, nur sein
   Legenden-Symbol soll kleiner sein. `s` bei `scatter()` ist eine
   Fläche, kein Durchmesser - ein Legenden-Handle nachträglich mit
   `handle.set_sizes(handle.get_sizes() / 2)` skalieren hätte die
   Fläche halbiert, aber der Durchmesser wäre dann nur auf ~71%
   geschrumpft (Wurzel aus 0,5), nicht auf 50%. Für einen wirklich
   halb so großen Durchmesser durch 4 statt durch 2 geteilt. Umgesetzt
   über den automatisch aus dem `scatter()`-Aufruf erzeugten
   Legend-Handle, gezielt nur für den Eintrag mit `label=origin_label`
   - die anderen beiden (Flughafen/Hafen) bleiben unangetastet.
2. **Playfair Display für Legende und Entfernungsstrahl-Beschriftung im
   `--galton`-Modus**: `legend.get_texts()` bzw.
   `cbar.ax.xaxis.label` bekommen `set_fontproperties(TITLE_FONT)` -
   dieselbe Bold-Instanz wie die Hauptüberschrift, da für Playfair
   Display ohnehin nur diese eine statische Gewichtsvariante vorliegt
   (siehe Phase 14g).
3. **`--cmap galton10`**: exakt zehn feste Stufen statt einer über
   `--band-hours` gesteuerten, interpolierten Farbskala - eine Farbe
   pro Stufe, keine Zwischentöne. Die zehn RGB-Werte sind identisch mit
   den bereits vorhandenen `GALTON_COLORS` (dieselben Werte, die der
   Nutzer beim ersten Mal von der Originalkarte abgelesen hatte) -
   daher `GALTON10_COLORS = GALTON_COLORS`, aber als eigene, benannte
   Konstante, weil sie hier anders verwendet werden: nicht als
   Stützstellen einer `LinearSegmentedColormap`, sondern direkt als
   `ListedColormap` mit `boundaries = np.linspace(0, COLOR_CAP_HOURS,
   11)` (10 gleich breite Bänder) statt `--band-hours`.
   Ursprünglich als eigener Schalter `--galton10` umgesetzt (der intern
   `galton = True` setzte), auf Wunsch des Nutzers aber korrigiert: es
   soll kein eigener Schalter sein, sondern - konsistent mit `--cmap
   galton` - ein Wert für `--cmap`. Dadurch verhält es sich jetzt auch
   wie jeder andere `--cmap`-Wert: `--cmap galton10` allein wählt nur
   die Palette (wirkt auch ohne `--galton`, da eine `ListedColormap`
   Werte ohnehin automatisch in ihre N Farben einrastet, auch ohne
   `contourf`); erst zusammen mit `--galton` werden daraus zehn feste
   `contourf`-Bänder statt `--band-hours`. Dateiname bekommt weiterhin
   nur `_galton` als Suffix, wenn `--galton` gesetzt ist - wie schon bei
   `--cmap galton` beeinflusst die Farbwahl den Dateinamen nicht.

## Phase 14p: Dateinamens-Kollision und zu enges GALTON_BAND_HOURS behoben

Nutzer meldete: "`--cmap galton10` und `--cmap galton` führen zum
selben zehnfarbigen Schema." Zwei getrennte Ursachen, beide behoben:

1. **Dateinamens-Kollision**: `galton_suffix` hing nur von `galton`
   ab, nicht von `cmap_name` - `--cmap galton` und `--cmap galton10`
   schrieben also unter demselben Dateinamen (`..._galton_labels.png`)
   und überschrieben sich gegenseitig. Wer beide Varianten
   nacheinander testete, sah beim zweiten Mal denselben Dateinamen mit
   dem Inhalt des zweiten Laufs - und hielt das für "beide sehen
   gleich aus". Fix: `galton_suffix = ("_galton10" if cmap_name ==
   "galton10" else "_galton") if galton else ""` in allen drei
   Wrapper-Skripten (`map_from_airport.py`, `friction_surface_map.py`,
   `friction_map_from_airport.py`).
2. **Echtes optisches Problem bei `--cmap galton` mit der
   Standard-Bandbreite**: `GALTON_BAND_HOURS` stand seit der
   allerersten Einführung von `--galton` auf 4 (also 12 Bänder bei
   `COLOR_CAP_HOURS=48`). Jeder Beispiel-Aufruf in diesem gesamten
   Chat hatte aber immer explizit `--band-hours 8` gesetzt (6 Bänder) -
   der Standardwert 4 wurde nie tatsächlich betrachtet. Mit 12 Bändern
   tastet `contourf` die zehn Ankerfarben von `GALTON_COLORS` so dicht
   ab, dass die interpolierte `LinearSegmentedColormap` kaum noch von
   der festen `ListedColormap` aus `--cmap galton10` zu unterscheiden
   ist - die Bänder landen jeweils sehr nah an einem der zehn Anker.
   Fix: `GALTON_BAND_HOURS` von 4 auf 8 geändert - damit liest sich
   `--cmap galton` wieder klar als fünf ineinander übergehende
   Farbfamilien statt als beinahe-diskretes Zehnerschema, ganz ohne
   dass `--band-hours` manuell gesetzt werden muss.

## Phase 14q: Schriftnamen/-größen nach config.py ausgelagert

Nutzer fragte, ob sich `config.py` zu einer `config.yaml` umbauen
ließe, um dort auch Schriftarten/-größen abzulegen. Dagegen
gesprochen: `config.py` enthält Python-Ausdrücke und eng an den Code
gebundene Erklärkommentare, die in YAML entweder verloren gingen oder
nur redundant nachgebildet werden könnten, plus überall
`config.X`-Zugriffe durch `config["X"]` oder einen Wrapper ersetzt
werden müssten - für eine nur von mir selbst editierte Datei ohne
klaren Zusatznutzen. Als Zwischenlösung akzeptiert: die bislang direkt
in `plot_h3_map.py` verstreuten Font-Literale (Dateipfad, Family-Namen,
Schriftgrößen für Titel/Kontinente/Städte, Stadt-Marker-Größe) nach
`config.py` gezogen, ohne den Dateityp zu wechseln:

```python
PLAYFAIR_BOLD_PATH = "fonts/PlayfairDisplay-Bold.ttf"
TITLE_FONT_FALLBACK_FAMILY = "serif"
CONTINENT_FONT_FAMILY = "Baskerville"
CITY_FONT_FAMILY = "Baskerville"
TITLE_FONT_SIZE = 18
CONTINENT_FONT_SIZE = 14
CITY_FONT_SIZE = 7.5
CITY_MARKER_SIZE = 2
```

`plot_h3_map.py` referenziert diese jetzt statt der bisherigen
Literale (`PLAYFAIR_BOLD`-Konstante entfernt, `fontsize=14`/`7.5`/`18`
und `markersize=2` durch `config.*` ersetzt) - Verhalten unverändert,
nur die Werte sitzen jetzt an einer Stelle mit allen anderen
Stellschrauben.

## Phase 14r: --lat-limits (freier Breitengrad-Zuschnitt)

Nutzer wollte den Mercator-Zuschnitt frei wählen können statt nur
zwischen den zwei fest einprogrammierten Werten (85/-85 Standard,
80/-60 unter `--galton`) zu wählen, z.B. `--lat-limits=80,-60`. Kleiner
Parser `parse_lat_limits()` in `plot_h3_map.py` ("80,-60" ->
`(80.0, -60.0)`), als `type=` direkt an `argparse` übergeben. Neuer
Parameter `lat_limits=None` an `plot_h3_map()`: wenn gesetzt, überschreibt
er die bisherige if/else-Fallunterscheidung; wirkt nur im Mercator-Zweig
(unter `--robinson` weiterhin `ax.set_global()`, unverändert). Durch
alle vier Kartenskripte durchgereicht, Dateiname bekommt bei aktiver
Option das Suffix `_lat{nord}_{süd}` (letztes Glied der Kette).

## Phase 14s: Beliebiger Landpunkt als Startpunkt (friction_map_from_point.py)

Nutzer fragte (nur Diskussion zunächst): Ließe sich statt eines
Flughafens ein beliebiger Punkt auf der Landmasse als Start wählen,
über das Friction-Surface-Modell? Antwort: ja, sogar einfacher als der
Flughafen-Fall, weil man die Richtung des ohnehin schon vorhandenen
Musters nur umdreht.

Bisher (friction_surface_global.py): virtueller Superknoten -> alle
Flughäfen (deren Reisezeit ab London schon bekannt ist) -> ein
einziger globaler Dijkstra verteilt Boden-Reisezeit an jede Landkachel
der Welt.

Neu (friction_map_from_point.py), für einen beliebigen Startpunkt: erst
ein einzelner Dijkstra *ab dem Startpunkt* über denselben gecachten
Land-Friction-Graphen zu jedem Flughafen-Pixel - liefert dessen
individuelle Bodenzeit ab dem Punkt (statt der bisher einheitlichen 0h
für "echte" Startflughäfen). Diese Bodenzeiten sind die Kantengewichte
des virtuellen Ursprungsknotens im normalen Flugnetz-Dijkstra - dafür
musste `travel_time.compute_shortest_times()` erweitert werden: das
`origin_iatas`-Argument darf jetzt auch ein Dict `{iata: einstiegsstunden}`
statt nur eine Liste sein, dann bekommt jede virtuelle Kante ihr
individuelles Gewicht statt einheitlich `0.0` (rückwärtskompatibel -
die bestehenden Aufrufer in main.py/map_from_airport.py übergeben
weiter Listen). Danach läuft exakt derselbe Flugnetz-Dijkstra wie immer
und kombiniert "Bodenzeit zum Flughafen + Flug-/Umstiegszeit" in einem
Rutsch. Flughäfen ohne Landverbindung zum Startpunkt (z.B. Inseln)
bekommen unendliche Bodenzeit und fallen automatisch aus den
Kandidaten - `math.isfinite()`-Filter beim Bauen des Gewicht-Dicts,
kein Sonderfall nötig.

Ab dort läuft alles wie in `friction_map_from_airport.py` weiter -
`build_friction_land()` (unverändert) nutzt denselben Friction-Graphen
noch einmal, diesmal wieder in der ursprünglichen Richtung (Flughafen
-> Weltkarte).

Ein Detail brauchte eine kleine Erweiterung von `plot_h3_map()`: der
rote Ursprungs-Stern wurde bisher immer per IATA-Code aus
`travel_times.csv` nachgeschlagen (`origin_iatas`) - für einen
Startpunkt, der kein Flughafen ist, gibt es dort aber keine passende
Zeile. Neuer Parameter `origin_points` (Liste von `(lat, lon)`-Paaren,
Default `None`) umgeht den Nachschlage-Schritt und platziert den Stern
direkt an den übergebenen Koordinaten; bestehende Aufrufer sind
unberührt, da sie `origin_points` gar nicht setzen.

Slug fürs Dateinamensschema: `slug_for_point(lat, lon)` analog zu
`slug_for(iata, name)` aus `map_from_airport.py`, z.B. `48.85, 2.35` ->
`point_48p85_2p35` (Punkt statt `.`, `m` statt `-`, da beides in
Dateinamen zwar technisch erlaubt, aber unschön/verwechselbar wäre).

Aufruf: `pipenv run python friction_map_from_point.py <lat> <lon>
[--label "Name"]`, alle übrigen Schalter (`--galton`, `--cmap`,
`--labels`, `--grid`, `--title`, `--lat-limits`, ...) identisch zu
`friction_map_from_airport.py`.

## Phase 14t: --cmap-Optionen in der Hilfeausgabe dokumentiert

Nutzer fragte, welche Farbpaletten neben `viridis_r`/`galton`/`galton10`
noch möglich sind, und wollte das in `--help` sehen. Der `--cmap`-Hilfetext
in allen fünf Skripten (auch `friction_map_from_point.py`) nennt jetzt
explizit die übrigen perzeptuell gleichmäßigen matplotlib-Paletten
(`plasma_r`, `inferno_r`, `magma_r`, `cividis_r`, jeweils auch ohne
`_r` für umgekehrte Farbrichtung), plus den Hinweis, dass grundsätzlich
jeder matplotlib-Colormap-Name funktioniert - vorher stand dort nur der
allgemeine Verweis auf "eine matplotlib-Colormap".

## Phase 14u: --rivers (große Flüsse wie im Original)

Nutzer wollte, analog zu Galtons Karte, große Flüsse einblenden können,
in derselben Strichstärke wie die Landmassenumrisse. Cartopy bringt mit
`cfeature.RIVERS` (Natural Earth, `rivers_lake_centerlines`, 110m) genau
den passenden Layer bereits mit - bei 110m nur 13 Liniengeometrien
weltweit (Nil, Amazonas, Kongo, Mississippi, Donau, Jangtse, ...), exakt
die "großen, bedeutsamen" Flüsse, keine Nebenflüsse - wie im Original.
Direkt nach `ax.coastlines(...)` eingehängt: `ax.add_feature(cfeature.RIVERS,
edgecolor=ANTHRACITE, linewidth=COASTLINE_LINEWIDTH, zorder=2)`.

Kurzer Verifikations-Umweg: im ersten Testrender (Standardmodus, bunter
viridis-Verlauf als Hintergrund) waren die Flüsse mit bloßem Auge nicht
zu erkennen, was nach einem Bug aussah. Isolierte Nachstellung mit
exakt denselben Parametern (Mercator, dieselbe Extent, anthrazit,
`linewidth=0.7`) auf neutralem Land/See-Hintergrund zeigte den Nil klar
sichtbar - die Geometrien waren also die ganze Zeit korrekt vorhanden
und gezeichnet, nur auf dem bunten, texturierten Kartenhintergrund und
in einem herunterskalierten Screenshot einfach zu unauffällig, um sie
beiläufig zu bemerken. Mit `--galton` (ruhigerer, flächiger Hintergrund)
sind Nil, Amazonas, Kongo und Mississippi klar erkennbar. Kein
Code-Fehler, nur ein Wahrnehmungsproblem beim ersten Hinsehen.

Durch alle vier Kartenskripte durchgereicht, Dateiname bekommt bei
aktivem Schalter das Suffix `_rivers` (letztes Glied der Kette).

## Phase 14v: reverse-geocoder aus dem Pflicht-Install entfernt (Windows-Fix)

Nutzer versuchte, das Projekt unter Windows 11 zum Laufen zu bringen -
`pipenv install` scheiterte an `cykhash` (transitive Abhängigkeit von
`reverse-geocoder`, siehe Phase 10/`ports_loading.py`): erst fehlendes
Cython beim `setup.py egg_info`-Schritt (durch Cython vorinstallieren +
`PIP_NO_BUILD_ISOLATION=1` behoben), danach - selbst mit installierten
Visual-C++-Build-Tools und Developer-Konsole - "Microsoft Visual C++
14.0 or greater is required" beim eigentlichen Kompilieren der
Cython-Extension. Native-Extension-Build-Ketten unter Windows sind
notorisch fragil; nach zwei fehlgeschlagenen Workaround-Runden lohnte
sich eine grundsätzlichere Lösung mehr als ein dritter Reparaturversuch.

Kernbeobachtung: `ports.csv` (LINERLIB) ist ein statischer Datensatz,
der sich nicht mehr ändert - die Longitude/Latitude-Korrektur per
Reverse-Geocoding (siehe `ports_loading.py`, jetzt umbenannt/aufgeteilt)
lief bisher aber bei JEDEM Pipeline-Lauf neu, obwohl das Ergebnis
deterministisch immer gleich ist. Sinnvoller: die Korrektur einmalig
laufen lassen, das Ergebnis als Datei committen, und die eigentliche
Pipeline liest nur noch diese fertige Datei - kein Reverse-Geocoding,
keine `reverse_geocoder`/`cykhash`-Abhängigkeit mehr zur Laufzeit nötig.

Umsetzung:
- Die komplette Korrekturlogik aus `ports_loading.py` in ein neues,
  eigenständiges Skript `fix_ports_coordinates.py` verschoben (liest
  `ports.csv`, schreibt `ports_corrected.csv`, `config.PORTS_CORRECTED_CSV`
  als neuer Pfad). Einmal ausgeführt, Ergebnis committet (333 Häfen,
  korrigiert).
- `ports_loading.py` auf das Nötigste eingedampft: liest nur noch
  `ports_corrected.csv` und wählt die benötigten Spalten - kein
  `reverse_geocoder`/`pycountry`-Import mehr.
- Aufrufer (`map_from_airport.py`, `main_h3.py`) auf
  `config.PORTS_CORRECTED_CSV` umgestellt.
- `Pipfile`: `reverse-geocoder`/`pycountry` von `[packages]` nach
  `[dev-packages]` verschoben - nur noch nötig, wenn `ports.csv`
  irgendwann doch aktualisiert wird und `fix_ports_coordinates.py`
  erneut laufen muss. `pipenv install` (ohne `--dev`) installiert diese
  Gruppe gar nicht mehr, der cykhash-Build entfällt komplett für alle,
  die nur die Karten rendern wollen - Windows-Blocker gelöst, ohne dass
  irgendjemand einen MSVC-Compiler braucht.
- `pipenv lock` neu ausgeführt, Verhalten end-to-end nachgetestet
  (inklusive eines simulierten "reverse_geocoder nicht installiert"-Laufs).

## Phase 14w: --galton-sigma (Glättungsradius parametrisiert)

Nutzer fragte (Diskussion zuerst), ob sich die Glättung für --galton
parametrisieren ließe. Kurz abgewogen: `GALTON_SIGMA_DEG` (Gauß-
Glättungsradius, bestimmt maßgeblich den "verwaschenen" Look) ist ein
sinnvoller Kandidat für einen CLI-Schalter, analog zu `--band-hours`.
`GALTON_GRID_DEG` (Auflösung des Zwischenrasters) dagegen bewusst nicht
freigegeben - reiner Performance/Präzisions-Kompromiss ohne nennenswert
sichtbaren gestalterischen Effekt, bleibt interner Konfigurationswert.

Umsetzung: `--galton-sigma` (Standard `config.GALTON_SIGMA_DEG` = 3.0°)
durch alle fünf Skripte durchgereicht, `_build_galton_grid(covered,
sigma_deg=galton_sigma)` statt des Konstanten-Default. Titel-Detailtext
nutzt jetzt den tatsächlich übergebenen Wert statt der Konstante direkt.
Kein Dateinamens-Suffix (wie bei `--band-hours` schon so gehandhabt).
Getestet mit σ=1.0 (deutlich schärfer/lokaler) und σ=5.0 (deutlich
weicher/verwaschener) gegen den Standard 3.0.

## Phase 14x: Rust-Diskussion → Profiling → 50x schnelleres Hexagon-Rendering

Nutzer fragte (Diskussion), wie aufwendig eine Rust-Portierung wäre und
wie groß der Performancegewinn. Einschätzung: hoher Aufwand, geringer
Nutzen - der Großteil der Rechenlast läuft schon durch kompilierten
Code (scipy Dijkstra, BallTree, h3-py, Shapely/GEOS), und Cartopy/
matplotlib (der eigentliche Rendering-Stack) hätte in Rust kein
reifes Äquivalent. Empfehlung statt Rewrite: gezieltes Profiling des
bestehenden Rendering-Pfads.

Profiling (cProfile über `plot_h3_map()`, Standardauflösung 4, kein
`--galton`, `--dpi 150`) förderte einen konkreten, überraschend
dominanten Befund zutage: **215 Sekunden Gesamtlaufzeit, davon 96% in
Cartopys `transform_path_non_affine`/`project_geometry`/`trace.pyx`.**
Ursache: `PolyCollection(..., transform=ccrs.PlateCarree())` lässt
Cartopy jedes der 282.030 Sechsecke einzeln über den generischen,
Shapely-basierten Trace-Algorithmus reprojizieren (der eigentlich für
beliebige, potenziell Antimeridian-kreuzende Geometrien gedacht ist) -
pro Aufruf mit erheblichem Objekt-Overhead (Shapely-`LineString`-/
`Polygon`-Konstruktion, `numpy.isclose`, etc.), macht bei 282k
Sechsecken 21 Mio. Shapely-Decorator-Aufrufe.

Fix: `_project_polygons()` in `plot_h3_map.py` - projiziert alle
Kachel-Eckpunkte in einem einzigen vektorisierten
`ax.projection.transform_points(ccrs.PlateCarree(), lons, lats)`-Aufruf
statt Polygon für Polygon, und übergibt der `PolyCollection` direkt
bereits projizierte Koordinaten (kein `transform=` mehr nötig - das
ist dann schon der native Datenraum der Achse). H3-Kacheln sind klein
und (dank der bestehenden Antimeridian-Korrektur in
`_cell_polygon_lonlat`) nie selbst-überschneidend, brauchen also nicht
Cartopys generischen, auf beliebige komplexe Geometrien ausgelegten
Trace-Pfad.

Ergebnis: **215s → ~4,1s (Faktor ~52)**, exakt gleiches Bild (577
Pol-Kacheln nicht darstellbar, identisch zum Referenzwert vor dieser
Änderung). Explizit gegen die Datumsgrenze getestet (Fidschi/Neuseeland-
Region) unter Mercator UND Robinson - keine Wraparound-Artefakte, obwohl
der spezialisierte Antimeridian-Trace-Pfad umgangen wird. `--galton`
(nutzt `contourf` statt `PolyCollection`, war nie betroffen) unverändert
getestet, keine Regression.

## Phase 14y: "Dijkstra fertig in 0s" - Zeitmessung korrigiert

Nutzer bemerkte, dass die erste Konsolenausgabe (`friction_map_from_airport.py`/
`friction_map_from_point.py`) immer "Dijkstra fertig in 0s" meldet, obwohl
bis dahin spürbar Zeit vergangen war. Zwei Ursachen, beide in
`friction_surface_global.py::run_dijkstra()`:

1. `t0 = time.time()` saß direkt vor dem eigentlichen
   `dijkstra(big, ...)`-Aufruf - der BallTree-Aufbau (Flughafen-Pixel
   im Friction-Graph finden) und das Zusammenbauen der
   Superknoten-Sparse-Matrix liefen davor unbemerkt und ungemessen mit,
   obwohl sie zusammen ähnlich lang dauern wie Dijkstra selbst (je
   ~0,2-0,8s in einem Testlauf). Gemessen wurde also nur der letzte,
   kürzeste Teilschritt, nicht "bis zu diesem Punkt" wie die
   Nutzererwartung an die erste Ausgabe war.
2. `:.0f}` rundete auf ganze Sekunden - selbst der isoliert gemessene
   `dijkstra()`-Aufruf allein lag mit ~0,4s schon im "wird zu 0"-Bereich.

Fix: `t0` an den Funktionsanfang verschoben (misst jetzt BallTree +
Matrix-Aufbau + Dijkstra zusammen), Formatierung auf `.1f}` erhöht.
Getestet: zeigt jetzt reproduzierbar "Dijkstra fertig in 1.4s" statt
"0s", für beide Aufrufer (`friction_map_from_airport.py`,
`friction_map_from_point.py`).

## Phase 14z: --heli/--jetpack/--james-bond (Kollege will aus Жданиха fliehen)

Diskussion, ausgelöst durch einen (augenzwinkernd formulierten) Wunsch
eines Kollegen nach `--heli`/`--jetpack`, um "virtuell aus Жданиха zu
fliehen". Erste Reaktion: eher Spielerei, da ein reiner
Luftlinien-Modus die interessante, straßenbasierte Struktur der Karte
durch einen langweiligen Kreis ersetzen würde. Nutzer korrigierte den
Denkfehler: Heli/Jetpack sollen nicht das gesamte Modell ersetzen,
sondern nur die Einstiegs-Etappe Startpunkt -> Flughafen - ab dem
erreichten Flughafen läuft das normale, interessante Flugnetz weiter.
Zweiter Einwand des Nutzers: die Reichweiten-Erweiterung (500km Heli +
20km Jetpack = 520km) ist nicht bloß symbolisch, weil in der Nähe
eines Flughafens ("Zivilisation") die Straße oft schon wieder
schneller ist als das langsame Jetpack - das Modell muss also pro
Flughafen zwischen Boden- und Luftroute abwägen, nicht stur eine
Vorfahrtsregel für eine Option erzwingen.

Werte (auf Wunsch an echten Vorbildern orientiert, nicht willkürlich):

- **Heli**: 220 km/h, 500 km Reichweite - Reisegeschwindigkeit
  leichter/mittlerer Hubschrauber (Bell 429, Airbus H145: real
  220-260 km/h), Reichweite konservativ für diese Klasse ohne
  Zwischentanken (Robinson R44 ~560 km, Bell 407 ~650 km).
- **Jetpack**: 100 km/h, 20 km Reichweite - reale treibstoffbetriebene
  Jetpacks (Jetpack Aviation JB-10, Bell Rocket Belt) erreichen
  kurzzeitig ~100+ km/h, halten das aber nur 5-10 Minuten durch;
  100 km/h * 10 min ≈ 17 km, aufgerundet.

Beide in `config.py`: `HELI_SPEED_KMH`/`HELI_RANGE_KM`,
`JETPACK_SPEED_KMH`/`JETPACK_RANGE_KM`.

Umsetzung in `friction_map_from_point.py`:

- `distance.py`: neue `haversine_km_vec()` (vektorisierte Variante von
  `haversine_miles`, in km) - Distanz vom Startpunkt zu allen
  Flughäfen auf einmal statt einzeln.
- `_air_entry_hours(lat, lon, airports_df, heli, jetpack)`: Luftlinie
  je Flughafen zu Reisezeit umgerechnet, `np.inf` außerhalb der
  Reichweite. Bei `heli and jetpack` zusammen: stückweise Funktion -
  bis `HELI_RANGE_KM` mit Heli-Geschwindigkeit, der Rest bis zu
  weiteren `JETPACK_RANGE_KM` mit Jetpack-Geschwindigkeit obendrauf
  (kombinierte maximale Reichweite 520 km), jenseits davon `np.inf`.
- `build_travel_times_from_point()`: `best_hours = np.minimum(ground_hours,
  air_hours)` - je Flughafen gewinnt die schnellere der beiden Optionen,
  genau der vom Nutzer geforderte Wettbewerb statt einer festen
  Rangfolge. Bestätigt im Test (Punkt im australischen Outback):
  Erldunda Airport 4,10h normal (Straße) vs. 0,16h mit `--james-bond`
  (Luftlinie ~35km/220km/h) - Anzahl erreichbarer Flughäfen bleibt
  gleich (3361), nur die Zeiten ändern sich dort, wo Luft tatsächlich
  gewinnt.
- CLI: `--heli`, `--jetpack`, `--james-bond` (Kurzform für beide
  zusammen, `heli=args.heli or args.james_bond` usw.). Dateinamen-Suffix
  `_heli`/`_jetpack`/`_bond` - wichtig: auch in den CSV-Namen (nicht
  nur im PNG), da `--heli` andere `travel_times_df`-Werte erzeugt und
  sonst mit dem Suffix-losen Normal-Lauf kollidieren würde (dieselbe
  Fehlerklasse wie die `--cmap galton`/`galton10`-Kollision aus Phase 14p).

## Phase 14zA: Falscher Alarm bei --james-bond, dann zwei echte Verbesserungen

Nutzer zeigte einen `--james-bond`-Kartenausschnitt aus der Taimyr-
Halbinsel (Жданиха) und vermutete einen Bug: kein sichtbarer Kreis um
den Startpunkt, praktisch der gesamte Rest der Welt unauffällig
"leer". Ausführliche Fehlersuche (cProfile-artige Verifikation von
`contourf`/`extend='max'`/`ListedColormap`, minimale Repro-Fälle mit
`pcolormesh`, `BoundaryNorm`) führte zunächst auf eine echte, reale
Matplotlib-3.11.0-Eigenart (`extend`-Farbwert wird intern als
`5.0e+249` statt eines sinnvollen Werts berechnet) - die sich aber am
Ende als **nicht die Ursache** herausstellte. Der tatsächliche Grund
war simpel: Pixel-Sample bestätigte, dass die "leere" Fläche exakt die
oberste Palettenfarbe (`#d2bea4`, "Braun hell", sowohl bei `galton` als
auch `galton10`) trägt - die liegt nur zufällig fast auf dem
Papierhintergrund (`#dad4bb`) und ist deshalb kaum zu erkennen. Kein
Rendering-Fehler, nur ein Kontrastproblem (noch nicht behoben - Nutzer
hat noch nicht zugestimmt).

Nutzer akzeptierte die Erklärung, brachte aber zwei berechtigte
Beobachtungen, die zu echten Verbesserungen führten:

1. **Kein sichtbarer Radius-Kreis**: Bislang beschleunigte
   `--heli`/`--jetpack` nur die Einstiegs-Etappe Startpunkt ->
   Flughafen (siehe Phase 14z) - die Weltkarte selbst blieb davon
   unberührt, sie zeigt nach wie vor nur die normale
   Friction-Surface-Ausbreitung ab dem jeweils schnellsten erreichten
   Flughafen. Nutzervorschlag: die H3-Kacheln selbst direkt per
   Luftlinie einfärben, kein separates Overlay nötig.

   Umsetzung: `_air_entry_hours()` zu `_air_hours_to(lat, lon,
   dest_lat, dest_lon, heli, jetpack)` verallgemeinert (nimmt jetzt
   beliebige Ziel-Koordinaten-Arrays statt nur `airports_df` - Basis
   für Wiederverwendung). Neue Funktion `_apply_air_reach_to_h3(h3_df,
   lat, lon, heli, jetpack)`: berechnet dieselbe Luftlinie-Formel für
   *jede* H3-Kachel (Land und See) und nimmt `min()` gegen den bereits
   berechneten Wert - wer schneller ist, gewinnt, genau dasselbe
   Prinzip wie beim Flughafen-Einstieg, nur direkt auf Kacheln
   angewendet statt nur auf die eine Einstiegs-Etappe. In `main()`
   direkt nach dem Zusammenführen von `land_result`/`sea_result`
   eingehängt. Ergebnis verifiziert: echter, gut sichtbarer Kreis um
   den Startpunkt (Mercator ist konform, ein realer Umkreis bleibt bei
   jeder Breite ein Kreis, kein Oval), reicht sogar übers offene Wasser
   (Kara-See), da die Luftlinie kein Land braucht - im Gegensatz zur
   alten Friction-Surface-"Finger"-Form, die weiterhin für die
   Bodenroute sichtbar bleibt.

2. **Mehrere erreichte Flughäfen bringen kaum Reichweitengewinn**:
   Bestätigt, Ursache in den Daten: Khatanga (HTG, nur ~20km vom
   Startpunkt, deckungsgleich mit dem 0.09h-Wert aus der CSV) und
   Saskylakh (SYS) haben **null Routen** in `routes.csv` - reine
   Sackgassen im Flugnetz. Der nächste Flughafen mit echten Verbindungen
   (Yakutsk, 76 Routen) liegt außerhalb der 520km-Kombireichweite, also
   bleibt trotz Heli/Jetpack nur die langsame Bodenroute (69+ Stunden)
   übrig, um überhaupt einen nutzbaren Flughafen zu erreichen. Kein
   Bug, sondern eine Eigenschaft des ~2014er OpenFlights-Datensatzes für
   sehr kleine arktische Flughäfen. Führte zur dritten Änderung:

3. **`--airports`/`--ports` statt `--no-hubs`**: Nutzerwunsch, weil das
   unkommentierte Einzeichnen aller Flughäfen (auch nutzloser wie
   Khatanga/Saskylakh) in die Irre führt. Logik umgedreht: standardmäßig
   werden weder Flughafen- noch Hafen-Punkte gezeichnet, zwei
   unabhängige Opt-in-Schalter statt einem gemeinsamen Opt-out.
   `config.SHOW_HUBS` zu `SHOW_AIRPORTS`/`SHOW_PORTS` (beide `False`)
   aufgeteilt, `plot_h3_map()`s `show_hubs`-Parameter zu
   `show_airports`/`show_ports` aufgeteilt (zwei getrennte `if`-Blöcke
   statt einem gemeinsamen), durch alle fünf Skripte durchgereicht.
   Bewusst `--ports` statt `--hubs` gewählt (auf Nachfrage), da "Hub"
   im Code bereits als Oberbegriff für Flughäfen UND Häfen gemeinsam
   verwendet wird (`hub_type`-Spalte, `nearest_hub.py`) - `--hubs`
   speziell nur für Häfen zu verwenden wäre mit dieser bestehenden
   Terminologie kollidiert.

## Phase 14zB: Der echte Bug - Fliegen "verschenkt" die geflogene Strecke

Nutzer prüfte den in Phase 14zA gefixten `--james-bond`-Kartenausschnitt
genauer und widersprach zweimal der Kontrastfarben-Erklärung
("Da stimmt was nicht" / "Nein, das ist auch nicht das Problem") - der
eigentliche Fehler lag nicht im Rendering, sondern in der Modellierung:
"Wann immer James Bond gezwungen ist, Heli und Jetpack aufzugeben,
bewegt er sich nach dem Friction-Surface-Modell weiter. Ergo müsste es
so am Kreisrand weitergehen, oder?"

Ein erster Demo-Fix (`_apply_ground_only_to_h3()`) berechnete die reine
Bodenzeit ab dem Startpunkt selbst - also ganz ohne Anrechnung der
bereits per Heli/Jetpack zurückgelegten Strecke. Nutzer erkannte den
Fehler exakt anhand des Demobilds: "Aber es müsste _überall_ am
Kreisrand auf der Landmasse per Friction-Surface-Modell weitergehen.
Das tut es aber nicht, sondern nur rechts unten. Und der Teil sieht so
aus, als ob er nicht vom Kreisrand aus berechnet worden wäre, sondern
vom Startpunkt aus." - exakt richtig diagnostiziert: `min(ground_ab_start,
air)` vergleicht nur zwei komplette Einzelstrecken, kombiniert sie nie,
und "gewinnt" nur zufällig in der einen Richtung, in der reines
Zufußgehen der gesamten Distanz noch mit der Flugroute mithalten kann.

Fix: `_combo_ground_minutes(lat, lon, graph, node_lat, node_lon, heli,
jetpack)` - derselbe virtuelle-Superknoten-Trick wie in
`friction_surface_global.py` (dort: Flughäfen als gewichtete
Einstiegspunkte für die Welt-Dijkstra), hier: jeder Friction-Graph-Knoten
in Flugreichweite wird ein virtueller Einstiegspunkt mit Kantengewicht
= seine eigene individuelle Flugzeit ab dem Startpunkt
(`_air_hours_to`). Ein einziger Dijkstra über den gesamten Graphen
liefert dann je Knoten das Minimum über alle Einstiegspunkte von
(Flugzeit dorthin + Bodenzeit von dort zum Knoten) - "so weit fliegen,
wie es sich lohnt, dann zu Fuß weiter", radial symmetrisch um den
Reichweitenkreis statt nur in einer zufälligen Richtung. Der Startpunkt
selbst ist immer ein kostenloser Einstiegspunkt (0h Flugzeit), deckt
damit automatisch auch den reinen Fußweg-Fall ganz ohne
`--heli`/`--jetpack` ab (identisch zum ursprünglichen
Einzelquellen-Dijkstra) - kein Sonderfall nötig.

`build_travel_times_from_point()` nutzt das Ergebnis jetzt direkt als
Einstiegszeit je Flughafen (ersetzt die alte separate `min(ground,
air)`-Rechnung komplett - hatte denselben Fehler), `_apply_ground_only_to_h3()`
wurde durch `_apply_combo_ground_to_h3()` ersetzt, die dasselbe
`combo_minutes`-Array (einmal pro Lauf berechnet, von beiden Aufrufern
wiederverwendet) gegen die bisherigen H3-Landkachel-Werte per `min()`
konkurrieren lässt. `_apply_air_reach_to_h3()` (reine Flugzeit, kein
Fußweg) bleibt zusätzlich bestehen, da sie als einzige auch
See-Kacheln einfärben kann (der Friction-Graph ist reines Land).

Verifiziert: Testlauf für Жданиха (72.1525957, 102.3660656) mit
`--james-bond` und `viridis_r`-Farbskala (zur Vermeidung des
Kontrastproblems aus Phase 14zA) zeigt den Übergang jetzt tatsächlich
radial in alle Richtungen (Westen, Süden, Osten - nicht mehr nur
Südosten). Die Weltkarte insgesamt wirkt zudem spürbar besser vernetzt,
da derselbe Fix auch die Flughafen-Einstiegszeiten korrigiert.
Regressionstest mit Paris (48.85, 2.35, ganz ohne `--heli`/`--jetpack`)
bestätigt unverändertes Verhalten im Normalfall (Orly/Le Bourget/CDG
weiterhin korrekt als nächste Flughäfen erkannt).

## Phase 14zC: Vorzeichenlose Gradzahlen, Libre Baskerville statt macOS-Font

Zwei kleine, unabhängige Nachbesserungen im Anschluss an den
Heli/Jetpack-Fix:

1. **Vorzeichenlose Achsenbeschriftung im `--galton`-Modus**: der
   `FuncFormatter` für die Gradzahlen am Kartenrand
   (`plot_h3_map.py`) gab bislang `f"{v:g}"` aus, also z.B. "-60" für
   60° Süd - im Original von 1881 stehen dort nur nackte Zahlen ohne
   Vorzeichen, West/Süd ist allein durch die Randposition erkennbar.
   Fix: `f"{abs(v):g}"`.

2. **Baskerville durch Libre Baskerville ersetzt**: `CONTINENT_FONT_FAMILY`/
   `CITY_FONT_FAMILY` referenzierten bislang `"Baskerville"` als
   matplotlib-Familiennamen - das ist eine macOS-Systemschrift, auf
   anderen Betriebssystemen wäre das Skript lautlos auf einen
   generischen Serifenfont zurückgefallen (Nutzer fragte gezielt nach
   einer gemeinfreien Alternative zum Bundeln). Libre Baskerville
   (Impallari Type, SIL Open Font License) ist eine für genau diesen
   Zweck entwickelte freie Baskerville-Alternative, verfügbar über
   Googles Font-Repository. Wie schon bei Playfair Display liegt dort
   nur eine Variable-Font-Datei vor (`LibreBaskerville[wght].ttf` für
   die Roman-, `LibreBaskerville-Italic[wght].ttf` für die
   Italic-Achse) - matplotlib kann deren Gewichtsachse nicht
   ansteuern, daher per `fonttools varLib.instancer` statische
   Instanzen erzeugt: `LibreBaskerville-Bold.ttf` (wght=700, für
   `CONTINENT_FONT`) und `LibreBaskerville-Italic.ttf` (wght=400, für
   `CITY_FONT`). `config.py` bekam dafür `CONTINENT_FONT_PATH`/
   `CITY_FONT_PATH` (statt `_FAMILY`) plus je einen
   `_FALLBACK_FAMILY` ("serif"), `plot_h3_map.py` lädt die Dateien
   jetzt genau wie schon bei `PLAYFAIR_BOLD_PATH` per
   `fm.fontManager.addfont()` mit Existenzprüfung und Fallback.
   Lizenztext liegt als `fonts/LibreBaskerville-OFL.txt` bei.
   Verifiziert per Regenerierung der Paris-Testkarte: Kontinente/
   Städte weiterhin fett/kursiv im passenden Serifenstil, keine
   sichtbare Verschlechterung gegenüber echtem Baskerville.

## Phase 14zD: friction_map_from_airport.py entfernt (redundant)

Nutzerfrage: `friction_map_from_point.py` kann inzwischen jeden
Startpunkt (nicht nur Flughäfen), also müsste `friction_map_from_airport.py`
eigentlich überflüssig sein. Empirisch geprüft statt nur behauptet:
beide Skripte für denselben Flughafen (THU, Thule Air Base) laufen
lassen - einmal per IATA-Code, einmal mit exakt denselben lat/lon-
Koordinaten - und die resultierenden H3-CSVs zellweise verglichen.
Ergebnis: von 2.016.842 Kacheln ist die maximale Abweichung
2.8e-14h, reines Gleitkommarauschen, keine einzige Kachel weicht um
mehr als 0.1h ab. `friction_map_from_point.py` reproduziert
`friction_map_from_airport.py` also bitgenau, sobald man die
Flughafenkoordinaten selbst als Punkt einsetzt - der Sonderfall
"Startpunkt ist ein Flughafen" ergibt sich automatisch aus dem
allgemeinen Fall, ganz ohne Sonderbehandlung (der Grund: für einen
Flughafen als Startpunkt ist die vom BallTree gefundene nächste
Friction-Graph-Kachel praktisch am selben Ort, die Bodenzeit dorthin
also praktisch 0h - exakt das, was `friction_map_from_airport.py`
für den Ursprungs-Flughafen fest auf 0h gesetzt hatte).

Einzige echte Abhängigkeit: `friction_map_from_point.py` importierte
`build_friction_land()` aus `friction_map_from_airport.py`. Die
Funktion wurde nach `friction_map_from_point.py` verschoben (dort ihr
einziger verbleibender Aufrufer), `friction_map_from_airport.py`
komplett gelöscht. Ein stehengebliebener Kommentarverweis in
`plot_h3_map.py` wurde mitkorrigiert. Nach dem Umbau erneut
verifiziert: `friction_map_from_point.py` mit den THU-Koordinaten
läuft weiterhin fehlerfrei und erzeugt dieselbe Karte.

## Phase 14zE: --band-hours zu --max-hours, galton10 ignoriert es nicht mehr

Nutzer meldete: `--cmap galton10 --band-hours=72` ließ die Farbskala
weiterhin nur bis 48h (`COLOR_CAP_HOURS`) reichen, nicht bis 72h wie
erwartet. Kein Bug im engeren Sinn, sondern exakt das dokumentierte,
aber unerwartete Verhalten: `--band-hours` steuerte bei `--cmap
galton10` nie die Gesamtspanne, sondern wurde dort komplett ignoriert
(zehn feste Stufen fest über `COLOR_CAP_HOURS` gelegt) - Nutzer hatte
`--band-hours` intuitiv als "Reichweite der Skala" verstanden statt
als "Breite jedes einzelnen Bands".

Erster Fixversuch: `galton10` respektiert `band_hours` wörtlich als
Bandbreite (zehn feste Bänder × `band_hours`) - Ergebnis: bei
`--band-hours=72` ging die Skala bis 720h (72×10), nicht bis 72h.
Technisch korrekt gegenüber der ursprünglichen Bedeutung des Parameters,
aber nicht das, was der Nutzer wollte oder erwartet hätte - dem Bild
angesehen und zurückgemeldet, bevor weitergemacht wurde (siehe
"Empirische Verifikationsdisziplin" in früheren Phasen: Ergebnis erst
zeigen, dann fragen, nicht annehmen).

Per Nachfrage geklärt: der Parameter soll umbenannt werden zu
`--max-hours` und direkt als Gesamtspanne der Skala fungieren, nicht
mehr als Bandbreite. Umgesetzt:

- `config.GALTON_BAND_HOURS` (Bandbreite, Default 8) ersetzt durch
  zwei getrennte Konstanten: `config.GALTON_MAX_HOURS` (Gesamtspanne,
  Default 48 - bewusst identisch zum bisherigen `COLOR_CAP_HOURS`,
  damit sich die Standardausgabe nicht ändert) und
  `config.GALTON_NUM_BANDS` (Bandanzahl bei `--cmap galton`, Default
  6 - kein eigener CLI-Schalter, da das eher zum Look der Palette
  gehört als zur Reichweite).
- `plot_h3_map()`: `band_hours`-Parameter zu `max_hours` umbenannt.
  Beide Boundary-Berechnungen (galton und galton10) jetzt einheitlich
  `np.linspace(0, max_hours, N+1)` - bei `galton10` `N = 10` (fest),
  sonst `N = config.GALTON_NUM_BANDS`. Vorher: `galton10` ignorierte
  den Parameter komplett (`np.linspace(0, COLOR_CAP_HOURS, 11)`),
  `galton` nutzte `np.arange(0, COLOR_CAP_HOURS + band_hours,
  band_hours)` - eine an `COLOR_CAP_HOURS` gekoppelte, nicht direkt
  steuerbare Formel.
- CLI-Schalter `--band-hours` zu `--max-hours` umbenannt, in allen vier
  Karten-Skripten (`plot_h3_map.py`, `friction_map_from_point.py`,
  `map_from_airport.py`, `friction_surface_map.py`) sowie der
  `--cmap`-Hilfe und der `--title`-Legendenzeile (zeigt jetzt die
  berechnete Bandbreite `max_hours / GALTON_NUM_BANDS`).

Verifiziert mit dem ursprünglich gemeldeten Aufruf
(`--cmap galton10 --max-hours=72`): Farbskala geht jetzt bis 72h in
zehn gleich breiten 7,2h-Stufen, wie erwartet.

## Phase 14zF: Kupferstich-Retro-Look (nur --galton)

Nutzeridee: den Look von Galtons Originalkarte (Kupferstich-Druck auf
gealtertem Papier) nachempfinden - ein Rausch-Overlay für die
Papierstruktur, und die Linien "kupferstichartig" statt digital
perfekt ziehen. Zunächst als Diskussion beantwortet (Empfehlung:
Rausch-Overlay + Linien-Wackeln als Post-/Pre-Processing-Schritte statt
einer aufwendigeren echten Schraffur-Schattierung), dann auf Zuruf
("Ja, bitte, aber nur für den Schalter --galton") umgesetzt.

**Linien-Wackeln**: kein manuelles Vertex-Jittern nötig - matplotlib
hat dafür bereits `Artist.set_sketch_params(scale, length,
randomness)` eingebaut, denselben Mechanismus, den `plt.xkcd()` intern
nutzt (dort global über `rcParams["path.sketch"]`, hier gezielt pro
Artist über die neue Hilfsfunktion `_sketch()`). Per Kurztest bestätigt,
dass das auch auf Cartopys `FeatureArtist` (Küsten, Flüsse) und
`Gridliner` funktioniert, nicht nur auf einfache matplotlib-Linien.
Parameter empirisch bei Weltkarten-Maßstab kalibriert (mehrere
Testrender verglichen): `scale=1.5, length=20, randomness=2` -
sichtbares Wackeln ohne unleserlich zu werden (ein erster Test mit den
xkcd-Standardwerten `scale=1, length=100` war bei Weltkarten-Maßstab
praktisch unsichtbar, da `length` in Punkten skaliert und die Karte
riesig ist; ein zweiter Test mit `scale=3, length=15` an einem
Europa-Ausschnitt dagegen viel zu unruhig/haarig). Angewendet auf
Küstenlinien, Flüsse (falls `--rivers`), den Gridliner und den
doppelten Kartenrahmen (Spine + Rectangle) - überall dort, wo
`config.py`s Kommentare bereits von "Galtons Original nachempfunden"
sprechen.

**Papier-Rauschen**: als Postprocessing-Schritt übers fertige PNG
(`_apply_retro_noise()`, nach `fig.savefig()`), nicht ins Rendering
selbst eingebaut - einfacher und unabhängig von Projektion/Auflösung/
DPI, wirkt einheitlich auf das ganze zusammengesetzte Bild (Karte,
Legende, Farbskala). Zwei Rauschkomponenten gemischt: ein grobes,
hochskaliertes Rauschfeld (wirkt wie fleckige Papiermarmorierung/
Stockflecken) plus feines Pixel-für-Pixel-Rauschen (Kornstruktur),
additiv auf alle drei RGB-Kanäle addiert. Stärke per Sichtprobe
kalibriert (0.03/0.06/0.10 verglichen) - 0.06 traf die beste Balance
zwischen sichtbarem Alterungseffekt und Lesbarkeit; 0.10 wirkte schon
recht matschig/fleckig.

Alle Parameter (`RETRO_SKETCH_SCALE`/`_LENGTH`/`_RANDOMNESS`,
`RETRO_NOISE_STRENGTH`) leben in `config.py`, bewusst ohne eigene
CLI-Schalter - das gehört zum festen Look von `--galton`, nicht zu
etwas, das pro Kartenlauf angepasst werden soll (dieselbe Überlegung
wie bei `GALTON_NUM_BANDS`). `Pillow` wird jetzt direkt importiert
(vorher nur transitiv über matplotlib installiert) - im `Pipfile`
ergänzt.

Verifiziert: Paris-Testkarte mit `--galton` zeigt sichtbar wackelnde
Küsten-/Gitter-/Rahmenlinien und eine überzeugende Papierkörnung,
ohne Lesbarkeit einzubüßen; dieselbe Karte ganz ohne `--galton`
unverändert (keine Wackellinien, kein Rauschen) - Regression
ausgeschlossen.

**Nachbesserung** auf Nutzerfeedback ("Galton hatte kein Parkinson"):
Drei Punkte.

1. **Zu starkes, rhythmisches statt zufälliges Wackeln**: `randomness=2`
   lag weit unter matplotlibs eigenem Default (16) - je niedriger,
   desto gleichmäßiger/wellenförmiger die Sinuskurve, mit der der
   Sketch-Filter intern arbeitet; hohe Randomness variiert
   Länge/Amplitude stärker und lässt es dadurch unregelmäßiger, weniger
   rhythmisch wirken. Per Sichtvergleich mehrerer Kombinationen neu
   kalibriert: `scale=0.3, length=15, randomness=10` - deutlich
   subtiler als der erste Versuch (`1.5/20/2`), liest sich als Zittern,
   nicht als Welle.

2. **Gitterlinien blieben gerade**: `gl.set_sketch_params()` (auf dem
   `Gridliner`-Objekt selbst) bewirkt nichts - die tatsächlich
   gezeichneten Meridian-/Parallelen-Linien sind eigene interne
   `LineCollection`-Artists (`gl.xline_artists`/`gl.yline_artists`),
   die cartopy erst beim ersten `fig.canvas.draw()` anlegt. Fix: den
   ohnehin schon vorhandenen frühen `fig.canvas.draw()`-Aufruf (bislang
   nur zur Pixel-Vermessung des Doppelrahmens da) mitnutzen, danach
   `_sketch()` auf jeden Artist in `gl.xline_artists`/`yline_artists`
   einzeln anwenden.

3. **Gradzahlen/Legendenzahlen sollen denselben Font wie Städtenamen
   haben**: `gl.xlabel_style`/`ylabel_style` und die Colorbar-
   Tick-Labels (`cbar.ax.get_xticklabels()`) bekommen jetzt
   `fontproperties=CITY_FONT` (dasselbe kursive Libre Baskerville wie
   die Stadtbeschriftungen) statt der matplotlib-Standardschrift.

4. **Legenden-Trennlinien sollen (wenn möglich) auch zittern**:
   stellte sich als eigentlich nicht existent heraus - die
   Farbfeldgrenzen in der Legende wirkten nur durch den Farbkontrast
   wie eine Linie, `cbar.dividers` (eine `LineCollection`) war leer, da
   `drawedges` standardmäßig `False` ist. Für `--galton` jetzt
   `drawedges=True` gesetzt, `cbar.dividers` und `cbar.outline` (der
   Rahmen um die ganze Farbskala) bekommen Farbe/Strichstärke wie die
   übrige Linienführung und werden ebenfalls per `_sketch()`
   gewackelt - vorher unsichtbare, jetzt echte, zitternde Trennlinien.

Verifiziert per erneutem Sichtvergleich (Legenden-Ausschnitt
vergrößert geprüft) und Regressionslauf ohne `--galton`.

## Phase 14zG: Zittern nochmal subtiler, -v für friction_map_from_point.py

Zwei unabhängige Nachbesserungen.

**Sketch-Amplitude weiter reduziert**: `RETRO_SKETCH_SCALE` von `0.6`
auf `0.3` (Phase 14zF) reichte dem Nutzer immer noch nicht, um wie ein
feines Zittern statt einer bewussten Wellung zu wirken. Per
Sichtprobe auf `0.05` reduziert (Länge/Randomness unverändert bei
`15`/`10`) - bei normaler Kartenansicht praktisch nicht mehr als
Wellenlinie wahrnehmbar, nur noch als feine Unregelmäßigkeit,
funktioniert aber weiterhin (kein no-op wie `scale=None`, das den
Sketch-Filter komplett abschalten würde).

**`-v`/`--verbose` nur für `friction_map_from_point.py`**: neue
Hilfsfunktion `_print_config_overview()` gibt vor Beginn der
eigentlichen Berechnung eine Zusammenfassung der für den Lauf
wirksamen Konfiguration aus (Startpunkt, H3-Auflösung/DPI, Projektion,
`--galton`-Einstellungen falls aktiv, aktive Overlays, Heli-/Jetpack-
Geschwindigkeiten/Reichweiten falls aktiv) - fasst zusammen, was sonst
über ein Dutzend einzelne CLI-Flags verstreut wäre. Zusätzlich vor
jedem größeren Arbeitsschritt in `main()` eine `print()`-Zeile
(Flughafendaten laden, Friction-Graph laden, kombinierte Boden-/Luft-
Reisezeiten berechnen, Bodenzeit auf Landkacheln verteilen, See-Kacheln
bauen, CSVs schreiben, Karte zeichnen) - jeweils per `if verbose:`
gewacht, Standardverhalten ohne `-v` bleibt unverändert (nur die
bereits vorher unbedingt ausgegebene "Dijkstra fertig"-Zeile aus
`friction_surface_global.run_dijkstra()` und die finale "Karte
gespeichert unter"-Zeile, beide unabhängig von diesem Schalter). Bewusst
nur in diesem einen Skript, nicht in den anderen drei Karten-Skripten -
explizit so gewünscht.

Verifiziert: Testlauf mit `-v --james-bond --galton ...` zeigt
Konfigurationsübersicht plus alle Zwischenschritte inklusive korrekter
Flughafen-Erreichbarkeitszahl; Lauf ohne `-v` bleibt exakt so knapp wie
zuvor (nur zwei Zeilen Ausgabe).

## Phase 14zH: Legende wie im Original - diskrete Farbfelder statt Farbstrahl

Nutzer zeigte einen Ausschnitt aus Galtons Originalkarte: die Legende
dort ist keine stufenlose Farbskala mit Achse, sondern eine einzelne
knappe Zeile "Explanation of colours." gefolgt von Farbfeld+Bereich je
Kategorie ("Green [Muster] within 10 days. Yellow [Muster] 10-20
days. ..."), darunter kursiv der Publikationshinweis. Wunsch: das für
`--galton` nachbilden (nur dort, der nicht-diskrete Modus behält seinen
gewohnten `fig.colorbar()`), deutlich weniger Höhe als bisher, plus
"Explanation of colours." wörtlich und darunter "Published by heise
Medien, 2026."

Umsetzung: neue Funktion `_draw_galton_color_legend(fig, ax, boundaries,
swatch_colors)` in `plot_h3_map.py`, ersetzt den kompletten
`fig.colorbar(...)`-Aufruf im `if galton:`-Zweig (der `else`-Zweig für
den normalen Modus bleibt unverändert). Da die Legende UNTER der
Kartenachse sitzt, außerhalb von deren eigener Bounding Box, läuft die
Positionierung über Figure- statt Achsen-Koordinaten - x-Positionen
werden sequentiell aus den tatsächlich gerenderten Textbreiten
aufsummiert (`fig.canvas.draw()` + `get_window_extent()` je Textstück,
derselbe Trick wie schon beim Doppelrahmen-Abstand). Für jedes Band:
ein `Rectangle`-Farbfeld (Farbe aus `GALTON10_COLORS` bei `--cmap
galton10`, sonst aus der interpolierten Colormap am Bandmittelpunkt
gesampelt) mit wackelndem Rand (`_sketch()`, passt zum übrigen
Retro-Look), gefolgt von der Bereichsangabe ("0-8h.", ..., "mehr als
48h." fürs letzte, offene Band - passend zu `extend="max"`, das ohnehin
allem darüber dieselbe Farbe gibt). Schriftgrößen/Abstände neu in
`config.py` (`GALTON_LEGEND_FONT_SIZE`, `GALTON_LEGEND_SWATCH_WIDTH_PT`/
`_HEIGHT_PT`, `GALTON_LEGEND_GAP_PT`).

Die alte, unter `--galton` extra aktivierte `drawedges=True`-Behandlung
von `cbar.dividers`/`cbar.outline` (Phase 14zF/14zG) ist damit
hinfällig und entfernt - es gibt für `--galton` gar keinen `cbar` mehr,
an dem es etwas zu wackeln gäbe.

Verifiziert: Testrender mit `--cmap galton` (6 Bänder) und `--cmap
galton10` (10 Bänder, passt trotz mehr Einträgen noch auf eine Zeile,
`bbox_inches="tight"` erweitert die gespeicherte Breite bei Bedarf von
selbst) zeigen die einzeilige Legende wie gewünscht; Regressionslauf
ganz ohne `--galton` bestätigt den unveränderten stufenlosen Farbbalken.

## Phase 14zI: Legenden-Feinschliff - Farbpaare, Zentrierung, Sprache

Vier kleine Nachbesserungen an der neuen Farberklärung aus Phase 14zH,
alle als Reaktion auf den direkten Vergleich mit einem Originalausschnitt.

1. **Farbtöne bei `--cmap galton10` paarweise zusammenfassen**: im
   Original werden nicht zehn Einzeltöne gezeigt, sondern fünf benannte
   Farbfamilien (Grün/Gelb/Rosa/Blau/Braun), von denen jede selbst ein
   dunkel/hell-Paar ist (siehe `GALTON_COLORS`-Reihenfolge in
   `plot_h3_map.py`). `_draw_galton_color_legend()` bekam einen neuen
   `paired`-Parameter (`True` nur bei `--cmap galton10`, von der
   Aufrufstelle anhand von `cmap_name` gesetzt): zwei aufeinanderfolgende
   Farben werden als ein zusammenhängendes Doppelfeld ohne Zwischenraum
   gezeichnet, mit einer gemeinsamen Bereichsangabe (`boundaries[i]` bis
   `boundaries[i+2]`, überspringt also einen Schritt). `--cmap galton`
   (kontinuierlich, `GALTON_NUM_BANDS` Bänder ohne diese Paarstruktur)
   bleibt unpaarig.

2. **Legende und Publikationszeile horizontal zentrieren**: bislang
   linksbündig ab `ax_bbox.x0`. Zweistufiges Vorgehen: alle Text-/
   Feld-Artists werden zunächst bei `x=0` sequentiell platziert (wie
   bisher, nur mit anderem Startpunkt), aus der resultierenden
   Gesamtbreite ein Versatz berechnet (`ax_center - total_width/2`) und
   anschließend jeder Artist um diesen Versatz verschoben
   (`set_x()`/`set_position()` je nach Artist-Typ) - vermeidet ein
   zweites, teureres Renderdurchlauf nur zur Breitenmessung. Die
   Publikationszeile wird separat anhand ihrer eigenen (kürzeren) Breite
   zentriert, nicht an der Legendenzeile ausgerichtet.

3. **Publikationszeile kleiner**: neue Schriftgröße
   `config.GALTON_LEGEND_FONT_SIZE * 2 / 3` statt derselben Größe wie die
   Legende selbst - kein eigener Konfigurationswert, da es sich um ein
   Verhältnis zur Legendengröße handelt, nicht um einen unabhängig
   sinnvollen Wert.

4. **"mehr als" zu "more than"**: passt zur Überschrift "Explanation of
   colours.", die ohnehin schon englisch ist - vorher unpassend
   gemischtsprachig.

Verifiziert: Testrender mit `--cmap galton10` zeigt fünf zentrierte
Doppelfelder mit gemeinsamer Bereichsangabe und "more than 38.4h." als
letztem Eintrag; `--cmap galton` zeigt weiterhin sechs einzelne,
zentrierte Felder; Regressionslauf ohne `--galton` unverändert.

## Phase 14zJ: 80°N/60°S-Zuschnitt jetzt immer Standard

`--lat-limits=80,-60` war bislang nur der Standard unter `--galton`,
sonst galt der generische symmetrische Wert 85/-85. Nutzerwunsch: der
asymmetrische Galton-Zuschnitt soll immer Standard sein, unabhängig von
`--galton`. In `plot_h3_map.py` die bedingte Fallunterscheidung
(`(80, -60) if galton else (85, -85)`) durch einen unbedingten Default
`(80, -60)` ersetzt - betrifft nur den ungenutzten Fall, dass
`--lat-limits` nicht gesetzt ist, `--lat-limits` selbst überschreibt es
weiterhin in beiden Modi. Hilfetexte in allen vier Karten-Skripten
entsprechend angepasst. Nebeneffekt (positiv): schneidet jetzt auch im
Nicht-`--galton`-Modus die stark verzerrte, wenig aussagekräftige
Antarktis größtenteils ab. Wer den alten symmetrischen Zuschnitt will,
kann ihn weiterhin explizit per `--lat-limits=85,-85` anfordern.

Verifiziert: Testrender ohne `--galton` zeigt jetzt denselben 80°N/60°S-
Zuschnitt wie zuvor nur unter `--galton`.

## Phase 14zK: Rahmen umschließt jetzt auch die Gradzahlen, kräftiger

Nutzer zeigte einen Ausschnitt aus Galtons Original: dessen Rahmen ist
sichtbar dicker als die restliche Linienführung UND umschließt die
Gradzahlen am Kartenrand mit, statt sie außerhalb stehen zu lassen. Bei
uns saßen bislang beide Rahmenlinien (Spine + innerer Rectangle, siehe
Phase davor) eng am Kartenrand, mit denselben Vorzeichenlosen
Gradzahlen (Phase 14z...) komplett außerhalb beider Linien.

Zwei Änderungen in `plot_h3_map.py`:

1. Neue Modulkonstante `FRAME_LINEWIDTH = 1.4` (vs. `COASTLINE_LINEWIDTH
   = 0.7`) - beide Rahmenlinien (Spine und äußeres Rectangle) nutzen
   jetzt diese kräftigere Strichstärke statt der für Küsten/Gitter
   verwendeten.

2. Der zweite Rahmen-Rectangle liegt nicht mehr INNERHALB der Spine
   (`FRAME_GAP_PT` nach innen verschoben), sondern AUSSERHALB, groß
   genug, um die Gradzahlen-Labels mit einzuschließen. Da deren
   tatsächliche Ausdehnung (Schriftgröße, Zeichenanzahl, DPI) erst nach
   dem Rendern bekannt ist, wird die Bounding-Box aus der Vereinigung
   der Achsen-eigenen Pixel-Bounding-Box und aller Label-Artists
   (`gl.label_artists`, per `Bbox.union()`) gebildet, plus `FRAME_GAP_PT`
   zusätzlichem Rand darüber hinaus - derselbe "erst rendern, dann
   vermessen"-Trick wie schon beim alten Innenrahmen und der
   Legendenzeile. Unter `--robinson` (keine Gradzahlen, `draw_labels=
   False`) ist `gl.label_artists` leer, der Rahmen liegt dann einfach
   eng an der Achse wie zuvor - kein Sonderfall nötig. Das äußere
   Rectangle braucht `clip_on=False`, da es jetzt legitim über die
   eigene `[0, 1]`-Bounding-Box der Achse hinausragt, um die Labels zu
   erreichen.

Verifiziert: Testrender mit `--galton --labels --grid` zeigt den
kräftigeren Rahmen jetzt außen um die Gradzahlen; `--galton --robinson`
(keine Labels) zeigt weiterhin einen eng anliegenden Rahmen ohne Fehler.

## Phase 14zL: Doppelrahmen zurück, dicker Rahmen bleibt außen; --galton impliziert --rivers/--grid

Zwei Nachbesserungen.

**Rahmen**: der vorherige Umbau (Phase 14zK) hatte versehentlich den
inneren, direkt an der Karte liegenden Doppelrahmen durch die neue
kräftigere Linie ersetzt, statt sie zu ergänzen - der Nutzer wollte
beides: den dünnen Doppelrahmen direkt an der Karte UND den neuen
dickeren, die Gradzahlen umschließenden Rahmen zusätzlich. Fix: Spine
wieder auf `COASTLINE_LINEWIDTH` zurückgesetzt, der alte innere
`Rectangle` (knapp innerhalb der Spine, `COASTLINE_LINEWIDTH`) wieder
eingefügt, der neue äußere `Rectangle` (der die Gradzahlen umschließt,
`FRAME_LINEWIDTH`) bleibt zusätzlich bestehen - macht insgesamt drei
Linien: dünn-dünn direkt an der Karte, dick außen um die Beschriftung.

**`--galton` impliziert `--rivers`/`--grid`**: an einer zentralen Stelle
umgesetzt (`plot_h3_map()` selbst, ganz am Anfang: `rivers = rivers or
galton`, `grid = grid or galton`) statt in jedem der vier CLI-Skripte
einzeln. Wichtige Ergänzung: dieselbe Verknüpfung musste zusätzlich in
den drei aufrufenden Skripten (`friction_map_from_point.py`,
`map_from_airport.py`, `friction_surface_map.py`) VOR der
Dateinamens-Bildung wiederholt werden - die `_rivers`/`_grid`-Suffixe
werden dort anhand der eigenen lokalen `rivers`/`grid`-Variable
gebildet, bevor `plot_h3_map()` überhaupt aufgerufen wird, hätten sonst
trotz tatsächlich gezeichneter Flüsse/Gitter gefehlt (dieselbe
Fehlerklasse wie die schon mehrfach in diesem Projekt behobenen
Dateinamen-Kollisionen). Bei `friction_map_from_point.py` zusätzlich
vor der `-v`-Konfigurationsübersicht angewendet, damit die dort
ausgegebene Overlay-Liste ebenfalls stimmt.

Verifiziert: `-v`-Lauf nur mit `--galton` (ohne `--grid`/`--rivers`)
zeigt "Overlays: labels, grid, rivers" und den korrekten
`_grid_rivers`-Dateinamen; Zoom auf die Kartenecke bestätigt den
dreiteiligen Rahmen; Regressionslauf ganz ohne `--galton` zeigt weiterhin
"Overlays: (keine)" und den unveränderten schlichten Dateinamen.

## Phase 14zM: Legenden-Stundenangaben auf ganze Zahlen gerundet

Bei `--cmap galton10` (zehn Bänder über `max_hours`) fallen die
Bandgrenzen nicht zwangsläufig auf ganze Stunden - beim Standardwert
`max_hours=48` liegt jede Grenze bei einem Vielfachen von 4.8, die
Legende zeigte entsprechend "4.8-9.6h." statt runder Zahlen. In
`_draw_galton_color_legend()` werden die Grenzwerte für die
Beschriftung jetzt per `round()` auf ganze Stunden gerundet
(`lower_h`/`upper_h`) - nur kosmetisch, das tatsächlich für `contourf`
verwendete `boundaries`-Array bleibt exakt, nur der Text der Legende
wird geglättet. `--cmap galton` (Bänder aus `GALTON_NUM_BANDS`, beim
Standardwert bereits ganzzahlig) zeigt dadurch unverändert dieselben
Werte wie zuvor.

Verifiziert: `--cmap galton10` zeigt jetzt "0-10h., 10-19h., 19-29h.,
29-38h., more than 38h." statt der Dezimalwerte; `--cmap galton`
weiterhin unverändert "0-8h., 8-16h., ..., more than 40h.".

## Phase 14zN: Städtenamen-Kollisionsvermeidung per adjustText

Nutzerfrage: können Städtenamen so platziert werden, dass sie sich
weder gegenseitig noch mit Küstenlinien kreuzen? Als Diskussion
beantwortet - Empfehlung `adjustText` (bereits im README als möglicher
nächster Schritt erwähnt), das auch beliebige Artists (z.B. die
Küstenlinien) als Ausweich-Objekte kennt, aber deutlich mehr Aufwand
und nicht-deterministische Läufe bedeutet. Nutzerentscheidung: erstmal
nur Städtenamen untereinander, ohne Küstenlinien-Ausweichen.

Umsetzung: `adjustText` per `pipenv install adjustText` ergänzt (in
`Pipfile` gelandet). In `_draw_labels()` werden die pro Stadt erzeugten
`ax.text()`-Objekte jetzt in einer Liste gesammelt (`city_texts`,
Kontinent-Beschriftungen bleiben davon unberührt) und nach der Schleife
per `adjust_text(city_texts, ax=ax)` gegeneinander verschoben. Wichtige
Erkenntnis beim Quelltext-Check von `adjustText`: es respektiert den
tatsächlichen Transform der übergebenen `Text`-Objekte
(`texts[0].get_transform()`), nicht hart `ax.transData` - da alle
Städtenamen `ccrs.PlateCarree()` als Transform teilen, funktioniert das
korrekt sowohl unter Mercator als auch Robinson, ohne dass die
Kollisionsberechnung selbst geografische Koordinaten kennen müsste.

Verifiziert: Testrender zeigt "Rio de Janeiro"/"São Paulo" (das im
README explizit als Beispiel für überlappende Labels genannte
Regionenpaar) jetzt sauber untereinander statt überlappend, sowohl mit
als auch ohne `--galton`.

## Phase 14zO: Erklärungsbox wie im Original, neue Groteskschrift

Nutzer zeigte den Erklärungstext unten links auf Galtons Original
("ISOCHRONIC PASSAGE CHART FOR TRAVELLERS, showing the shortest number
of days journey from London by the quickest through routes...") und
bat um einen an unser Modell angepassten Text, zunächst nur als
Vorschlag (nicht umsetzen). Vorschlag wurde als "perfekt" bestätigt und
umgesetzt, auf Englisch (passend zu "Explanation of colours."/
"Published by..."), plus eine passende serifenlose Schrift für die
Überschrift.

**Schriftart**: Archivo Black (Omnibus-Type, SIL Open Font License,
`fonts/ArchivoBlack-OFL.txt`) - kräftige Grotesk im viktorianischen
Headline-Stil, deutlicher Kontrast zu den sonst ausschließlich
serifigen Schriften (Playfair Display, Libre Baskerville). Liegt bei
Google Fonts bereits als statische Einzelschnitt-Datei vor, kein
Variable-Font-Umweg wie bei Playfair/Libre Baskerville nötig. Neue
Konfigurationswerte in `config.py`: `EXPLANATION_TITLE_FONT_PATH`,
`_FALLBACK_FAMILY`, `EXPLANATION_TITLE_FONT_SIZE`,
`EXPLANATION_SUBTITLE_FONT_SIZE`, `EXPLANATION_BODY_FONT_SIZE`,
`EXPLANATION_BODY_WRAP_CHARS`. Laden in `plot_h3_map.py` nach demselben
Muster wie TITLE_FONT/CONTINENT_FONT/CITY_FONT (Existenzprüfung +
Fallback-Familie).

**Text**: bewusst nicht Galtons Wortlaut übernommen, sondern
beschrieben, was das Modell tatsächlich berechnet - Stunden statt Tage
(unser Maximum liegt bei ~48h, nicht mehreren Wochen), "the quickest
available routes" statt "as are available without unreasonable cost"
(striktes Dijkstra-Minimum, keine Ermessensfrage), und die einzige im
Modell tatsächlich vorhandene Kulanz-Annahme (`TRANSFER_HOURS` je
Umstieg) statt Galtons vagem "local preparations have been made and
other circumstances are favourable". Schließt mit "In the manner of
Francis Galton, F.R.S. (1881)." als Hommage statt falscher Autorenzeile.
Bei `--heli`/`--jetpack` ein zusätzlicher Satz zur Heli-/Jetpack-
Einstiegsetappe - dafür bekam `plot_h3_map()` zwei neue Parameter
(`heli`/`jetpack`), nur von `friction_map_from_point.py` durchgereicht
(einzige Aufruferin mit diesem Konzept).

**Positionierung**: neue Funktion `_draw_galton_explanation(fig, ax,
origin_label, legend, heli, jetpack)`, direkt über der
Ursprungs-Legende (dem Stern) gestapelt, linksbündig zu deren
`legend.get_window_extent()`-Position - "erst rendern, dann
vermessen"-Trick wie schon bei der Farberklärung und dem Doppelrahmen.
Die Zeilen werden in umgekehrter Lesereihenfolge platziert
(Attribution zuerst, Titel zuletzt), da jede neue Zeile über der
vorherigen erscheint, nicht darunter. Fließtext-Zeilenumbruch per
`textwrap.wrap()` mit fester Zeichenbreite statt pixelgenauer Messung
wie sonst in dieser Datei üblich - für einen dekorativen Absatz
ausreichend, spart den Mehraufwand einer echten Wortumbruch-Messung.
Body-Text und Attribution nutzen `CITY_FONT` (kursives Libre
Baskerville) statt einer vierten Schriftfamilie.

Verifiziert: Testrender zeigt die Box wie erwartet über der
Stern-Legende, mit korrektem `origin_label` und `TRANSFER_HOURS`-Wert;
`--james-bond`-Lauf zeigt den zusätzlichen Heli-/Jetpack-Satz;
Regressionslauf ganz ohne `--galton` zeigt keine Box.

## Phase 14zP: Erklärungsbox-Feinschliff - Kontrast, Schriftschnitte, Zentrierung

Fünf Nachbesserungen an der neuen Erklärungsbox aus Phase 14zO, alle
nach genauem Vergleich mit dem Original.

1. **Hellerer Hintergrund**: neue Konfigurationswerte
   `EXPLANATION_BG_COLOR` (`#f2ede0`, heller als `BACKGROUND_COLOR`
   `#dad4bb`), `_ALPHA` (0.85), `_PAD_PT`. Eine `Rectangle`-Fläche wird
   NACH allen Textelementen anhand der Vereinigung ihrer
   Bounding-Boxen (plus Padding) platziert, mit niedrigerem `zorder`
   als der Text (5 vs. 6) - dieselbe Funktion, die der matplotlib-
   Standard-Legende (Stern) automatisch schon einen hellen Hintergrund
   gibt, hier von Hand nachgebaut.

2. **"FOR TRAVELLERS," mit Serifen**: statt der serifenlosen
   Titel-Groteskschrift jetzt `CONTINENT_FONT` (fettes Libre
   Baskerville) - wie im Original, wo nur die Hauptüberschrift
   serifenlos ist, die Unterzeile aber Serifen hat.

3. **Fließtext nicht mehr kursiv**: neue Schriftdatei
   `fonts/LibreBaskerville-Regular.ttf` (Roman-Achse, wght=400 statt
   700 wie `CONTINENT_FONT_PATH`) - bislang wurden nur Bold- und
   Italic-Schnitte extrahiert, kein regulärer. Neue Konstante
   `config.BODY_FONT_PATH`, geladen in `plot_h3_map.py` als
   `BODY_FONT` nach demselben Existenzprüfung+Fallback-Muster wie die
   anderen Schriften.

4. **"In the manner of ..." fett statt kursiv**: nutzt jetzt ebenfalls
   `CONTINENT_FONT` statt `CITY_FONT` - liest sich eher wie eine
   Signaturzeile.

5. **Alle Zeilen zentriert statt linksbündig, Fließtext im
   "Blocksatz, sonst linksbündig"**: matplotlib hat keinen echten
   Blocksatz (bräuchte Wort-für-Wort-Platzierung mit berechnetem
   Wortabstand) - laut Nutzervorgabe daher der explizit erlaubte
   Rückfall auf linksbündig für die einzelnen Absatzzeilen. Der Absatz
   als Ganzes wird aber trotzdem zentriert: die Body-Zeilen werden
   zunächst unsichtbar bei Position (0,0) erzeugt, nur um ihre
   gerenderte Breite zu kennen (`fig.canvas.draw()` +
   `get_window_extent()`), die breiteste bestimmt den linken Rand des
   gesamten Absatzblocks relativ zur gemeinsamen Mittelachse (der
   horizontalen Mitte der Stern-Legende) - danach werden dieselben
   Artists nur noch per `set_position()` an ihre endgültige Position
   verschoben, statt neu erzeugt zu werden. Titel/Untertitel/
   Attribution sind einzeilig und werden trivial per `ha="center"` auf
   dieselbe Mittelachse zentriert.

**Schriftwahl für die Überschrift überdacht**: Nutzer erlaubte
ausdrücklich eine "noch altertümlichere" Alternative zu Archivo Black.
Ersetzt durch Anton (Google Fonts, OFL) - von viktorianischen/frühen
Plakat-Groteskschriften inspiriert, wirkt im direkten Vergleich weniger
zeitgenössisch als Archivo Black. `fonts/ArchivoBlack-*` wieder
entfernt, `config.EXPLANATION_TITLE_FONT_PATH` zeigt jetzt auf
`fonts/Anton-Regular.ttf`.

Verifiziert: Zoom auf die Box bestätigt alle fünf Punkte (heller
Hintergrund, serifige Unterzeile, aufrechter Fließtext, fette
Attribution, zentrierte Zeilen mit linksbündigem, aber als Block
zentriertem Absatz); Regressionslauf ganz ohne `--galton` zeigt weiterhin
keine Box.

## Phase 15 (geplant): Isochronen-Konturlinien

Auf Basis des kombinierten Land+See-H3-Rasters aus Phase 6 echte
Isolinien zeichnen. Noch nicht umgesetzt.
