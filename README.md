# Akiya Watch

App personale per cercare immobili in vendita in Giappone fino a 13,5 milioni di yen, con mappa, filtri in dollari australiani, preferiti, rendimento e avvisi per i nuovi annunci.

| Fonte | Cosa | Stato |
|---|---|---|
| athome.co.jp | case e appartamenti usati, case nuove, con inquilino, commerciale | esclusa: verifica anti-bot dopo 6 pagine (anche da rete di casa, a 15 s) |
| SUUMO | case e appartamenti usati, case nuove (solo pagine per città, consentite dal robots.txt) | attiva |
| Akiya bank pubbliche | portali prefetturali + comuni trovati dal censimento mensile | attiva |
| LIFULL HOME'S Akiya Bank | akiya delle banche comunali | esclusa: 403 anche da rete di casa |
| Rakumachi, Kenbiya | portali investimento | esclusi: accesso dall'estero negato / robots.txt

- **Script** (`scraper/`): ogni giorno legge le tre fonti con calma (una richiesta ogni ~2 secondi), unisce i doppioni, ricava la posizione per la mappa (geocoder GSI) e converte i prezzi in AUD (cambio BCE).
- **App** (`web/`): app web installabile su Android e computer, pubblicata su GitHub Pages.
- **Avvisi**: notifica push con [ntfy](https://ntfy.sh) e riepilogo email per gli annunci nuovi che rispettano i filtri in `config.yml`.
- **Privacy**: tutti i dati sono cifrati (AES-256) con la tua passphrase. Il repository e il sito sono pubblici, ma senza passphrase nessuno può leggere gli annunci.

> Uso personale. I termini d'uso di LIFULL e SUUMO vietano la ripubblicazione e l'uso commerciale dei loro contenuti senza permesso: per rendere l'app pubblica servono accordi con i portali.

## Configurazione iniziale (una volta sola)

1. **Secrets** (Settings → Secrets and variables → Actions → New repository secret)
   | Nome | Valore |
   |---|---|
   | `AKIYA_PASSPHRASE` | una frase lunga che ricordi; serve per aprire l'app |
   | `NTFY_TOPIC` | un nome difficile da indovinare, es. `akiya-enrico-7f3k9q` |
   | `SMTP_USER` | (facoltativo) il tuo indirizzo Gmail |
   | `SMTP_PASS` | (facoltativo) una *password per le app* di Google, non la password normale |
   | `EMAIL_TO` | (facoltativo) dove ricevere il riepilogo |
2. **Pages**: Settings → Pages → Source: **GitHub Actions**.
3. **Primo giro**: Actions → *Aggiorna annunci* → **Run workflow**. Può durare qualche ora.
4. **Notifiche sul telefono**: installa l'app **ntfy** dal Play Store e iscriviti al topic scelto in `NTFY_TOPIC`.
5. **App**: apri `https://cheebo90.github.io/akiya-watch/` in Chrome sul telefono → menu ⋮ → **Installa app**.

## Akiya bank di prefetture e comuni

- `akiyabanks.yml`: siti verificati a mano (portali prefetturali di Hokkaido, Ibaraki, Niigata e Mie).
- `census.yml`: generato ogni mese da **Actions → Censimento akiya bank**. Parte dall'elenco di link comunali di
  akiya-portal.net, visita ogni sito una volta (rispettando robots.txt) e attiva da solo quelli dove riconosce le schede.
  Stati: `ok` (letto ogni giorno), `todo` (da sistemare a mano), `pdf` (elenco in PDF), `delegated` (ospitato da LIFULL/At Home),
  `robots` (vietato dal sito), `blocked`, `unreachable`.
- Per sistemare un sito `todo`, copialo in `akiyabanks.yml` indicando la pagina elenco e la regex delle schede.

## Personalizzare

Modifica `config.yml` direttamente su GitHub: budget, prefetture, fonti e filtri degli avvisi.

## Se una fonte viene bloccata

Se un sito blocca i server di GitHub ricevi un avviso. In quel caso lo script può girare sul tuo computer:

```bash
pip install -r requirements.txt
export AKIYA_PASSPHRASE="..." NTFY_TOPIC="..."
python -m scraper.run all
git add data/state.enc web/data.enc && git commit -m "aggiornamento" && git push
```

## Sviluppo

```bash
python -m pytest -q
```
