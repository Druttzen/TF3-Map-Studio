# Kodgranskning av TF3-Map-Studio — 4 oktober 2026

**Status efter åtgärder 4 oktober:** R1–R12 är rättade i aktuell källkod.
Regressioner täcker dubbel återställningsförlust, verklig överföring från aktuell
OSM-producent, rastermasker, slutna linjära vatten, egna innerområden, låst Skip
vid dataidentitetsfel, sparad XYZ/full modelltransform, ordnade godsfilter,
ändrade TF3-filer/arkiv, skuggad översättningsfunktion och ogiltiga donatorer.
GitHub-arbetsgången ligger nu i repositoryts `.github/workflows/` och omfattar
alla fyra verktyg. Granskningsfynden och radreferenserna nedan beskriver den
ursprungliga koden, före dessa rättningar. Speltesternas begränsningar gäller
fortfarande. LiDAR-funktionen och källkontrollerna beskrivs i
[LIDAR-SOURCES.md](F:/TF3-Map-Studio/TF3-Heightmap-Studio/LIDAR-SOURCES.md).

**Bedömning: REQUEST CHANGES.** Tolv bekräftade fynd: fyra P1 och åtta P2. P1 bör rättas före nästa utgåva eftersom de kan förlora en tidigare export, stoppa överföringen mellan verktygen eller ge fel terräng. P2 gäller avgränsade fel i kartdata, återupptagning, kontroll och modkonvertering.

**Tillförlitlighet:** hög för de beskrivna kodfelen, som har reproducerats eller kontrollerats direkt mot repositorystrukturen. Granskningen bevisar inte hur nya exporter fungerar i en körande TF3-karta.

Granskad version: `ea3a82952eb1e0349e8802095c8e6dc690d67eac`, Mod Converter 0.10.0, i `F:/TF3-Map-Studio`. Granskningen omfattar den aktuella koden, även äldre kod utanför senaste ändringen. Produktionskod, installerade spel, originalmoddar och sparfiler är oförändrade.

## Omfattning

Samtliga 46 Python-moduler i de tre fristående verktygens produktionskod har lästs: nio i OSM-konverteraren, tolv i Heightmap Studio inklusive dess tre kopierade hjälpfiler, och 25 i Mod Converter. Det är sammanlagt 11 797 rader. Startfil, bygg- och paketeringsskript, beroendefiler, resurskontroller, testunderlag och dokumentation har också granskats.

Importer-moddet omfattar 17 Lua-filer, modell- och meshdefinitioner, paketering och resursmanifest. Dess 25 installerbara filer har jämförts byte för byte med kopian som följer med OSM-konverteraren: båda kopiorna är identiska.

De två incheckade `packaging/licenses`-filerna under Heightmap Studios `third-party` har kontrollerats separat: importkod och licensnotiser samt hela SPDX-tabellens struktur, 699 licenser och 79 undantag. Ingen ytterligare defekt bekräftades. Externa biblioteks hela källkod och färdigbyggda programfiler omfattas inte av en egen fullständig kodrevision.

Kontrollerna använder officiell TF2/TF3-dokumentation, OSM:s specifikationer, Rasterios dokumentation och skrivskyddad inspektion av de faktiskt installerade spelresurserna. Där dokumentation och verkliga resursdefinitioner skiljer sig har de installerade definitionerna kontrollerats. Inga okända Workshop-skript har körts.

## Testresultat

| Testsamling | Godkända | Överhoppade |
| --- | ---: | ---: |
| OSM-TF3-Vanilla-Converter | 221 | 0 |
| TF3-Heightmap-Studio | 132 | 0 |
| TF3-OSM-Importer-Mod | 129 | 0 |
| TRF3-Mod-Converter | 639 | 2 |
| **Totalt** | **1 121** | **2** |

De två överhoppade testen gäller Windows-behörighet för symboliska länkar och lokal Tk-initiering. Heightmap-samlingen ger även beroendevarningar. Vissa importerprov finns i båda leveransvägarna; totalsumman är körda tester och ska inte tolkas som 1 121 olika spelfunktioner. Ytterligare riktade prov reproducerar fynden nedan; riktade delmängder av befintliga tester har inte räknats en gång till.

Resurskontrollen hittar importer-moddets 39 vanillaresurser och sex GUI-moduler i TF3. OSM-konverterarens äldre kontroll omfattar 37 resurser och samma sex GUI-moduler. Att resurser finns är inte bevis för lyckad spelimport.

