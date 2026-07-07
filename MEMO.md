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

## Phase 11 (geplant): Isochronen-Konturlinien

Auf Basis des kombinierten Land+See-H3-Rasters aus Phase 6 echte
Isolinien zeichnen. Noch nicht umgesetzt.
