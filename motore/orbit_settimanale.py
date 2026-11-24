"""REFLOW ORBIT - giro settimanale su GitHub Actions, con dati solo cifrati.

Il repository e' pubblico: qui non c'e' nessun dato di impianto. Tutto quello che
riguarda gli impianti (anagrafica, aree, serie, script di calcolo, immagini e
risultati) sta nel ramo `dati` solo in forma cifrata (AES-256-GCM). La chiave
sta nei Secrets del repository e in un file nella cartella REFLOW ORBIT su
SharePoint, da cui la legge l'app dopo il login Microsoft.

File del ramo `dati` (tutti cifrati):
  stato.enc        pacchetto di lavoro: erba_satellite.py, impianti.json, serie/<id>.json
  orbit.enc        dati/orbit.json letto dall'app (immagini con nomi anonimi)
  img/<codice>.enc immagine satellitare di ogni impianto (codice = HMAC dell'id)
  log.enc          registro dell'ultimo giro

Comandi
  giro         (GitHub Actions) decifra, calcola con erba_satellite.py, ricifra e
               pubblica nella cartella del ramo `dati`. Chiave e credenziali da
               variabili d'ambiente: ORBIT_CHIAVE, COPERNICUS_CLIENT_ID,
               COPERNICUS_CLIENT_SECRET. Nei log stampa solo conteggi.
  impacchetta  rifa' stato.enc da una cartella con erba_satellite.py e impianti.json
               (la cartella REFLOW ORBIT), tenendo le serie gia' presenti nel ramo
               `dati` (--azzera id1,id2 per ricalcolarne alcune da capo).
  estrai       decifra il ramo `dati` in una cartella, per controllo.

Chiave fuori da Actions: --chiave-file <percorso del file con la chiave in base64>.
Dipendenze: pip install requests cryptography
"""

import argparse
import base64
import datetime as dt
import hashlib
import hmac
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIA = b"ORB1"


class Errore(Exception):
    """Errore con messaggio pubblicabile nei log (senza dati di impianto)."""


# ----------------------------------------------------------------- cifratura

def carica_chiave(args):
    testo = None
    if getattr(args, "chiave_file", None):
        testo = Path(args.chiave_file).read_text(encoding="utf-8")
    elif os.environ.get("ORBIT_CHIAVE"):
        testo = os.environ["ORBIT_CHIAVE"]
    if not testo:
        raise Errore("chiave mancante (secret ORBIT_CHIAVE o --chiave-file)")
    try:
        k = base64.b64decode(testo.strip(), validate=True)
    except Exception:
        raise Errore("chiave non valida (deve essere base64)")
    if len(k) != 32:
        raise Errore("chiave non valida (servono 32 byte)")
    return k


def cifra(chiave, dati, nome):
    nonce = os.urandom(12)
    return MAGIA + nonce + AESGCM(chiave).encrypt(nonce, dati, nome.encode())


def decifra(chiave, blob, nome):
    if blob[:4] != MAGIA:
        raise Errore(f"{nome}: formato non riconosciuto")
    try:
        return AESGCM(chiave).decrypt(blob[4:16], blob[16:], nome.encode())
    except Exception:
        raise Errore(f"{nome}: decifratura non riuscita (chiave diversa?)")


def codice_immagine(chiave, id_impianto):
    return hmac.new(chiave, ("img:" + id_impianto).encode(), hashlib.sha256).hexdigest()[:24]


def scrivi(cartella, nome, chiave, dati):
    p = Path(cartella) / nome
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(cifra(chiave, dati, nome))


def leggi(cartella, nome, chiave):
    p = Path(cartella) / nome
    if not p.exists():
        raise Errore(f"{nome} non trovato nel ramo dati")
    return decifra(chiave, p.read_bytes(), nome)


# ----------------------------------------------------------------- pacchetto di lavoro

def apri_pacchetto(blob, destinazione):
    dest = Path(destinazione)
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        for n in z.namelist():
            if n.startswith("/") or ".." in Path(n).parts:
                raise Errore("pacchetto non valido")
        z.extractall(dest)
    for f in ("erba_satellite.py", "impianti.json"):
        if not (dest / f).exists():
            raise Errore(f"pacchetto incompleto: manca {f}")


