# Ablauf bei „setup“

So geht Claude vor, wenn im Chat „setup“ steht. Die Regeln kommen immer aus diesem Repo: Vor jedem Setup holt Claude mit `git pull` den neuesten Stand von GitHub.

**Keine Anlageberatung. Die Regel liegt in allen Tests im Minus (siehe README).**

## Feste Regeln

- Claude sendet, ändert und schließt nie eine Order, auch nicht mit Erlaubnis. Du klickst jede Order selbst im KuCoin-Browser.
- Claude zeigt dir zuerst das Ticket. Ohne dein „ja“ passiert nichts.
- Die API-Schlüssel stehen nur in Windows-Umgebungsvariablen. Sie werden nie ausgegeben und nie im Chat abgefragt.
- Hebel 1x, isoliert.
- Höchstens 5 % Verlust pro Trade (3,83 USDT), Tageslimit 7,66 USDT. Die Zahlen stehen in `trader/kucoin.json`.
- Zwei Trades am Tag. Getestet ist nur Mo–Fr 09:30 bis 12:30 Berlin.

## Schritte

1. **Neuester Stand:** `git pull` im Ordner `C:\Users\ahmad\trad2`.
2. **Konto** (`python trader-kucoin/kucoin.py account`):
   - Kontostand, offene Positionen und aktive Stop-Orders.
   - Ist noch ein Trade offen, sagt Claude das zuerst.
3. **Börse** (`python trader-kucoin/kucoin.py brief`): Störungen, Wartung und Delistings bei den großen Kontrakten.
4. **News** (Websuche):
   - Große Termine heute: Fed, CPI, Arbeitsmarktdaten.
   - Krypto-Schlagzeilen der letzten 24 Stunden: Hacks, Ausfälle, Regulierung.
   - Coins mit schlechten News kommen auf die Sperrliste. Wegen des Binance-Hacks steht BNB dort.
   - Gespeichert wird das mit `kucoin.py news --summary "..." --avoid SYM`.
5. **Uhrzeit:**
   - **Mo–Fr 09:30 bis etwa 10:30:** `python trader/daily.py --avoid SYM`. Geschlossen wird um 12:30.
   - **Zu jeder anderen Zeit:** `python trader/daily.py --hours 3 --avoid SYM`. Geschlossen wird nach 3 Stunden. Claude sagt dazu, dass diese Zeiten nicht getestet sind.
6. **Rechnen** (`trader/daily.py`):
   - **Auswahl:** die 30 Kontrakte mit dem meisten Umsatz.
   - **Richtung:** Liegt auf 4h der EMA20 über dem EMA50, ist der Trade Long, sonst Short.
   - **7 Prüfungen:** Trend, Zone, RSI, Kerze, Fair Value Gap, Fibonacci, Platz bis zum Ziel.
   - **Price Action auf 15m** (`trader/price_action.py`): Spricht sie gegen den Trade, kommt der Coin nach hinten.
   - **Stop:** hinter einer Zone, 2–4 % vom Einstieg.
   - **Ziel:** 2R, nach Gebühren mindestens 1,2R.
   - **Größe:** Verlust höchstens 3,83 USDT. Positionswert höchstens 50 % des Kontos, 1x.
   - Die 2 besten Trades, in 2 verschiedenen Coins.
7. **Antwort:**
   - Pro Trade eine Zeile: `<COIN> LONG|SHORT – <Menge> (= <N> Kontrakte) – SL – TP – <x>/7 Regeln – bis <Uhrzeit> schließen`
   - Darunter: maximaler Verlust und Gewinn am Ziel für beide zusammen.
   - Warnungen nur, wenn wirklich etwas ansteht.
8. **Du klickst selbst**, mit TP und SL angehakt.
9. **Danach:** Schreib „drin“. Claude prüft, ob SL und TP bei KuCoin angekommen sind.

## Kein Trade, wenn

- ein alter Trade noch offen ist,
- kein Coin die harten Regeln besteht,
- das Tageslimit von 7,66 USDT erreicht ist.

Claude nennt dann den Grund in einem Satz.

## Private Daten

Trade-Logs und Tagesdaten (`trader/*-log.json`, `kucoin-brief.json`, `daily-watch.json` usw.) bleiben nur auf dem PC im Klon. `.gitignore` hält sie aus diesem öffentlichen Repo heraus.
