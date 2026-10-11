# Status — Samuel og Adam sin tilbudssjekk

Sist oppdatert: 11. oktober 2026

## Hva dette er

En statisk nettside som viser hvilke av familiens faste varer som er på tilbud, hentet fra eTilbudsavis.no.

- `sjekk_tilbud.py` henter tilbud for varene i `config.json` og skriver `site/tilbud.json`.
- `site/index.html` leser `tilbud.json` og viser tilbudene. Ingen server, ingen byggesteg.
- `.github/workflows/oppdater.yml` kjører skraperen to ganger om dagen (ca. kl. 06 og 15) og publiserer `site/` til GitHub Pages.

## Kjøre lokalt

```
python -m pip install -r requirements.txt
python sjekk_tilbud.py                 # henter ferske tilbud (ca. 25 sekunder)
python -m http.server 8765 -d site     # åpne http://localhost:8765
python -m pytest                       # tester (krever pytest)
```

## Legge til eller endre varer

Rediger `config.json`. Hver vare har:

- `sokeord`: det som søkes etter hos eTilbudsavis.
- `krev`: ord som må finnes i tilbudets navn eller beskrivelse. En liste inni lista betyr «ett av disse», f.eks. `["eple", ["juice", "most"]]`.
- `ikke`: ord som utelukker et tilbud, f.eks. `"margarin"` for smør.

## Publisering

Siden ligger på https://thomaxelsen.github.io/Tilbudsaviser/ (GitHub Pages, kilde «GitHub Actions»).

- 11. oktober 2026: første kjøring av «Oppdater tilbud» gikk gjennom. Alle 19 søk svarte fra GitHubs servere, med samme 13 tilbud som lokalt og sted Oslo.
- Den planlagte kjøringen (kl. 06 og 15) er ikke observert ennå; første er 12. oktober om morgenen.

## Gjenstår

- Slett tjenesten hos Render. `Procfile` og `app.py` er fjernet, så den gamle siden der virker ikke lenger.

## Viktige valg

- **Statisk side i stedet for Flask på Render.** Den gamle siden skrapet 19 søk hver gang noen åpnet den (ca. 19 sekunder). Nå hentes dataene i bakgrunnen.
- **Tilbudsdataene committes til repoet** av GitHub Actions når de endrer seg. Det holder den planlagte jobben i live (GitHub skrur av planlagte jobber i repoer uten aktivitet i 60 dager) og gir prishistorikk i git. Konsekvens: kjør `git pull` før du pusher egne endringer.
- **Datakilde:** `<app-data>`-blokkene på søkesiden, ikke JSON-LD. De har alle treff (ikke bare ti), beskrivelse, førpris, kilopris, medlemspris og kjedefarge.
- **Feil skjules ikke.** Kan en vare ikke sjekkes, står det på siden. Feiler mer enn halvparten av søkene, beholdes forrige `tilbud.json`, og jobben i GitHub Actions merkes som feilet. Er dataene eldre enn 36 timer, viser siden et varsel.
- **Sted:** eTilbudsavis bruker Oslo når den ikke kjenner posisjonen. Stedet lagres i `tilbud.json` og vises nederst på siden.

## Kjente begrensninger

- «Lavest kilopris/literpris» vises bare når alle tilbudene på en vare har sammenlignbar enhetspris.
- Soloppgang og solnedgang er regnet med en forenklet formel og kan bomme med noen minutter.
- Filtrene er skjønnsmessige. «Olivero smør & olivenolje» regnes for eksempel som smør; legg `"olivero"` i `ikke` for å fjerne den.

## Ideer som ikke er gjort

Varsling på e-post/push, prishistorikk på siden, visning per butikk, valg av butikker, installerbar app, og å legge til varer fra selve siden.
