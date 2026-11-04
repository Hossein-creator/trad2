# trad2

Stand vom 04.11.2026: KuCoin-Futures-Skripte für zwei Trades am Tag. Die Skripte senden keine Orders aus der Tagesroutine, jede Order wird von Hand im KuCoin-Browser gesetzt.

**Dies ist keine Anlageberatung und kein Gewinnversprechen. Die Regel liegt in allen Tests unten im Minus.**

## Tagesablauf (Berlin, Mo–Fr)

| Zeit | Was passiert |
|---|---|
| ca. 08:29 | Konto, Brief und News prüfen, Rangliste speichern (`daily.py --snapshot`), kein Trade |
| ca. 09:29 | 2 Trades in 2 verschiedenen Coins (`daily.py`) |
| 12:00–12:30 | Trades von Hand schließen, falls SL oder TP sie nicht beendet haben |

Nach etwa 10:30 gibt das Skript keine neuen Trades mehr.

## Regeln

- **Risiko:** max. 1 % Verlust pro Trade, Ziel 2R, mindestens 1,2R nach Gebühren und Funding, 1x isoliert
- **Stop:** hinter einer Zone, 2–4 % Abstand
- **Auswahl:** 7 Prüfungen (Trend, Zone, RSI, Kerze, Fair Value Gap, Fibonacci, Platz bis zum Ziel), danach Punkte
- **Richtung:** 4h-EMA20 über EMA50 Long, darunter Short

Die Einzelheiten stehen am Anfang von `trader/daily.py`.

## Testergebnisse (nach Kosten)

| Test | Trades | Gewinnquote | Pro Trade | Gesamt |
|---|---|---|---|---|
| 09:30–12:30, 2 Trades, 29 Coins, 1 Jahr | 528 | 42 % | −0,06R | −33R |
| 2 zufällige Coins, gleiche Regeln | 528 | 47 % | −0,02R | −10R |
| 11:00–22:00, 2 Trades, 50 Coins, 2 Jahre | 1.002 | 41 % | −0,10R | −102,5R |

Die vollständigen Zahlen stehen in `trader/backtest-*.txt`.

## Einrichten

Python 3 genügt, Zusatzpakete sind nicht nötig. Die API-Schlüssel gehören in die Umgebungsvariablen `KUCOIN_API_KEY`, `KUCOIN_API_SECRET` und `KUCOIN_API_PASSPHRASE` und **nie** in dieses Repo.

```bash
python trader-kucoin/kucoin.py account
```

```bash
python trader/daily.py --avoid ETH,BNB
```

Die Backtests laden ihre Kursdaten selbst:

```bash
python trader/fetch_bars.py BARS_FOLDER 30 370 15
```

## Inhalt

- `trader/`: Tages- und Wochenend-Strategie, Scanner, Backtests, Einstellungen
- `trader-kucoin/`: KuCoin-Skill mit Regeln und Skript
- `task/`: Anweisung der geplanten Morgen-Aufgabe in der Claude-App

Eigene Trade-Logs und Tagesdaten liegen nicht in diesem Repo (siehe `.gitignore`).
