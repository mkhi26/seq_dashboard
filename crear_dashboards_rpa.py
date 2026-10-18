#!/usr/bin/env python3
"""Crea o actualiza el dashboard RPA (Automation Anywhere) en Seq vía API REST.

Uso:
    python crear_dashboards_rpa.py --server http://localhost:8080 --apikey <KEY>
    python crear_dashboards_rpa.py --apikey $SEQ_API_KEY --dry-run

Requiere solo la API key de Seq (header X-Seq-ApiKey). Sin dependencias externas.
Idempotente: si ya existe un dashboard con el título, reemplaza sus charts.
Los paneles usan Where `Application = 'RPA'`; el alcance por código base se
aplica en la UI con las señales (p. ej. RPA Tasks PBTH-156) — nada quemado.
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request

FILTRO_RPA = "Application = 'RPA'"
STYLE_Q = {"LineFillToZeroY": False, "LineShowMarkers": True, "BarOverlaySum": False,
           "UseLogarithmicScale": False, "SuppressLegend": False, "Palette": "Default"}
DURACION = "(max(@Timestamp) - min(@Timestamp)) / 10000000"


def query(measurements, groupby, tipo="Bar", where=FILTRO_RPA, having=None,
          order=None, limit=None):
    return {
        "Measurements": measurements,
        "Where": where,
        "SignalExpression": None,
        "GroupBy": groupby,
        "DisplayStyle": {"Type": tipo, **STYLE_Q},
        "Having": having,
        "OrderBy": order or [],
        "Limit": limit,
    }


def chart(title, queries, cols=6, filas=1, desc=None):
    return {"Title": title, "SignalExpression": None, "Description": desc,
            "Queries": queries,
            "DisplayStyle": {"WidthColumns": cols, "HeightRows": filas}}


PANELES = [
    chart("P1 - Eventos por nivel", [
        query([{"Value": "count(*)", "Label": "Eventos"}], ["@Level"], tipo="Pie")],
        cols=4, desc="Volumen de eventos RPA por nivel (Information/Warning/Error)."),
    chart("P2 - Tasa de error", [
        query([{"Value": "count(*)", "Label": "Total"}], ["@Level = 'Error'"],
              tipo="Pie")],
        cols=4, desc="True = eventos de nivel Error. Tasa = True / (True + False)."),
    chart("P3 - Duración por proceso (s)", [
        query([{"Value": DURACION, "Label": "DuracionSegundos"},
               {"Value": "first(TaskName)", "Label": "BotPrincipal"},
               {"Value": "any(EventType = 'End')", "Label": "Completado"},
               {"Value": "count(*)", "Label": "Eventos"}],
              ["ProcessId"], order=["DuracionSegundos DESC"], limit=50)],
        cols=8,
        desc="Una fila por ProcessId. BotPrincipal = primer evento cronológico "
             "(_01_Main). Completado=false = proceso sin evento End (posible corte)."),
    chart("P4 - Duración por sub-tarea (s)", [
        query([{"Value": DURACION, "Label": "DuracionSegundos"},
               {"Value": "any(EventType = 'End')", "Label": "Completado"},
               {"Value": "count(*)", "Label": "Eventos"}],
              ["ProcessId", "TaskName"], order=["DuracionSegundos DESC"], limit=100)],
        cols=12,
        desc="Detalle por sub-tarea dentro de cada proceso. Para ver solo "
             "ejecuciones largas añade en Having: DuracionSegundos > 600."),
    chart("P5 - Volumen por nivel (temporal)", [
        query([{"Value": "count(*)", "Label": "Eventos"}], ["@Level"], tipo="Line")],
        cols=12, filas=2,
        desc="Serie temporal por nivel; elijo el intervalo (1h/1d) con el "
             "selector de rango del dashboard."),
    chart("P6 - Últimos eventos (drill)", [
        query([{"Value": "count(*)", "Label": "N"}],
              ["@Timestamp", "@Level", "ProcessId", "ExecutionId", "TaskName",
               "EventType", "ErrorLine", "Server", "Message"],
              tipo="Table", order=["@Timestamp DESC"], limit=200)],
        cols=12, filas=2,
        desc="Recientes del alcance activo (señales seleccionadas). Drill por "
             "proceso: Events + filtro ProcessId = '<id>'."),
    chart("P7 - Tiempo de actividad por máquina (s)", [
        query([{"Value": DURACION, "Label": "VentanaSegundos"},
               {"Value": "count(EventType = 'Start')", "Label": "Inicios"},
               {"Value": "count(distinct (ProcessId))", "Label": "Procesos"},
               {"Value": "count(*)", "Label": "Eventos"},
               {"Value": "any(@Level = 'Error')", "Label": "HuboError"}],
              ["Server"], order=["VentanaSegundos DESC"], limit=50)],
        cols=8,
        desc="Una fila por máquina (Server). VentanaSegundos = del primer al "
             "último evento de la máquina en el rango activo; Inicios = "
             "ejecuciones arrancadas; HuboError = tuvo eventos Error."),
    chart("P8 - Uso por máquina: bloques (Gantt)", [
        query([{"Value": "min(@Timestamp)", "Label": "Inicio"},
               {"Value": "max(@Timestamp)", "Label": "Fin"},
               {"Value": DURACION, "Label": "DuracionSegundos"},
               {"Value": "count(*)", "Label": "Eventos"},
               {"Value": "any(@Level = 'Error')", "Label": "ConError"}],
              ["Server", "ProcessId", "TaskName"], tipo="Table", limit=500)],
        cols=12, filas=2,
        desc="Un bloque = ejecución de una sub-tarea en una máquina "
             "(Inicio -> Fin + duración + tarea). Los huecos entre bloques de "
             "una máquina son su tiempo libre. Inicio/Fin en ticks de Seq."),
    chart("P9 - Actividad por máquina en el tiempo (barras)", [
        query([{"Value": "count(*)", "Label": "Eventos"},
               {"Value": "count(EventType = 'Start')", "Label": "Inicios"}],
              ["Server"], tipo="Bar")],
        cols=12, filas=2,
        desc="Barras discontinuas por máquina en cada intervalo del selector "
             "del dashboard (p. ej. 15m). Donde no hay barra, la máquina "
             "está libre."),
]


def api(args, method, path, body=None):
    req = urllib.request.Request(
        args.server.rstrip("/") + "/api/" + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json", "X-Seq-ApiKey": args.apikey},
        method=method)
    try:
        with urllib.request.urlopen(req) as r:
            raw = r.read().decode()
            return r.status, json.loads(raw) if raw else None, r.headers
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            msg = json.loads(raw).get("Error", raw)
        except ValueError:
            msg = raw
        raise SystemExit(f"[API {e.code}] {method} {path}: {msg}")


def buscar_dashboard(args, titulo):
    _, lista, _ = api(args, "GET", "dashboards/?shared=true")
    for d in lista:
        if d["Title"] == titulo:
            return d["Id"]
    return None


def armar_body(dash, charts):
    body = {k: dash[k] for k in ("Id", "Title", "OwnerId", "IsProtected",
                                 "SignalExpression") if k in dash}
    body["Description"] = dash.get("Description")
    body["Charts"] = charts
    return body


def publicar_charts(args, dash_id, charts):
    _, dash, _ = api(args, "GET", f"dashboards/{dash_id}")
    ver = dash["Links"]["Self"].split("version=")[-1]
    _, resp, _ = api(args, "PUT", f"dashboards/{dash_id}?version={ver}",
                     armar_body(dash, charts))
    return resp


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--server", default="http://localhost:8080")
    p.add_argument("--apikey", default=os.environ.get("SEQ_API_KEY"),
                   help="API key (o env SEQ_API_KEY)")
    p.add_argument("--titulo", default="RPA - Automation Anywhere")
    p.add_argument("--dry-run", action="store_true",
                   help="Muestra los paneles sin tocar Seq")
    args = p.parse_args()
    if not args.apikey:
        sys.exit("Falta --apikey o SEQ_API_KEY")

    if args.dry_run:
        print(f"[dry-run] Se publicarían {len(PANELES)} paneles en "
              f"'{args.titulo}':")
        for c in PANELES:
            q = c["Queries"][0]
            print(f"  - {c['Title']} ({c['DisplayStyle']['WidthColumns']} cols, "
                  f"{q['DisplayStyle']['Type']}, group by {q['GroupBy'] or '—'}, "
                  f"limit {q['Limit'] or '—'})")
        return

    dash_id = buscar_dashboard(args, args.titulo)
    if dash_id:
        print(f"[ok] Dashboard existente: {dash_id} <- reemplazando charts")
    else:
        _, nuevo, headers = api(args, "POST", "dashboards/", {"Title": args.titulo})
        dash_id = nuevo["Id"]
        print(f"[ok] Dashboard creado: {dash_id} "
              f"({headers.get('Location', '').strip()})")

    resp = publicar_charts(args, dash_id, PANELES)
    print(f"[ok] {len(resp['Charts'])} charts publicados:")
    for c in resp["Charts"]:
        print(f"    {c['Id']:>12}  {c['Title']}")
    print(f"\nDashboard id: {dash_id}  |  validar: seqcli dashboard render "
          f"-i {dash_id} -c \"<titulo de panel>\"")


if __name__ == "__main__":
    main()
