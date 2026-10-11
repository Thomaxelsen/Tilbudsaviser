"""
Tilbudssjekker — henter tilbud på varene i config.json fra eTilbudsavis.no.

Skriver resultatet til site/tilbud.json, som den statiske siden leser.
Kjør: python sjekk_tilbud.py
"""

import argparse
import base64
import json
import re
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

SCRIPT_DIR = Path(__file__).parent
CONFIG_FILE = SCRIPT_DIR / "config.json"
UT_FIL = SCRIPT_DIR / "site" / "tilbud.json"
BASE_URL = "https://etilbudsavis.no/"
SOK_URL = BASE_URL + "soek/"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
PAUSE = 0.3  # sekunder mellom hvert søk, for å være snill mot kilden
ENHETER = {"kilogram": "kg", "liter": "l"}
FARGE = re.compile(r"#[0-9a-fA-F]{6}")


class Kildefeil(Exception):
    """eTilbudsavis svarte ikke, eller siden har endret oppbygning."""


def last_config():
    """Leser config.json og returnerer produkter og butikkliste."""
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        config = json.load(f)
    return config["produkter"], config["butikker"]


def hent_side(sokeord: str) -> str:
    """Henter søkesiden for et søkeord. Prøver én gang til ved feil."""
    url = SOK_URL + urllib.parse.quote(sokeord)
    siste_feil = None
    for forsok in range(2):
        if forsok:
            time.sleep(2)
        try:
            resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=15)
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as e:
            siste_feil = e
    raise Kildefeil(f"Kunne ikke hente '{sokeord}': {siste_feil}")


def les_tilbud(html: str) -> tuple[list[dict], str | None]:
    """Plukker tilbudene ut av <app-data>-blokkene på en søkeside.

    Returnerer (rå tilbud, stedet søket gjelder for). Et søk uten treff gir en
    tom liste; mangler selve datablokken, er siden lagt om og vi feiler høylytt.
    """
    soup = BeautifulSoup(html, "html.parser")
    tilbud, sted, fant_blokk = [], None, False

    for blokk in soup.find_all("app-data"):
        try:
            nokkel = json.loads(base64.b64decode(blokk.get("data-key", "")))
            innhold = json.loads(blokk.get_text())
        except ValueError:
            continue
        if not isinstance(nokkel, list) or not nokkel or not isinstance(innhold, dict):
            continue

        if nokkel[0] == "offers" and isinstance(innhold.get("data"), list):
            fant_blokk = True
            tilbud.extend(t for t in innhold["data"] if isinstance(t, dict))
        elif nokkel[0] == "location":
            sted = innhold.get("city")

    if not fant_blokk:
        raise Kildefeil("Fant ingen tilbudsdata på siden — eTilbudsavis kan ha endret oppbygning.")
    return tilbud, sted


def _tidspunkt(verdi) -> str | None:
    """Gjør om «2026-10-11T22:00:00+0000» til ISO-format nettleseren forstår."""
    try:
        return datetime.fromisoformat(verdi).astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError):
        return None


def tolk_tilbud(raa: dict) -> dict:
    """Oversetter et rått tilbud til feltene siden bruker. Tomme felt utelates."""
    butikk = raa.get("business") or {}
    navn = (raa.get("name") or "").strip()
    if navn.isupper():
        navn = navn.capitalize()

    pris, spart = raa.get("price"), raa.get("savings")
    rabatt = raa.get("relativeSavings")
    forpris = None
    if pris and spart and spart > 0:
        forpris = round(pris + spart, 2)
        rabatt = rabatt or round(spart / forpris * 100)

    enhet = ENHETER.get(raa.get("baseUnit"))
    enhetspris = raa.get("unitPrice") if enhet else None
    farge = butikk.get("primaryColor")
    slug = (butikk.get("slugs") or [butikk.get("name", "")])[0]
    antall = raa.get("pieceCountFrom")

    tilbud = {
        "id": raa.get("publicId"),
        "navn": navn,
        "beskrivelse": (raa.get("description") or "").strip(),
        "butikk": butikk.get("name", ""),
        "farge": farge if isinstance(farge, str) and FARGE.fullmatch(farge) else None,
        "pris": pris,
        "medlemspris": raa.get("membershipPrice"),
        "forpris": forpris,
        "rabatt_prosent": rabatt,
        "medlemsrabatt_prosent": raa.get("membershipRelativeSavings"),
        "ta": raa.get("pieceCountGet"),
        "betal": raa.get("pieceCountGetFor"),
        "antall": antall if antall and antall > 1 else None,
        "enhetspris": round(enhetspris, 2) if enhetspris else None,
        "enhet": enhet if enhetspris else None,
        "fra": _tidspunkt(raa.get("validFrom")),
        "til": _tidspunkt(raa.get("validUntil")),
        "bilde": raa.get("image"),
        "bilde_stor": raa.get("imageLarge"),
        "url": f"{BASE_URL}{urllib.parse.quote(slug)}?publication={raa.get('publicationPublicId')}&offer={raa.get('publicId')}",
    }
    return {k: v for k, v in tilbud.items() if v is not None}


