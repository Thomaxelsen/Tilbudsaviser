"""Flask web-app for Tilbudssjekker."""

import json
from pathlib import Path

from flask import Flask, jsonify, render_template
from sjekk_tilbud import hent_alle_tilbud

app = Flask(__name__)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/config")
def config():
    config_file = Path(__file__).parent / "config.json"
    with open(config_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    return jsonify(data)


@app.route("/sjekk", methods=["POST"])
def sjekk():
    data = hent_alle_tilbud()
    return jsonify(data)


if __name__ == "__main__":
    app.run(debug=True, port=5000)