## Bekräftade fynd

| ID | Prioritet | Fel | Primär plats |
| --- | --- | --- | --- |
| R1 | P1 | Misslyckad återställning raderar den gamla exportens enda kopia | [converter.py:538](F:/TF3-Map-Studio/OSM-TF3-Vanilla-Converter/tools/converter.py:538) |
| R2 | P1 | Heightmap Studio avvisar den aktuella OSM-exporten | [settings.py:67](F:/TF3-Map-Studio/TF3-Heightmap-Studio/vendor/settings.py:67) |
| R3 | P1 | Ogiltiga höjdpixlar behandlas som verkliga höjder | [elevation.py:129](F:/TF3-Map-Studio/TF3-Heightmap-Studio/tools/elevation.py:129) |
| R4 | P1 | Slutna linjära vattendrag fyller även torr mark innanför slingan | [hydrology.py:197](F:/TF3-Map-Studio/OSM-TF3-Vanilla-Converter/tools/hydrology.py:197) |
| R5 | P2 | Egna markytor inuti multipolygoner försvinner | [converter.py:369](F:/TF3-Map-Studio/OSM-TF3-Vanilla-Converter/tools/converter.py:369) |
| R6 | P2 | Fel kartidentitet kan hoppas över och kasta bort ett obyggt objekt | [importer.script.lua:540](F:/TF3-Map-Studio/TF3-OSM-Importer-Mod/mod/tf3_osm_importer_mod/content/osm/importer.script.lua:540) |
| R7 | P2 | Objektkontrollen godkänner extrema fel i höjdled | [world_audit.lua:398](F:/TF3-Map-Studio/TF3-OSM-Importer-Mod/mod/tf3_osm_importer_mod/content/osm/world_audit.lua:398) |
| R8 | P2 | Donatorns godsfilter använder fel ordning | [donor_cargo.py:161](F:/TF3-Map-Studio/TRF3-Mod-Converter/src/trf3_mod_converter/donor_cargo.py:161) |
| R9 | P2 | Ändrade TF3-resurser upptäcks inte när en tidigare export återanvänds | [batch.py:375](F:/TF3-Map-Studio/TRF3-Mod-Converter/src/trf3_mod_converter/batch.py:375) |
| R10 | P2 | Lokal Lua-funktion misstolkas som standardöversättning | [lua_metadata.py:67](F:/TF3-Map-Studio/TRF3-Mod-Converter/src/trf3_mod_converter/lua_metadata.py:67) |
| R11 | P2 | Ogiltig TF3-modell kan användas för att komplettera en mod | [native_projection.py:72](F:/TF3-Map-Studio/TRF3-Mod-Converter/src/trf3_mod_converter/native_projection.py:72) |
| R12 | P2 | GitHub kör inte den incheckade testarbetsgången från dess nuvarande plats | [ci.yml:1](F:/TF3-Map-Studio/TRF3-Mod-Converter/.github/workflows/ci.yml:1) |

### R1 — Återställningskopian kan gå förlorad

**Utgångsläge:** användaren ersätter en befintlig Lua-export och dess rapport. Den nya Lua-filen sparas, men rapportens ersättning misslyckas. Om återställningen av den gamla Lua-filen också misslyckas raderar den ovillkorliga städningen återställningskopian. Resultatet blir ny Lua, gammal rapport och ingen kopia av den gamla kartdatan.

