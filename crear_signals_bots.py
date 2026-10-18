#!/usr/bin/env python3
"""Crea un signal de Seq por cada bot (codigo base de TaskName) detectado.

Detecta los codigos unicos en los eventos RPA (prefijo de TaskName antes del
primer guion bajo), y crea `RPA Tasks <CODIGO>` por cada uno que no exista
todavia. Idempotente: respeta las senales existentes (verificadas por titulo).

Requiere seqcli (el endpoint REST de signals ignora el filtro; seqcli es la
unica via con filtro efectivo, verificado empiricamente).

Uso:
    python crear_signals_bots.py --apikey $SEQ_API_KEY
    python crear_signals_bots.py --apikey ... --codigo PBTH-090   # forzar uno
    python crear_signals_bots.py --apikey ... --dry-run
"""
import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

PREFIJO_TITULO = "RPA Tasks"


def seqcli(args, sub, *resto):
    cmd = shlex.split(args.seqcli) + shlex.split(sub) + [
        "-s", args.seqcli_server, "-a", args.apikey, *resto]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        msg = (r.stderr or r.stdout or "").strip()
        raise SystemExit(f"[seqcli fallo] {sub}...\n{msg}")
    return r.stdout


def detectar_codigos(args):
    fin = datetime.now(timezone.utc)
    ini = fin - timedelta(days=args.dias)
    out = seqcli(args, "query", "--no-color", "--start",
                 ini.strftime("%Y-%m-%dT%H:%M:%SZ"),
                 "--end", fin.strftime("%Y-%m-%dT%H:%M:%SZ"),
                 "-q", "select first(TaskName) as Tarea from stream "
                       "where Application = 'RPA' group by TaskName")
    codigos = set()
    for linea in out.splitlines()[1:]:
        tarea = linea.strip().strip('"').split(",")[0].strip('"')
        if "_" in tarea:
            codigos.add(tarea.split("_", 1)[0])
    return sorted(codigos)


def senales_existentes(args):
    url = (args.server.rstrip("/") +
           "/api/signals/?shared=true")
    req = urllib.request.Request(
        url, headers={"X-Seq-ApiKey": args.apikey})
    with urllib.request.urlopen(req) as r:
        return {s["Title"] for s in json.load(r)}


def crear_signal(args, codigo):
    titulo = f"{PREFIJO_TITULO} {codigo}"
    filtro = f"Application = 'RPA' and TaskName like '{codigo}%'"
    desc = (f"Eventos del bot {codigo}. Seleccionála en el dashboard o en "
            f"Events para filtrar dinámicamente.")
    out = seqcli(args, "signal create", "-t", titulo, "-f", filtro,
                 "--description", desc)
    m = re.search(r"signal-\d+", out)
    return m.group(0) if m else out.strip()


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--server", default="http://localhost:8080",
                   help="URL de Seq para la API REST (host)")
    p.add_argument("--seqcli-server", default="http://localhost",
                   help="URL de Seq que ve seqcli (dentro de Docker: localhost)")
    p.add_argument("--apikey", default=os.environ.get("SEQ_API_KEY"))
    p.add_argument("--seqcli", default="seqcli",
                   help="Comando seqcli (acepta espacios p/ Docker)")
    p.add_argument("--dias", type=int, default=30,
                   help="Ventana para detectar codigos (default 30)")
    p.add_argument("--codigo", default=None,
                   help="Crear solo este codigo (p.ej. PBTH-090), sin detectar")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    if not args.apikey:
        sys.exit("Falta --apikey o SEQ_API_KEY")

    if args.codigo:
        codigos = [args.codigo.upper()]
    else:
        codigos = detectar_codigos(args)
    print(f"[i] Codigo(s): {', '.join(codigos) or '(ninguno)'}")

    existentes = senales_existentes(args)
    creados, omitidos = [], []
    for cod in codigos:
        titulo = f"{PREFIJO_TITULO} {cod}"
        if titulo in existentes:
            omitidos.append(cod)
            continue
        if args.dry_run:
            print(f"[dry-run] crearia: {titulo}")
            creados.append(cod)
            continue
        sid = crear_signal(args, cod)
        print(f"[ok] {titulo} -> {sid}")
        creados.append(cod)

    print(f"\nResumen: {len(codigos)} codigo(s) | "
          f"{len(omitidos)} ya existian | {len(creados)} "
          f"{'se crearian' if args.dry_run else 'creados'}")


if __name__ == "__main__":
    main()
