# Operación automática local

El motor se ejecuta con `python3 run.py --run-jobs`. Lee `config/automation.json`, corre sólo las tareas vencidas y deja una fila de auditoría y salud por fuente en SQLite. El servidor web y el motor son procesos separados: si una fuente falla, la portada sigue funcionando con la última información conocida.

## Configuración de fuentes

`config/automation.json` no contiene secretos. Configura únicamente endpoints HTTPS públicos o autorizados. Antes de habilitar Generalitat o Diputació, prueba el conector de forma limitada:

```bash
python3 run.py --sync generalitat --endpoint 'https://…' --page-size 100 --max-rows 100 --sync-timeout 60
```

Después copia el endpoint en el trabajo correspondiente y cambia `enabled` a `true`. Cada fuente tiene límite de filas, tiempo total y frecuencia independientes. Nunca se interpreta la ausencia en una respuesta parcial como baja o cancelación.

## launchd en macOS

La vía recomendada instala un plist con rutas absolutas de este checkout:

```bash
python3 run.py --install-launchd
```

También puede crearse manualmente:

Crea `~/Library/LaunchAgents/com.loagendo.engine.plist` con este contenido, sustituyendo las rutas absolutas de este checkout:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.loagendo.engine</string>
  <key>ProgramArguments</key><array><string>/usr/bin/env</string><string>python3</string><string>/RUTA/loagendo/run.py</string><string>--run-jobs</string></array>
  <key>WorkingDirectory</key><string>/RUTA/loagendo</string>
  <key>StartInterval</key><integer>900</integer>
  <key>StandardOutPath</key><string>/RUTA/loagendo/reports/automation.log</string>
  <key>StandardErrorPath</key><string>/RUTA/loagendo/reports/automation-error.log</string>
</dict></plist>
```

`StartInterval` despierta el motor cada 15 minutos; las frecuencias efectivas siguen siendo las de `automation.json` (por ejemplo, cada 3 o 6 horas). Cárgalo con:

```bash
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.loagendo.engine.plist
launchctl kickstart -k gui/$(id -u)/com.loagendo.engine
```

Comprueba el resultado con `python3 run.py --automation-status`. La integración de OpenAI no forma parte de este motor todavía: debe entrar como una tarea independiente con presupuesto, evaluación y trazabilidad de prompts.
