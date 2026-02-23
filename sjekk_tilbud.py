"""
Tilbudssjekker — Sjekker ukentlige tilbud fra norske dagligvarebutikker.

Bruker eTilbudsavis.no som datakilde for å finne tilbud på spesifikke varer.
Kjør: python sjekk_tilbud.py
"""

import io
import json
import re
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

# Sikre UTF-8 output på Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import requests
from bs4 import BeautifulSoup

SCRIPT_DIR = Path(__file__).parent
CONFIG_FILE = SCRIPT_DIR / "config.json"
BASE_URL = "https://etilbudsavis.no/soek/"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


def last_config():
    """Leser config.json og returnerer produkter og butikkliste."""
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        config = json.load(f)
    return config["produkter"], [b.lower() for b in config["butikker"]]


def hent_tilbud(sokeord: str) -> list[dict]:
    """Henter tilbud fra eTilbudsavis for et gitt søkeord.

    Returnerer en liste med tilbud (dict med navn, pris, butikk, etc.)
    """
    url = BASE_URL + urllib.parse.quote(sokeord)
    headers = {"User-Agent": USER_AGENT}

    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"  Feil ved henting av '{sokeord}': {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    tilbud = []

    # Metode 1: Parse schema.org JSON-LD data
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string)
        except (json.JSONDecodeError, TypeError):
            continue

        if data.get("@type") != "SearchResultsPage":
            continue

        main_entity = data.get("mainEntity", {})
        items = main_entity.get("itemListElement", [])

        for item in items:
            offer = item.get("item", {})
            seller = offer.get("seller", {})
            tilbud.append({
                "navn": offer.get("name", ""),
                "pris": offer.get("price"),
                "butikk": seller.get("name", ""),
                "gyldig_fra": offer.get("validFrom", ""),
                "gyldig_til": offer.get("validThrough", ""),
                "bilde": offer.get("image", ""),
                "url": offer.get("url", ""),
            })

    # Metode 2: Søk etter JSON-data i vanlige script-tagger (fallback)
    if not tilbud:
        for script in soup.find_all("script"):
            if not script.string:
                continue
            # Ser etter Next.js-data eller lignende app-state
            match = re.search(r'"itemListElement"\s*:\s*\[(.*?)\]', script.string, re.DOTALL)
            if match:
                try:
                    items_str = "[" + match.group(1) + "]"
                    items = json.loads(items_str)
                    for item in items:
                        offer = item.get("item", item)
                        seller = offer.get("seller", {})
                        tilbud.append({
                            "navn": offer.get("name", ""),
                            "pris": offer.get("price"),
                            "butikk": seller.get("name", ""),
                            "gyldig_fra": offer.get("validFrom", ""),
                            "gyldig_til": offer.get("validThrough", ""),
                            "bilde": offer.get("image", ""),
                            "url": offer.get("url", ""),
                        })
                except json.JSONDecodeError:
                    continue

    return tilbud


def filtrer_butikker(tilbud: list[dict], butikker: list[str]) -> list[dict]:
    """Filtrerer tilbud til kun de butikkene brukeren er interessert i."""
    return [
        t for t in tilbud
        if t["butikk"].lower() in butikker
    ]


def formater_dato(iso_str: str) -> str:
    """Konverterer ISO-datostreng til lesbart norsk format."""
    if not iso_str:
        return "?"
    try:
        dt = datetime.fromisoformat(iso_str.replace("+0000", "+00:00"))
        måneder = [
            "", "jan", "feb", "mar", "apr", "mai", "jun",
            "jul", "aug", "sep", "okt", "nov", "des"
        ]
        return f"{dt.day}. {måneder[dt.month]}"
    except (ValueError, IndexError):
        return iso_str[:10]


def formater_pris(pris) -> str:
    """Formaterer pris til norsk format."""
    if pris is None:
        return "?"
    try:
        pris_float = float(pris)
        if pris_float == int(pris_float):
            return f"{int(pris_float)} kr"
        return f"{pris_float:.2f} kr".replace(".", ",")
    except (ValueError, TypeError):
        return str(pris)


def ukenummer() -> int:
    """Returnerer gjeldende ukenummer."""
    return datetime.now().isocalendar()[1]


def hent_alle_tilbud() -> dict:
    """Henter tilbud for alle produkter i config.

    Returnerer dict med metadata og resultater, egnet for både CLI og web.
    """
    produkter, butikker = last_config()
    uke = ukenummer()
    år = datetime.now().year

    resultater = []
    for produkt in produkter:
        navn = produkt["navn"]
        sokeord_liste = produkt["sokeord"]
        filter_ord = [f.lower() for f in produkt.get("filter", [])]

        unike_tilbud = {}
        for sokeord in sokeord_liste:
            tilbud = hent_tilbud(sokeord)
            filtrert = filtrer_butikker(tilbud, butikker)
            for t in filtrert:
                # Hvis filter er satt, sjekk at minst ett filterord finnes i produktnavnet
                if filter_ord:
                    t_navn = t["navn"].lower()
                    if not any(f in t_navn for f in filter_ord):
                        continue
                nøkkel = f"{t['butikk']}_{t['navn']}_{t['pris']}"
                if nøkkel not in unike_tilbud:
                    unike_tilbud[nøkkel] = t
            time.sleep(0.5)

        treff = list(unike_tilbud.values())
        for t in treff:
            t["pris_formatert"] = formater_pris(t["pris"])
            t["fra_formatert"] = formater_dato(t["gyldig_fra"])
            t["til_formatert"] = formater_dato(t["gyldig_til"])

        resultater.append({
            "produkt": navn,
            "har_tilbud": len(treff) > 0,
            "tilbud": treff,
        })

    return {
        "uke": uke,
        "aar": år,
        "resultater": resultater,
        "totalt_treff": sum(len(r["tilbud"]) for r in resultater),
    }


def main():
    data = hent_alle_tilbud()

    print(f"\n{'=' * 50}")
    print(f"  TILBUDSSJEKK — Uke {data['uke']}, {data['aar']}")
    print(f"{'=' * 50}\n")

    for r in data["resultater"]:
        if r["har_tilbud"]:
            print(f"  ✅ {r['produkt']}")
            for t in r["tilbud"]:
                print(f"     📍 {t['butikk']} — {t['pris_formatert']}")
                print(f"        {t['navn']}")
                print(f"        Gyldig: {t['fra_formatert']} – {t['til_formatert']}")
                print()
        else:
            print(f"  ❌ {r['produkt']}")
            print(f"     Ingen tilbud denne uken.\n")

    print(f"{'=' * 50}")
    if data["totalt_treff"] > 0:
        print(f"  Totalt {data['totalt_treff']} tilbud funnet!")
    else:
        print(f"  Ingen av varene dine er på tilbud denne uken.")
    print(f"{'=' * 50}\n")


if __name__ == "__main__":
    main()
