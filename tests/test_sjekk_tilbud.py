"""Tester for skraperen. Kjør: python -m pytest"""

import base64
import html
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import sjekk_tilbud as s

NAA = datetime(2026, 10, 11, 9, 0, tzinfo=timezone.utc)


def raatt_tilbud(**endringer):
    tilbud = {
        "publicId": "abc123",
        "name": "MEIERISMØR",
        "description": "500G, TINE (99,80/KG)\nFØRPRIS 68,90",
        "unitPrice": 99.8,
        "baseUnit": "kilogram",
        "price": 49.9,
        "savings": 19.000000000000007,
        "membershipPrice": None,
        "relativeSavings": None,
        "membershipRelativeSavings": None,
        "pieceCountGet": None,
        "pieceCountGetFor": None,
        "pieceCountFrom": 1,
        "image": "https://image-transformer-api.tjek.com/?u=liten",
        "imageLarge": "https://image-transformer-api.tjek.com/?u=stor",
        "validFrom": "2026-10-11T22:00:00+0000",
        "validUntil": "2026-10-14T21:59:59+0000",
        "business": {"name": "MENY", "slugs": ["MENY"], "primaryColor": "#dd233d"},
        "publicationPublicId": "E39UwO-u",
    }
    tilbud.update(endringer)
    return tilbud


def side(*blokker):
    """Bygger en minimal søkeside med <app-data>-elementer slik eTilbudsavis gjør."""
    deler = []
    for nokkel, innhold in blokker:
        kodet = base64.b64encode(json.dumps(nokkel).encode()).decode()
        deler.append(f'<app-data data-key="{kodet}">{html.escape(json.dumps(innhold))}</app-data>')
    return "<html><body>" + "".join(deler) + "</body></html>"


# --- les_tilbud ---

def test_les_tilbud_henter_tilbud_og_sted():
    sidehtml = side(
        (["offers", {"searchTerm": "smør", "sources": ["publication"]}], {"data": [raatt_tilbud()]}),
        (["offers", {"searchTerm": "smør", "sources": ["business_product"]}], {"data": []}),
        (["location", None], {"city": "Oslo", "mode": "fallback"}),
    )
    tilbud, sted = s.les_tilbud(sidehtml)
    assert [t["name"] for t in tilbud] == ["MEIERISMØR"]
    assert sted == "Oslo"


def test_les_tilbud_godtar_sok_uten_treff():
    tilbud, _ = s.les_tilbud(side((["offers", {"searchTerm": "x"}], {"data": []})))
    assert tilbud == []


def test_les_tilbud_feiler_naar_datablokken_mangler():
    with pytest.raises(s.Kildefeil):
        s.les_tilbud("<html><body>Vi har lagt om siden</body></html>")


# --- tolk_tilbud ---

def test_tolk_tilbud_regner_ut_forpris_rabatt_og_enhet():
    t = s.tolk_tilbud(raatt_tilbud())
    assert t["navn"] == "Meierismør"
    assert t["butikk"] == "MENY"
    assert t["farge"] == "#dd233d"
    assert t["pris"] == 49.9
    assert t["forpris"] == 68.9
    assert t["rabatt_prosent"] == 28
    assert (t["enhetspris"], t["enhet"]) == (99.8, "kg")
    assert t["fra"] == "2026-10-11T22:00:00+00:00"
    assert t["url"] == "https://etilbudsavis.no/MENY?publication=E39UwO-u&offer=abc123"
    assert t["bilde_stor"].endswith("stor")


def test_tolk_tilbud_prosenttilbud_uten_kronepris():
    t = s.tolk_tilbud(raatt_tilbud(price=None, savings=None, relativeSavings=25, unitPrice=0))
    assert "pris" not in t and "enhetspris" not in t
    assert t["rabatt_prosent"] == 25


def test_tolk_tilbud_medlemspris_og_flerkjop():
    t = s.tolk_tilbud(raatt_tilbud(price=None, savings=None, membershipPrice=20, pieceCountFrom=2))
    assert t["medlemspris"] == 20
    assert t["antall"] == 2
    t = s.tolk_tilbud(raatt_tilbud(price=None, savings=None, pieceCountGet=3, pieceCountGetFor=2))
    assert (t["ta"], t["betal"]) == (3, 2)


def test_tolk_tilbud_beholder_navn_med_blandet_skrift_og_forkaster_ugyldig_farge():
    t = s.tolk_tilbud(raatt_tilbud(name="Peppes pizza", business={"name": "REMA 1000", "slugs": ["REMA 1000"], "primaryColor": "red; x"}))
    assert t["navn"] == "Peppes pizza"
    assert "farge" not in t
    assert t["url"].startswith("https://etilbudsavis.no/REMA%201000?")


# --- treffer_filter ---

@pytest.mark.parametrize("navn, beskrivelse, forventet", [
    ("Meierismør", "500G, TINE", True),
    ("Melange", "original, flytende 500 ml", False),      # margarin uten «smør» i teksten
    ("Melange margarin", "med smør", False),               # utelukket av «ikke»
    ("Nystekt smør croissant", "70g", False),
    ("WD-40", "Smører og beskytter", False),
])
def test_filter_smor(navn, beskrivelse, forventet):
    tilbud = {"navn": navn, "beskrivelse": beskrivelse}
    assert s.treffer_filter(tilbud, ["smør"], ["margarin", "croissant", "smøre"]) is forventet