def crea_pacchetto(lavoro):
    lavoro = Path(lavoro)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(lavoro / "erba_satellite.py", "erba_satellite.py")
        z.write(lavoro / "impianti.json", "impianti.json")
        serie = lavoro / "dati" / "serie"
        if serie.is_dir():
            for f in sorted(serie.glob("*.json")):
                z.write(f, f"dati/serie/{f.name}")
    return buf.getvalue()


# ----------------------------------------------------------------- pubblicazione

def pubblica(chiave, lavoro, cartella_dati):
    """orbit.json e immagini dalla cartella di lavoro al ramo dati, cifrati e con nomi anonimi."""
    lavoro, cd = Path(lavoro), Path(cartella_dati)
    pacchetto = json.loads((lavoro / "dati" / "orbit.json").read_text(encoding="utf-8"))
    img_dir = cd / "img"
    if img_dir.exists():
        shutil.rmtree(img_dir)
    n_img = 0
    for voce in pacchetto["impianti"]:
        rel = voce.get("immagine")
        if not rel:
            continue
        f = lavoro / "dati" / rel
        if not f.exists():
            voce["immagine"] = None
            continue
        nome = f"img/{codice_immagine(chiave, voce['id'])}.enc"
        scrivi(cd, nome, chiave, f.read_bytes())
        voce["immagine"] = nome
        n_img += 1
    scrivi(cd, "orbit.enc", chiave, json.dumps(pacchetto, ensure_ascii=False).encode("utf-8"))
    return pacchetto, n_img


def riepilogo(pacchetto, n_img, attenzioni):
    conta = {}
    for v in pacchetto["impianti"]:
        s = (v.get("stato") or {}).get("semaforo", "nd")
        conta[s] = conta.get(s, 0) + 1
        fs = (v.get("stato") or {}).get("fine_stagione")
        if fs:
            k = "fine stagione " + fs.get("semaforo", "nd")
            conta[k] = conta.get(k, 0) + 1
    righe = [f"Aggiornato: {pacchetto['aggiornato']}",
             f"Impianti: {len(pacchetto['impianti'])}, immagini: {n_img}, avvisi di scaricamento: {attenzioni}",
             "Stati: " + ", ".join(f"{k} {conta[k]}" for k in sorted(conta))]
    return "\n".join(righe)


# ----------------------------------------------------------------- comandi

def cmd_giro(args):
    chiave = carica_chiave(args)
    cid = os.environ.get("COPERNICUS_CLIENT_ID", "").strip()
    sec = os.environ.get("COPERNICUS_CLIENT_SECRET", "").strip()
    if not cid or not sec:
        raise Errore("credenziali Copernicus mancanti (secret COPERNICUS_CLIENT_ID e COPERNICUS_CLIENT_SECRET)")
    cd = Path(args.dati)
    registro = [f"Giro del {dt.datetime.now().isoformat(timespec='minutes')}"]
    try:
        with tempfile.TemporaryDirectory() as tmp:
            lavoro = Path(tmp) / "lavoro"
            apri_pacchetto(leggi(cd, "stato.enc", chiave), lavoro)
            cfg = Path(tmp) / "config.ini"
            cfg.write_text(f"[copernicus]\nclient_id = {cid}\nclient_secret = {sec}\n", encoding="utf-8")
            os.chmod(cfg, 0o600)
            impianti = json.loads((lavoro / "impianti.json").read_text(encoding="utf-8"))["impianti"]
            con_area = sum(1 for i in impianti if i.get("geometria"))
            env = dict(os.environ, REFLOW_ORBIT_IMPIANTI=str(lavoro / "impianti.json"))
            for k in ("ORBIT_CHIAVE", "COPERNICUS_CLIENT_ID", "COPERNICUS_CLIENT_SECRET"):
                env.pop(k, None)
            cmd = [sys.executable, str(lavoro / "erba_satellite.py"), "stato", "--immagini",
                   "--config", str(cfg), "--output", str(lavoro / "dati")]
            if args.a:
                cmd += ["--a", args.a]
            try:
                p = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=args.timeout * 60)
            except subprocess.TimeoutExpired:
                raise Errore(f"calcolo interrotto dopo {args.timeout} minuti")
            registro += [p.stdout, p.stderr]
            if p.returncode != 0:
                raise Errore(f"calcolo non riuscito (codice {p.returncode}, dettagli nel registro cifrato)")
            attenzioni = sum(1 for r in p.stdout.splitlines() if r.startswith("ATTENZIONE") and "anteprima" not in r)
            if con_area and attenzioni >= con_area:
                raise Errore("nessuna serie scaricata (Copernicus non raggiungibile?): dati precedenti mantenuti")
            pacchetto, n_img = pubblica(chiave, lavoro, cd)
            scrivi(cd, "stato.enc", chiave, crea_pacchetto(lavoro))
            sintesi = riepilogo(pacchetto, n_img, sum(1 for r in p.stdout.splitlines() if r.startswith("ATTENZIONE")))
            registro.append(sintesi)
            print(sintesi)
    except Errore as e:
        registro.append("ERRORE: " + str(e))
        raise
    except Exception as e:
        registro.append(f"ERRORE imprevisto: {type(e).__name__}: {e}")
        raise Errore(f"errore imprevisto ({type(e).__name__}), dettagli nel registro cifrato")
    finally:
        scrivi(cd, "log.enc", chiave, "\n".join(x for x in registro if x).encode("utf-8"))


