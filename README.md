# CITY FORGE 0.1.2

Lokální desktopový demonstrátor pro Ubuntu 24.04 x86_64: Electron, React, TypeScript, MapLibre, FastAPI a skutečný SUMO. Po instalaci funguje bez účtů a externích mapových API. Není to kalibrované digitální dvojče.

## Co opravuje tato verze

Dodaný log ukazuje chybějící **systémové programy `sumo` a `netconvert`**, nikoli chybný výsledek simulace. `pip install` je neinstaluje. Python v logu navíc běží jako uživatelský Python 3.14 s jinými knihovnami; zde je doporučeno oddělené prostředí systémového Pythonu 3.12 z Ubuntu 24.04.

* Společné vyhledávání programů pro výpočet i zjištění verzí; volitelný adresář `CITY_SUMO_BIN`.
* Diagnostika `python -m backend.doctor` s nenulovým návratovým kódem a instalačním příkazem při chybě. Desktop ověří nástroje před ohlášením připravenosti backendu.
* Chybějící nástroj stále způsobí selhání běhu, nikdy náhradní výsledek nebo úspěch testu.
* Jednotkový test pádu workeru izoluje zjišťování verzí, aby skutečně dosáhl testovaného pádu. Integrační testy nadále spouštějí reálné SUMO i netconvert, bez přeskakování.
* Opraven chybný testovací příkaz receptu. Python knihovny jsou připnuté na konkrétní vzájemně kompatibilní verze, aby se nepřebírala libovolná nová kombinace Starlette/TestClient z uživatelského prostředí.

Kód ani příkazy zde nejsou deklarovány jako již spuštěné.

## Instalace a oprava prostředí

Příkazy provádějte v kořeni projektu. Potřebujete Ubuntu 24.04, Node.js 22.12+ řady 22 a npm. Instalace vyžaduje internet a sudo, aplikace se spouští jako běžný uživatel.

```bash
sudo apt-get update
sudo apt-get install -y sumo util-linux python3-venv libnss3 libgtk-3-0 libgbm1 libasound2t64
/usr/bin/python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
npm install --no-audit --no-fund
.venv/bin/python -m backend.doctor
```

Používejte `.venv/bin/python`, ne holé `python`, které ve vašem logu ukazuje na jinou instalaci. Jestli už `.venv` patří jinému Pythonu, vytvořte nové prostředí pod jiným názvem a odpovídajícím způsobem upravte příkazy. Není potřeba mazat uživatelské balíčky ani cizí data. Warning TestClient není příčinou uvedených tří selhání; prostředí s uvedenými requirements brání jeho přebírání z jiné instalace.

Při nestandardní instalaci SUMO:

```bash
export CITY_SUMO_BIN=/opt/sumo/bin
.venv/bin/python -m backend.doctor
```

Tento adresář musí obsahovat oba spustitelné soubory `sumo` i `netconvert`. Bez této proměnné se používá PATH. `prlimit` se vždy hledá v PATH. Pokud proměnná ukazuje na chybný adresář, opravte ji nebo použijte `unset CITY_SUMO_BIN`. Python modul `sumo` není náhradou binárek.

## Testy a sestavení

```bash
.venv/bin/python -m backend.doctor && .venv/bin/python -m pytest -q tests
npm run build
```

Testy reálných simulací nejsou při chybějících závislostech přeskočeny. Přímý příkaz pytest je také podporován a při chybě selže s návodem. Diagnostika před ním poskytne přehlednější vysvětlení. Testuje se reprodukovatelnost, objížďka a nulový průjezd uzavřeným úsekem, nedosažitelnost, validace, snímek vstupů, export CSV, zrušení procesu i běhu, zotavení po přerušení, chybějící nástroje a selhání workeru. Integrační testy vyžadují nainstalované SUMO; test pádu stavového automatu je záměrně jednotkový. Chyba vede k nenulovému kódu. GUI není automatizovaně testováno.

Build provádí kontrolu TypeScriptu, Vite build do `dist/` a vytváří nepodepsanou distribuci `release/linux-unpacked/`. Na headless runneru není třeba desktop spouštět. Žádné publikování či nasazení se neprovádí.

## Spuštění a dodání

```bash
CITY_FORGE_PYTHON="$PWD/.venv/bin/python" ./release/linux-unpacked/city-forge
```