def treffer_filter(tilbud: dict, krev: list, ikke: list) -> bool:
    """Sjekker et tilbud mot produktets filter, i navn og beskrivelse.

    Hver oppføring i «krev» må finnes (en liste betyr «ett av disse»),
    og ingen av ordene i «ikke» får forekomme.
    """
    tekst = f"{tilbud.get('navn', '')} {tilbud.get('beskrivelse', '')}".lower()
    if any(ord.lower() in tekst for ord in ikke):
        return False
    for gruppe in krev:
        alternativer = [gruppe] if isinstance(gruppe, str) else gruppe
        if not any(ord.lower() in tekst for ord in alternativer):
            return False
    return True


def hent_alle_tilbud(naa: datetime | None = None) -> dict:
    """Henter tilbud for alle produkter i config, og merker søk som feilet."""
    produkter, butikker = last_config()
    naa = naa or datetime.now(timezone.utc)
    butikker_smaa = {b.lower() for b in butikker}
    sted, sok_totalt, sok_feilet = None, 0, 0

    resultater = []
    for produkt in produkter:
        krev, ikke = produkt.get("krev", []), produkt.get("ikke", [])
        unike, feil = {}, False

        for sokeord in produkt["sokeord"]:
            sok_totalt += 1
            try:
                raa_tilbud, sok_sted = les_tilbud(hent_side(sokeord))
            except Kildefeil as e:
                print(f"  Feil: {e}")
                sok_feilet += 1
                feil = True
                continue
            finally:
                time.sleep(PAUSE)
            sted = sted or sok_sted

            for raa in raa_tilbud:
                t = tolk_tilbud(raa)
                if t["butikk"].lower() not in butikker_smaa:
                    continue
                if "til" in t and datetime.fromisoformat(t["til"]) < naa:
                    continue
                if not treffer_filter(t, krev, ikke):
                    continue
                # Samme tilbud står ofte i flere utgaver av samme avis
                nokkel = (t["butikk"], t["navn"], t.get("pris"), t.get("medlemspris"), t.get("fra"), t.get("til"))
                unike.setdefault(nokkel, t)

        resultater.append({"navn": produkt["navn"], "feil": feil, "tilbud": list(unike.values())})

    return {
        "generert": naa.isoformat(),
        "sted": sted,
        "sok_totalt": sok_totalt,
        "sok_feilet": sok_feilet,
        "produkter": resultater,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Henter tilbud og skriver dem til en JSON-fil.")
    parser.add_argument("--ut", type=Path, default=UT_FIL, help=f"filen som skal skrives (standard: {UT_FIL})")
    args = parser.parse_args(argv)

    # Windows-konsollen bruker ikke UTF-8 som standard
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    data = hent_alle_tilbud()

    for p in data["produkter"]:
        merke = "!" if p["feil"] else ("✓" if p["tilbud"] else "–")
        print(f"  {merke} {p['navn']}: {len(p['tilbud'])} tilbud" + (" (kunne ikke sjekkes fullt ut)" if p["feil"] else ""))

    # Er kilden stort sett nede, beholder vi heller forrige fil enn å tømme siden
    if data["sok_feilet"] * 2 > data["sok_totalt"]:
        print(f"\n{data['sok_feilet']} av {data['sok_totalt']} søk feilet. Beholder forrige {args.ut.name}.")
        return 1

    args.ut.parent.mkdir(parents=True, exist_ok=True)
    args.ut.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"\nSkrev {sum(len(p['tilbud']) for p in data['produkter'])} tilbud til {args.ut}")
    return 1 if data["sok_feilet"] else 0


if __name__ == "__main__":
    sys.exit(main())
