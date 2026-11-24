# REFLOW ORBIT

Monitoraggio satellitare (Copernicus Sentinel-2) della crescita dell'erba negli impianti fotovoltaici a terra in O&M di Reflow S.r.l.: per ogni impianto un semaforo (verde, giallo = sfalcio da programmare, rosso = oltre il livello a cui di solito si taglia), l'andamento dell'indice di verde (NDVI) con le date degli sfalci e un'immagine satellitare recente.

Applicativo web (PWA) in sola lettura, con accesso tramite account Microsoft aziendale (registrazione condivisa con REFLOW PLANNER e REFLOW iMAPS). I dati li calcola lo script di monitoraggio e stanno su SharePoint, non in questo repository.

## Dati

Nessun dato di impianto, coordinata o nome di cliente va inserito in questo repository in chiaro: il `.gitignore` esclude i file di dati.

## Aggiornamento settimanale automatico

Ogni lunedì mattina il workflow `.github/workflows/aggiornamento-settimanale.yml` (GitHub Actions) esegue `motore/orbit_settimanale.py giro`: decifra il pacchetto di lavoro, ricalcola lo stato di tutti gli impianti da Copernicus Sentinel-2 e pubblica i risultati nel ramo `dati`, **solo cifrati** (AES-256-GCM). L'app li decifra nel browser con una chiave che legge da SharePoint dopo il login Microsoft. I log del workflow riportano solo conteggi.

Secrets del repository: `ORBIT_CHIAVE` (chiave in base64, la stessa del file su SharePoint), `COPERNICUS_CLIENT_ID`, `COPERNICUS_CLIENT_SECRET`.

Il giro parte anche a mano (Actions → "ORBIT - aggiornamento settimanale" → Run workflow) e a ogni modifica di `motore/` o del workflow. Se il calcolo non riesce, restano pubblicati i dati del giro precedente.

## Manutenzione

Responsabile dell'applicativo: Luca Alberton (PM O&M, Reflow S.r.l.).