Alternativa po buildu: `CITY_FORGE_PYTHON="$PWD/.venv/bin/python" npm start`. Nepoužívejte root ani nevypínejte Electron sandbox. Bez nastavení interpretu desktop zkusí `/usr/bin/python3`, který nemusí mít potřebné knihovny.

Předejte celý `release/linux-unpacked/`, README a requirements.txt. Na cílovém Ubuntu nainstalujte systémové závislosti, vytvořte tam vlastní virtuální prostředí a nastavte absolutní cestu `CITY_FORGE_PYTHON`. Virtuální prostředí nepřenášejte mezi počítači. Jde o rozbalenou distribuci, ne samostatný AppImage či DEB; linuxová binárka není pro Windows.

Vyberte úsek v mapě nebo seznamem, násobek poptávky a 1–3 různá semínka. Worker počítá základ a uzavírku pro každé semínko. Lze zrušit výpočet, porovnat metriky a exportovat CSV nebo HTML s dohledatelností. Parametry uloženého výsledku jsou odlišeny od výběru pro další běh.

## Import a model

Importujte JSON podle `backend/demo.json`, do 256 KiB: metadata zdroje, licence, ISO datum, IANA časové pásmo, `LOCAL_METRES`, uzly, orientované úseky a rychlosti v m/s, počátek, nemocnici, počet automobilů a seřazené jedinečné odjezdy autobusů v sekundách. Nejvýše 100 uzlů, 250 úseků, 600 automobilů v základu, 40 odjezdů. V základu musejí být všechny uzly dosažitelné z počátku. Data ukázky jsou vlastní syntetická data CC0-1.0, nikoli skutečná Praha. Převod do MapLibre je schematický, délky simulace vycházejí z metrických souřadnic.

Experiment trvá 900 sekund, uzavírka celý interval. Automobily odjíždějí rovnoměrně náhodně v prvních 600 s. Jedna OD dvojice, jednopruhové úseky, cesta vybraná podle délky/rychlosti před odjezdem, bez dynamické rovnováhy a ručně povolených objížděk. Teleportace v SUMO je vypnutá. Autobusy jsou vozidla bus bez zastávek a pobytů, nikoli úplný GTFS provoz.

Jízdy a stání se průměrují jen přes dokončená vozidla: kontrolujte nedokončené a nedosažitelné cesty. Nedosažitelná doba je null, ne nula. Fronta je maximum `queueing_length` na jednom pruhu přes čas, ne součet sítě. Min–max přes semínka není interval spolehlivosti. Citlivost lze ručně zkoumat novým během s jinou poptávkou.

Nemocnice je analytická nejkratší volná cesta bez kolon, přednosti, křižovatkových zdržení, dostupnosti a výjezdu posádky. Nikdy není podkladem pro skutečné vysílání záchranářů.

## Ukládání a provozní ochrany

Loopback API má náhodný token a rezervovaný port, renderer omezené IPC bez Node.js. Procesy se spouštějí polem argumentů bez shellu. `prlimit` omezuje každý výpočetní proces na 1.5 GiB adresního prostoru, 45 s CPU, 50 s reálného času a 32 MiB na výstupní soubor. Zrušení ukončuje procesní skupinu. Nejde o kontejner pro nedůvěryhodný kód; celková disková kvóta není implementována.

Běhy jsou v Electron userData/runs, obvykle `~/.config/city-forge/runs`. Atomicky zapisovaný job.json uchovává snímek vstupů, kontrolní součty vstupů/scénáře, model, semínka, parametry a verze nástrojů. Podadresáře uchovávají skutečné XML a logy. Dokončení nastává až po úspěchu všech dvojic. Přerušené běhy se po restartu označí jako selhané. Desktop povoluje jedinou instanci.

Limit je 20 uložených experimentů. Při zavřené aplikaci je ručně archivujte; software cizí data automaticky nemaže. Pro reprodukovatelnost uchovejte také vytvořený package-lock.json, pip freeze, OS a verze SUMO. Npm rozsahy a systémový SUMO nejsou neměnný environment lock. Výkon na 8 GB notebooku nebyl změřen.

Záměrně nedodáno: PostGIS, importy OSM/GTFS/CSV/GeoJSON, měřené intenzity, kalibrace, více OD dvojic, nastavitelné intervaly, časová mapa výsledků, instalační balíček se systémovými závislostmi. Aplikace neovládá městskou infrastrukturu.
