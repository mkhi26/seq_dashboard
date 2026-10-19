// Power BI Desktop > Obtener datos > Consulta en blanco > Editor avanzado
// Pegar esto completo (cambia Key/URL si Seq no corre en esta maquina).
let
    Base   = "http://192.168.1.33:8080/api/events",
    Key    = "PEGA_TU_API_KEY_AQUI",
    Crudo  = Json.Document(Web.Contents(Base, [
                 Query   = [from = "0", count = "10000",
                            filter = "Application = 'RPA'"],
                 Headers = [#"X-Seq-ApiKey" = Key]])),
    T0     = Table.FromList(Crudo, Splitter.SplitByNothing()),
    T1     = Table.ExpandRecordColumn(T0, "Column1",
                 {"Timestamp", "Level", "Properties"}),
    T2     = Table.AddColumn(T1, "P", each Record.FromList(
                 List.Transform([Properties], each _[Value]),
                 List.Transform([Properties], each _[Name]))),
    T3     = Table.ExpandRecordColumn(T2, "P",
                 {"Application", "ErrorLine", "EventType", "ExecutionId",
                  "Message", "ProcessId", "Server", "TaskName"},
                 MissingField.Ignore),
    T4     = Table.RemoveColumns(T3, {"Properties"}),
    Tipos  = Table.TransformColumnTypes(T4, {
                 {"Timestamp", type datetime},
                 {"Level", type text},
                 {"Application", type text},
                 {"ErrorLine", type text},
                 {"EventType", type text},
                 {"ExecutionId", type text},
                 {"Message", type text},
                 {"ProcessId", type text},
                 {"Server", type text},
                 {"TaskName", type text}}),
    Sencillo = Table.ReorderColumns(Tipos, {
                 {"Timestamp", "Level", "Application", "Server", "ProcessId",
                  "ExecutionId", "TaskName", "EventType", "ErrorLine",
                  "Message"}})
in
    Sencillo