def test_filter_krever_alle_grupper_men_bare_ett_alternativ_i_hver():
    krev = ["eple", ["juice", "most"]]
    assert s.treffer_filter({"navn": "Eplemost", "beskrivelse": "3l"}, krev, [])
    assert s.treffer_filter({"navn": "Sunniva juice", "beskrivelse": "Eple/Frokostjuice"}, krev, [])
    assert not s.treffer_filter({"navn": "Cevita juice", "beskrivelse": "et stort utvalg"}, krev, [])
    assert not s.treffer_filter({"navn": "Epledrikk", "beskrivelse": ""}, krev, [])


def test_filter_leser_beskrivelsen():
    # «Peppes» står bare i beskrivelsen, og «hele bønner» likeså
    assert s.treffer_filter({"navn": "Pepperoni", "beskrivelse": "70 g, Peppes"}, ["peppes"], [])
    assert s.treffer_filter({"navn": "L'or espresso", "beskrivelse": "Hele bønner. 500 g"}, ["espresso", "bønner"], [])
    assert not s.treffer_filter({"navn": "Nespresso kapsler", "beskrivelse": "10 stk"}, ["espresso", "bønner"], [])


def test_uten_filter_slipper_alt_gjennom():
    assert s.treffer_filter({"navn": "Hva som helst", "beskrivelse": ""}, [], [])


# --- hent_alle_tilbud ---

KONFIG = (
    [
        {"navn": "Smør", "sokeord": ["smør", "meierismør"], "krev": ["smør"], "ikke": ["margarin"]},
        {"navn": "Rustica", "sokeord": ["rustica"], "krev": ["rustica"]},
    ],
    ["MENY", "KIWI"],
)


def kjor(monkeypatch, sider):
    def falsk_hent(sokeord):
        resultat = sider[sokeord]
        if isinstance(resultat, Exception):
            raise resultat
        return resultat

    monkeypatch.setattr(s, "last_config", lambda: KONFIG)
    monkeypatch.setattr(s, "hent_side", falsk_hent)
    monkeypatch.setattr(s, "PAUSE", 0)
    return s.hent_alle_tilbud(naa=NAA)


def offers(*tilbud):
    return side((["offers", {}], {"data": list(tilbud)}), (["location", None], {"city": "Oslo"}))


def test_hent_alle_filtrerer_butikk_vare_utlopt_og_duplikater(monkeypatch):
    data = kjor(monkeypatch, {
        "smør": offers(
            raatt_tilbud(),
            raatt_tilbud(publicId="kopi"),                                    # samme tilbud i en annen avisutgave
            raatt_tilbud(publicId="jacobs", business={"name": "Jacobs", "slugs": ["Jacobs"]}),
            raatt_tilbud(publicId="marg", name="MELANGE MARGARIN"),
            raatt_tilbud(publicId="gammelt", price=39, validUntil="2026-10-10T21:59:59+0000"),
        ),
        "meierismør": offers(raatt_tilbud()),
        "rustica": offers(),
    })
    smor, rustica = data["produkter"]
    assert [t["id"] for t in smor["tilbud"]] == ["abc123"]
    assert rustica == {"navn": "Rustica", "feil": False, "tilbud": []}
    assert data["sted"] == "Oslo"
    assert data["sok_feilet"] == 0
    assert data["generert"] == "2026-10-11T09:00:00+00:00"


def test_hent_alle_merker_varer_som_ikke_kunne_sjekkes(monkeypatch):
    data = kjor(monkeypatch, {
        "smør": offers(raatt_tilbud()),
        "meierismør": s.Kildefeil("nede"),
        "rustica": s.Kildefeil("nede"),
    })
    smor, rustica = data["produkter"]
    assert smor["feil"] is True and len(smor["tilbud"]) == 1
    assert rustica == {"navn": "Rustica", "feil": True, "tilbud": []}
    assert (data["sok_totalt"], data["sok_feilet"]) == (3, 2)


# --- skriving ---

def test_main_lar_gammel_fil_staa_naar_kilden_er_nede(monkeypatch, tmp_path):
    ut = tmp_path / "tilbud.json"
    ut.write_text('{"gammel": true}', encoding="utf-8")
    monkeypatch.setattr(s, "last_config", lambda: KONFIG)
    monkeypatch.setattr(s, "hent_side", lambda sokeord: (_ for _ in ()).throw(s.Kildefeil("nede")))
    monkeypatch.setattr(s, "PAUSE", 0)
    assert s.main(["--ut", str(ut)]) == 1
    assert json.loads(ut.read_text(encoding="utf-8")) == {"gammel": True}


def test_main_skriver_fil_og_melder_delvis_feil(monkeypatch, tmp_path):
    ut = tmp_path / "ny" / "tilbud.json"
    sider = {"smør": offers(raatt_tilbud(validUntil="2099-01-01T00:00:00+0000")), "meierismør": offers(), "rustica": s.Kildefeil("nede")}

    def falsk_hent(sokeord):
        if isinstance(sider[sokeord], Exception):
            raise sider[sokeord]
        return sider[sokeord]

    monkeypatch.setattr(s, "last_config", lambda: KONFIG)
    monkeypatch.setattr(s, "hent_side", falsk_hent)
    monkeypatch.setattr(s, "PAUSE", 0)
    assert s.main(["--ut", str(ut)]) == 1
    skrevet = json.loads(ut.read_text(encoding="utf-8"))
    assert skrevet["produkter"][0]["tilbud"][0]["navn"] == "Meierismør"
    assert skrevet["produkter"][1]["feil"] is True