def cmd_impacchetta(args):
    chiave = carica_chiave(args)
    sorgente, cd = Path(args.sorgente), Path(args.dati)
    azzera = {x.strip() for x in (args.azzera or "").split(",") if x.strip()}
    with tempfile.TemporaryDirectory() as tmp:
        lavoro = Path(tmp) / "lavoro"
        if (cd / "stato.enc").exists():
            apri_pacchetto(leggi(cd, "stato.enc", chiave), lavoro)
        serie = lavoro / "dati" / "serie"
        if args.serie:
            serie.mkdir(parents=True, exist_ok=True)
            for f in Path(args.serie).glob("*.json"):
                if not (serie / f.name).exists():
                    shutil.copy2(f, serie / f.name)
        lavoro.mkdir(parents=True, exist_ok=True)
        for f in ("erba_satellite.py", "impianti.json"):
            shutil.copy2(sorgente / f, lavoro / f)
        ids = {i["id"] for i in json.loads((lavoro / "impianti.json").read_text(encoding="utf-8"))["impianti"]}
        tolte = 0
        if serie.is_dir():
            for f in serie.glob("*.json"):
                if f.stem in azzera or f.stem not in ids:
                    f.unlink()
                    tolte += 1
        scrivi(cd, "stato.enc", chiave, crea_pacchetto(lavoro))
        n = len(list(serie.glob("*.json"))) if serie.is_dir() else 0
        print(f"stato.enc scritto: {len(ids)} impianti, {n} serie ({tolte} tolte)")


def cmd_estrai(args):
    chiave = carica_chiave(args)
    cd, dest = Path(args.dati), Path(args.destinazione)
    dest.mkdir(parents=True, exist_ok=True)
    apri_pacchetto(leggi(cd, "stato.enc", chiave), dest / "lavoro")
    if (cd / "orbit.enc").exists():
        (dest / "orbit.json").write_bytes(leggi(cd, "orbit.enc", chiave))
    if (cd / "log.enc").exists():
        (dest / "log.txt").write_bytes(leggi(cd, "log.enc", chiave))
    for f in sorted((cd / "img").glob("*.enc")) if (cd / "img").is_dir() else []:
        out = dest / "img" / (f.stem + ".png")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(leggi(cd, f"img/{f.name}", chiave))
    print("Estratto in", dest)


def main():
    p = argparse.ArgumentParser(description="REFLOW ORBIT - giro settimanale con dati cifrati")
    p.add_argument("comando", choices=["giro", "impacchetta", "estrai"])
    p.add_argument("--dati", required=True, help="cartella del ramo dati")
    p.add_argument("--chiave-file", help="file con la chiave in base64 (fuori da Actions)")
    p.add_argument("--sorgente", help="impacchetta: cartella con erba_satellite.py e impianti.json")
    p.add_argument("--serie", help="impacchetta: cartella con serie <id>.json da aggiungere se mancanti")
    p.add_argument("--azzera", help="impacchetta: id separati da virgola le cui serie vanno ricalcolate")
    p.add_argument("--destinazione", help="estrai: cartella di uscita")
    p.add_argument("--a", help="giro: data di calcolo AAAA-MM-GG (solo per prove)")
    p.add_argument("--timeout", type=int, default=45, help="giro: minuti massimi per il calcolo")
    args = p.parse_args()
    try:
        {"giro": cmd_giro, "impacchetta": cmd_impacchetta, "estrai": cmd_estrai}[args.comando](args)
    except Errore as e:
        print("ERRORE:", e, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