**Bevis:** två injicerade `PermissionError` i oförändrad produktionskod gav `previousDatasetStillLive=false` och `previousDatasetRecoverable=false`. Endast `map.lua` och den gamla rapporten återstod. Det vanliga återställningstestet omfattar bara det första felet. Python beskriver ersättningen som en enskild filoperation som kan misslyckas; två ersättningar bildar ingen gemensam transaktion. [Python: os.replace](https://docs.python.org/3/library/os.html#os.replace).

**Rekommenderad ändring:** behåll säkerhetskopian tills sparande eller återställning är bekräftat. Rapportera dess sökväg vid ett återställningsfel. Lägg till ett prov med både spar- och återställningsfel. OSM-nedladdaren har redan ett skydd för detta; återanvänd samma princip i exporten.

### R2 — Överföringen från OSM till Heightmap fungerar inte med aktuell export

Den verkliga, aktuella OSM-konverteraren skriver `settings.features.waterways` och `settings.waterway_width`. Heightmap Studios kopierade inställningskod känner inte igen dessa. [alignment.py:33](F:/TF3-Map-Studio/TF3-Heightmap-Studio/tools/alignment.py:33) avvisar därför rapporten redan när den öppnas.

**Bevis:** en ny export från den aktuella konverteraren ger `Feature selections must use known feature names and true/false values`. Detta inträffar även om OSM-filen inte innehåller vatten. Uppdatering av enbart `waterways` räcker inte: också `waterway_width` avvisas vid [settings.py:65](F:/TF3-Map-Studio/TF3-Heightmap-Studio/vendor/settings.py:65). De befintliga testen exporterar via Heightmaps äldre kopia och missar skillnaden.

**Rekommenderad ändring:** använd ett gemensamt, versionsmärkt format för inställningar och lägg till migrering av äldre rapporter. Testa att en faktisk export från verktyg 1 kan öppnas av verktyg 2. Vattenmetadata ska bevaras; vattenbyggandet ska fortfarande ske i importer-moddet.

### R3 — GeoTIFF-masken förlorar företräde framför nodata

När en GeoTIFF har både ett nodata-värde och en separat giltighetsmask skickar höjdsamplingen det skalära nodata-värdet uttryckligen till reprojekteringen. I den installerade biblioteksversionen kan maskens klassning då åsidosättas.

**Bevis:** en 65 × 65 DEM innehöll lagrade 9999 m i pixlar vars mask säger ogiltig, med nodata=-9999. Nästa DEM innehöll giltiga 200 m. Höjdsamplingen returnerade 9999 m i stället för 200 m med Nearest, Bilinear och Cubic. Även motsatt fall misslyckas: en mask som uttryckligen gör ett nodata-värde giltigt respekteras inte. Kontrollprovet med mask utan skalärt nodata fungerar. Fyndet gäller alltså kombinationen, inte alla maskade höjdfiler. Maskens företräde dokumenteras av [Rasterio: Nodata Masks](https://rasterio.readthedocs.io/en/stable/topics/masks.html).

**Rekommenderad ändring:** använd en reprojekteringsväg som uttryckligen respekterar giltighetsmasken före mosaik och interpolation. Behåll begränsad minnesanvändning för stora filer. Testa båda maskfallen och att senare giltiga DEM-filer fyller verkliga luckor.

### R4 — En kanal i slinga blir en fylld vattenpolygon

Koden väljer polygon när en linje är sluten, oberoende av den beräknade ytklassningen. Därmed blir en sluten `waterway=canal`, uttryckligen märkt `area=no` och `width=1`, ett helt fyllt område.

**Bevis:** provets 20 × 20 m kanalslinga exporterade cirka 399,995 m² grävyta. Den torra mittpunkten, tio meter från kanalen, ingick. Exporten saknade centrumlinje och bredd. OSM definierar `area=no` som linje, och kanalers centrumlinjer skiljs från deras kartlagda vattenytor. [OSM: area](https://wiki.openstreetmap.org/wiki/Key:area), [OSM: canal](https://wiki.openstreetmap.org/wiki/Tag:waterway=canal).

**Rekommenderad ändring:** låt verifierade taggar styra om geometrin är linje eller yta. En sluten linje ska behålla sin centrumlinje och få en zon efter sin bredd, inklusive korrekta anslutningar i slutningen. Testa slingor med `area=no` samt vanliga slutna dammar. Provet bevisar fel exporterad grävyta; den faktiska terrängändringen i TF3 har inte körts.

### R5 — En egen markyta inuti en relation tappas bort

Alla använda multipolygonmedlemmar markeras som redan behandlade. En inre, självständigt märkt `landuse=meadow` i en skogsrelation undertrycks därmed i den efterföljande behandlingen. Provet med växtgenerering avstängd gav noll markytor för ängen med relationen, men två ytor för exakt samma äng utan relationen.

Låt inre medlemmar med egna egenskaper behandlas självständigt, samtidigt som relationens geometri slipper dubbleras. Detta följer [OSM:s regler för multipolygonmedlemmar](https://wiki.openstreetmap.org/wiki/Relation:multipolygon).

### R6 — Skip kan hoppa över ett objekt vid fel dataset

Importerns Skip-funktion kontrollerar accepterade men inte färdigjournalförda objekt, men inte felorsaken eller datasetets identitet. Ett identitetsfel behandlas som ett faktiskt misslyckat byggsteg.

Provet byggde första omgången, ändrade dataset-ID, tryckte Skip, återställde ID och fortsatte. Slutresultatet var 116 av 117 sceneryobjekt, ett överhoppat steg och status `finished`. Markera felorsak uttryckligen, kontrollera dataset-ID även före Skip och tillåt överhoppning endast av ett identifierat bygg- eller förberedelsesteg. Ändra inte markör eller räknare vid ett identitetsfel.

### R7 — Objektkontrollen kontrollerar inte Z

Matchningen kontrollerar modell, XY, rotation och skala, men saknar jämförelse av Z. Provet flyttade ett träd 500 m uppåt och en markör 1000 m nedåt. Kontrollen svarade fortfarande `Saved built objects verified`.

Journalför accepterad Z och jämför alla tre koordinater. Äldre journaler utan höjdbevis ska beskriva kontrollen som begränsad. Fulla transformationer bör kontrolleras för objekt som kan ha andra orienteringar än en enkel rotation runt höjdaxeln. API:t tillhandahåller tredimensionella positioner och fulla transformationer. [TF3: engine API](https://wiki.transportfever3.com/script-doc/api/engine.html).

### R8 — Godsfilter använder fel ordning i donatorlogiken

`donor_cargo._keys` slår ihop inkluderingar och drar bort alla undantag. [native_donors.py:136](F:/TF3-Map-Studio/TRF3-Mod-Converter/src/trf3_mod_converter/native_donors.py:136) lägger också till individuella typer före klassundantagen. TF3:s ordning är klassinkludering, klassundantag, typinkludering, typundantag. En uttrycklig typ kan därför återinkluderas efter att dess klass har undantagits. [TF3: Cargo Type Sets](https://wiki.transportfever3.com/doku.php?id=modding:misc:cargo#cargo_type_sets).

Provet undantog BULK och inkluderade sedan COAL. Den befintliga korrekta `CargoCatalog.resolve_set` behöll kol, men båda donatorfunktionerna tog bort det. Verklig kapacitetskomplettering blockerades trots en passande donator med kapacitet 80. Återanvänd den korrekta gemensamma tolkningen och testa återinkludering vid både matchning och komplettering.

### R9 — Återanvänd export verifieras mot spelsökväg, inte spelinnehåll

Kvittot sparar käll-, utdata- och konverterarversion, men endast sökvägen för TF3. En uppdaterad eller ändrad installation på samma plats ger ändå `Previous export verified` utan en ny kontroll av de refererade vanillaresurserna.

Provet exporterade tillfällig testdata, tog bort den använda resursen `vehicle/train/shared/default_train.trf.lua` ur testinstallationens arkiv och återupptog kön. Den gamla exporten godkändes; en ny export misslyckades korrekt med saknad resurs. Det installerade spelet har inte ändrats. Spara och kontrollera spelversion samt fingeravtryck för använda resursdefinitioner, och kontrollera referenser vid återanvändning. Kvittot ska fortsatt skilja statisk kontroll från speltest.

### R10 — En lokal funktion som heter `_` tolkas fel

Metadata-parsern tillåter lokala funktionsdefinitioner i `data()`, men behandlar varje `_`-anrop som standardöversättning. I provet returnerade en egen lokal `_`-funktion `Changed Name`, medan parsern och den sparade exporten gav `Original Key`. En isolerad Lua-körning av enbart det egenförfattade provet bekräftade skillnaden.

Avvisa skuggade hjälpfunktioner eller verifiera att översättningsanropet verkligen syftar på standardfunktionen. Kör inte godtycklig modkod för att lösa detta. Lua:s lexikala räckviddsregler innebär att den lokala funktionen gäller vid anropet. [Lua: Visibility Rules](https://www.lua.org/manual/5.3/manual.html#3.5).

### R11 — Den snabba donatorläsningen kan godkänna ogiltig native-data

Den snabba läsaren accepterar unary `+`, som Lua saknar. En modell med `lods = { +1 }` i det bortvalda geometriblocket registreras ändå som donator utan diagnostik. Verklig `complete_missing_model` fyllde saknad TF2-vikt till 15,0 ton från denna fil, medan både full statisk parser och Lua avvisade den. Ingen sådan trasig fil har konstaterats bland installerade vanilla-modeller. [Lua: Arithmetic Operators](https://www.lua.org/manual/5.3/manual.html#3.4.1).

Samma registreringsväg vid [native_donors.py:531](F:/TF3-Map-Studio/TRF3-Mod-Converter/src/trf3_mod_converter/native_donors.py:531) accepterar även modellversion 1. Det reproducerade provet använde denna för komplettering trots TF3:s modellformat version 2. [TF3: Resource Types & Structure](https://wiki.transportfever3.com/doku.php?id=modding:general:resourcetypes).

Kontrollera korrekt grammatik och rätt formatversion innan donatorn registreras. Avvisa felaktiga definitioner med diagnostik. Bevara snabb läsning, men låt den inte godkänna språk som den fulla parsern avvisar.

### R12 — Testarbetsgången ligger under fel repositoryrot

Den enda incheckade arbetsgången ligger i `TRF3-Mod-Converter/.github/workflows/ci.yml`. I det samlade repositoryt finns ingen `.github/workflows` i roten. GitHub hittar därför inte arbetsgången för detta repository. GitHub kräver den katalogen under repositoryts rot. [GitHub: Workflow syntax](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax).

Flytta arbetsgången till roten och ställ in rätt arbetskatalog och filsökvägar för varje verktyg. Nuvarande installations- och byggkommandon förutsätter att Mod Converter är repositoryroten. Lägg även till de andra verktygens tester och ett prov av hela överföringen OSM → Heightmap → importerdata. Detta fynd bygger på incheckad struktur och dokumenterad GitHub-logik; ingen fjärrkörning av en ny arbetsgång har gjorts.

## Förbättringar och kvarvarande stöd

**Prioriterad ordning:** säkra tidigare exporter, återställ överföringen mellan OSM och Heightmap, rätta mask- och vattengeometrin, och åtgärda därefter godsfilter, donatorvalidering och återupptagning. Importerns Skip- och objektkontroller samt repositoryts testarbetsgång bör ingå innan nästa utgåva godkänns.

Använd gemensamma implementationer för inställningsformat, godsfilter och sparande med återställning. De bekräftade felen uppstår där flera kodvägar tolkar samma data på olika sätt. Låt importer-moddet ha en kanonisk källkopia och kontrollera automatiskt att båda paketerade kopiorna matchar. De matchar i dag.

Modkonverteraren har fortfarande avsiktliga begränsningar. Godtyckliga skript, funktionella construction-moduler, äldre portaltunnlar och vissa vanliga TF2-gatuegenskaper behöver manuell migrering. Den installerade TF2-standardgatan innehåller `type`, nästlad kontaktledning och signalegenskaper som den nuvarande adaptern avvisar. Fullständigt stöd för alla modklasser är därför ännu inte etablerat. Utöka varje format efter dess dokumenterade och installerade kontrakt och verifiera resursen i TF3 innan den markeras som stödd. [TF3: Tracks and Streets](https://wiki.transportfever3.com/doku.php?id=modding:infrastructure:tracksstreets), [TF3: Bridges and Tunnels](https://wiki.transportfever3.com/doku.php?id=modding:infrastructure:bridgestunnels).

Möjliga ytterligare förbättringar är att undvika upprepad öppning av samma resursarkiv inom en konverteringsomgång, spara DEM-fingeravtryck i projekt för reproducerbarhet och flytta stor biomegenerering från GUI-tråden. Ett litet resursläsningsprov visar minskad overhead med en öppnad arkivläsare, men bevisar ingen viss tidsvinst för hela konverteringen. Största kartornas respons och minnesåtgång behöver mätas innan sådana förbättringar prioriteras.

## Vad spel- och webbfakta faktiskt styrker

De installerade TF2/TF3-ljudhjälparna stämmer med ljudadapterns kontrollerade formler. Installerade brohjälpare stöder de modelluppsättningar som de befintliga adapterproven använder. TF3:s marktexturer stöder både sampler och `indices`-mask; ingen ändring från det ena formatet till det andra behövs enbart för kompatibilitet. [TF2: Sound Sets](https://wiki.transportfever2.com/doku.php?id=modding:soundsets), [TF3: Sound Sets](https://wiki.transportfever3.com/doku.php?id=modding:misc:soundsets), [TF3: Ground Textures](https://wiki.transportfever3.com/doku.php?id=modding:constructions:groundtextures).

`getBaseHeightAt` undantar icke-permanenta terränganpassningar, och konstruktionens `LESS` sänker bara terräng som ligger högre än den angivna ytan. Överlappande vattenomgångar är därför inte i sig bevis för ytterligare 0,5 m grävning per omgång. Något sådant kumulativt fel har inte bekräftats. [TF3: engine API](https://wiki.transportfever3.com/script-doc/api/engine.html), [TF3: Construction Basics](https://wiki.transportfever3.com/doku.php?id=modding:constructions:basics).

Ingen stödd funktion för separat navigerbar havsnivå per sjö har etablerats i denna granskning. Att måla Dirty Water eller använda en vattenmodell ska inte likställas med att skapa verkligt navigerbart sjövatten. Exakt grävdjup, strandpåverkan, utseende, väg- och järnvägsbyggande, fordonsrutter samt sparning och återladdning behöver kontrolleras i en separat TF3-testkarta. Inga verifieringsflaggor för spelimport har höjts under granskningen.

## Reproduktionsunderlag

Proven använder egenförfattade data, tillfälliga testinstallationer och projektets simulerade spelgränser. De ändrar inte användarens installerade spel eller originalmoddar.

| Underlag | Fil |
| --- | --- |
| Återställning, kanalslinga och inre markyta | [OSM-prover](F:/TF3-Map-Studio/work/review_osm_probes_20261004.py) |
| Aktuell OSM-export som Heightmap avvisar | [Rapportfixture](F:/TF3-Map-Studio/work/review_heightmap_current_handoff/current.report.json) |
| Höjdmasker med tre interpolationer | [Prov](F:/TF3-Map-Studio/work/review_heightmap_mask_probe.py), [resultat](F:/TF3-Map-Studio/work/review_heightmap_current_handoff/mask_probe_results.json) |
| Godsfilter och verklig kapacitetskomplettering | [Prov](F:/TF3-Map-Studio/work/review_cargo_set_probe.py), [resultat](F:/TF3-Map-Studio/work/review_heightmap_current_handoff/cargo_set_probe_results.json) |
| Datasetbyte, Skip och kontroll av höjdled | [Importerprov](F:/TF3-Map-Studio/work/review_importer_repro_20261004.py) |
| Skuggad Lua-funktion och ändrad testinstallation | [Prov](F:/TF3-Map-Studio/work/review_mod_converter_probes_20261004.py), [resultat](F:/TF3-Map-Studio/work/review_mod_converter_probes_20261004.json) |
| Ogiltig donator och version 1 | [Donatorprov](F:/TF3-Map-Studio/work/review_donor_repro_20261004.py) |
| Medföljande licensmodul | [Inspektionsresultat](F:/TF3-Map-Studio/work/review_heightmap_current_handoff/packaging_licenses_review.json) |

Detaljerad täckning finns även i [OSM-delrapporten](F:/TF3-Map-Studio/work/review_osm_20261004.md), [Heightmap-delrapporten](F:/TF3-Map-Studio/work/review_heightmap_20261004.md), [importer-delrapporten](F:/TF3-Map-Studio/work/review_importer_20261004.md), [donator-delrapporten](F:/TF3-Map-Studio/work/review_donor_modules_20261004.md) och [resurs-/ljudrapporten](F:/TF3-Map-Studio/work/review_resource_20261004.md). Dessa arbetsfiler ligger lokalt under den ignorerade katalogen `work`; samlingsrapporten är sparad i projektroten.

## Kontroll efter r�ttningarna

- OSM Converter: 234 passerade tester, inklusive bundlade importerfall.
- Heightmap Studio: 150 passerade tester, inklusive LiDAR och faktisk aktuell OSM-export.
- Frist�ende importer: 134 passerade tester.
- Mod Converter: 647 passerade, 2 hoppade �ver f�r Windows-l�nkbeh�righet.
- Totalt 1 165 k�rda testfall i fyra sviter; importerfallen f�rekommer i tv� verktyg och �r inte alla unika.
- Installerade TF3: 39 av 39 vanilla-resurser och 6 UI-moduler hittade.
- Sk�rpt donatorkatalog: 341 modeller godk�nda; 14 avvisade med diagnoser.
- Riktig anonym USGS-h�mtning och �ppna svenska/globala kataloger kontrollerade.
- Spelinstallation och sparfiler har inte �ndrats. Nya h�jd-/vattenfunktioner har inte godk�nts genom ett TF3-speltest.
