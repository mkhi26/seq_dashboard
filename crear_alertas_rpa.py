#!/usr/bin/env python3
"""Crea las 4 alertas RPA de Seq para Automation Anywhere.

Reglas:
  1. Inicio de bot principal  -> Start de "*_01_Main"
  2. Fin de bot principal     -> End   de "*_01_Main"
  3. N fallos por tarea       -> N eventos Error de la misma TaskName en ventana
  4. Ejecucion con N+ fallos  -> N o mas Ends con Error de la misma TaskName
                                 en ventana (aprox. a "fallos seguidos")

Idempotente por titulo: las alertas ya existentes se omiten (o se actualizan
con --update). El canal de notificacion es opcional (--notification-app).

Nota honesta sobre la regla 4: el motor de alertas de Seq cuenta filas dentro
de una ventana temporal; NO verifica rachas estrictas (fallos consecutivos sin
un exito intercalado). Para eso haria falta un proceso externo con estado.

Uso:
    python crear_alertas_rpa.py --apikey $SEQ_API_KEY
    python crear_alertas_rpa.py --apikey ... --n-fallos 3 --fallos-seguidas 5
    python crear_alertas_rpa.py --apikey ... --notification-app appinstance-611
    python crear_alertas_rpa.py --apikey ... --update
    python crear_alertas_rpa.py --apikey ... --dry-run
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request

APP = "Application = 'RPA'"
COLAS = [
    {
        "sufijo": "Inicio de ejecución de bot principal",
        "descripcion": "Dispara cuando un proceso principal (_01_Main) arranca.",
        "where": f"{APP} and EventType = 'Start' and TaskName like '%_01_Main'",
        "group_by": [],
        "time_grouping": "00:01:00",
        "having": "count > 0",
        "nivel": "Information",
        "supresion": "00:05:00",
    },
    {
        "sufijo": "Fin de ejecución de bot principal",
        "descripcion": "Dispara cuando un proceso principal (_01_Main) termina.",
        "where": f"{APP} and EventType = 'End' and TaskName like '%_01_Main'",
        "group_by": [],
        "time_grouping": "00:01:00",
        "having": "count > 0",
        "nivel": "Information",
        "supresion": "00:05:00",
    },
    {
        "sufijo": "Fallos repetidos por tarea ({n} en {ventana})",
        "descripcion": "{n} o mas eventos Error de la misma tarea en una "
                       "ventana de {ventana}.",
        "where": f"{APP} and @Level = 'Error'",
        "group_by": ["TaskName"],
        "time_grouping": "{ventana}",
        "having": "count >= {n}",
        "nivel": "Error",
        "supresion": "{ventana}",
    },
    {
        "sufijo": "Ejecución con {n} fallos (ventana {ventana})",
        "descripcion": "{n} o mas ejecuciones End con Error de la misma tarea "
                       "en {ventana} (aproxima a fallos seguidos).",
        "where": f"{APP} and EventType = 'End' and @Level = 'Error'",
        "group_by": ["TaskName"],
        "time_grouping": "{ventana}",
        "having": "count >= {n}",
        "nivel": "Error",
        "supresion": "00:30:00",
    },
]

PREFIJO = "RPA"


def api(args, metodo, ruta, cuerpo=None):
    url = args.server.rstrip("/") + "/" + ruta.lstrip("/")
    datos = None
    if cuerpo is not None:
        datos = json.dumps(cuerpo, separators=(",", ":")).encode()
    req = urllib.request.Request(
        url, data=datos, method=metodo,
        headers={"Content-Type": "application/json",
                 "X-Seq-ApiKey": args.apikey})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            cuerpo_r = r.read()
            return r.status, (json.loads(cuerpo_r) if cuerpo_r else None)
    except urllib.error.HTTPError as e:
        detalle = e.read().decode("utf-8", "replace")[:200]
        return e.code, detalle


def canal(notification_app):
    if not notification_app:
        return []
    return [{
        "Id": None,
        "IncludeContributingEvents": False,
        "IncludedContributingEventLimit": None,
        "NotificationAppInstanceId": notification_app,
        "NotificationAppSettingOverrides": {},
        "NotificationMessage": None,
    }]


def construir_alertas(args):
    ctx = {"n": args.n_fallos, "ventana": args.ventana}
    alertas = []
    for i, plantilla in enumerate(COLAS, start=1):
        ctx["n"] = args.fallos_seguidas if i == 4 else args.n_fallos
        def fmt(s):
            return s.format(**ctx)
        group_by = [{"Value": g, "Label": None, "IsCaseInsensitive": False}
                    for g in plantilla["group_by"]]
        alertas.append({
            "Title": f"{PREFIJO} - {fmt(plantilla['sufijo'])}",
            "Description": fmt(plantilla["descripcion"]),
            "Where": plantilla["where"],
            "GroupBy": group_by,
            "TimeGrouping": fmt(plantilla["time_grouping"]),
            "Select": [{"Value": "count(*)", "Label": "count"}],
            "Having": fmt(plantilla["having"]),
            "NotificationLevel": plantilla["nivel"],
            "NotificationProperties": [],
            "NotificationChannels": canal(args.notification_app),
            "SuppressionTime": fmt(plantilla["supresion"]),
        })
    return alertas


def alertas_existentes(args):
    st, datos = api(args, "GET", "api/alerts/?shared=true")
    if st != 200:
        raise SystemExit(f"[!] No pude listar alertas ({st}): {datos}")
    return {a["Title"]: a for a in datos}


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--server", default="http://localhost:8080",
                   help="URL de Seq (default http://localhost:8080)")
    p.add_argument("--apikey", default=os.environ.get("SEQ_API_KEY"))
    p.add_argument("--n-fallos", type=int, default=3,
                   help="Fallos por tarea para la alerta 3 (default 3)")
    p.add_argument("--fallos-seguidas", type=int, default=5,
                   help="Fallos para la alerta 4 (default 5)")
    p.add_argument("--ventana", default="00:10:00",
                   help="Ventana temporal HH:MM:SS (default 00:10:00)")
    p.add_argument("--notification-app", default=None,
                   help="Id de app instance de salida (email/webhook/slack)")
    p.add_argument("--update", action="store_true",
                   help="Actualizar las alertas existentes en vez de omitirlas")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    if not args.apikey:
        sys.exit("Falta --apikey o SEQ_API_KEY")

    alertas = construir_alertas(args)
    existentes = alertas_existentes(args)

    creadas, actualizadas, omitidas = [], [], []
    for a in alertas:
        titulo = a["Title"]
        previa = existentes.get(titulo)
        if previa and not args.update:
            omitidas.append(titulo)
            continue
        if args.dry_run:
            accion = "actualizaria" if previa else "crearia"
            print(f"[dry-run] {accion}: {titulo}")
            (actualizadas if previa else creadas).append(titulo)
            continue
        if previa:
            ver = previa["Links"]["Self"].split("version=")[-1]
            st, res = api(args, "PUT", f"api/alerts/{previa['Id']}?version={ver}", a)
            if st >= 400:
                raise SystemExit(f"[!] Error actualizando {titulo}: {st} {res}")
            print(f"[upd] {titulo} ({previa['Id']})")
            actualizadas.append(titulo)
        else:
            st, datos = api(args, "POST", "api/alerts/", a)
            if st >= 400:
                raise SystemExit(f"[!] Error creando {titulo}: {st} {datos}")
            st2, lista = api(args, "GET", "api/alerts/?shared=true")
            nueva = next((x for x in lista if x["Title"] == titulo), None)
            aid = nueva["Id"] if nueva else "?"
            print(f"[ok]  {titulo} -> {aid}")
            creadas.append(titulo)

    print(f"\nResumen: {len(creadas)} "
          f"{'se crearian' if args.dry_run else 'creadas'} | "
          f"{len(actualizadas)} "
          f"{'se actualizarian' if args.dry_run else 'actualizadas'} | "
          f"{len(omitidas)} ya existian")
    if args.dry_run:
        return
    st, lista = api(args, "GET", "api/alerts/?shared=true")
    print("\nAlertas RPA en Seq:")
    for a in sorted(lista, key=lambda x: x["Id"]):
        if a["Title"].startswith(PREFIJO + " - "):
            act = a.get("Activity") or {}
            print(f"  {a['Id']}  {a['Title']:<52} "
                  f"check={str(act.get('LastCheck'))[11:19]} "
                  f"trig={act.get('LastCheckTriggered')} "
                  f"total={act.get('TotalOccurrences')}")


if __name__ == "__main__":
    main()
