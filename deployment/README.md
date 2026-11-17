# Deployment auf der Developer Platform

## Aktuelles Lab-Deployment

Seit dem 17. November 2026 ist Revision 3 im CLI-Profil `lab` ausgerollt.
Beide Komponenten verwenden `eseidinger/bot-social:latest`, von der Platform zu
`sha256:90cf54f831c36a84a6ef58603a95793edbb6faffbd43ce71c3693cb0d38ddec5`
aufgelöst. [application.json](application.json) enthält die aktive Deklaration
mit `BOT_SOCIAL_MODEL=openai:gpt-6.1-sol` und HTTPS-Ausgang zu
`api.openai.com`. Das projektspezifische `OPENAI_API_KEY`-Secret ist aktiv.
`web` und `worker` sind bereit. Die öffentliche Adresse ist
`https://web-bot-social.apps.eseidinger.de/`; ohne genehmigte
Anwendungsmitgliedschaft führt sie zur Anmeldung. Der PostgreSQL-Store
`primary` und die beiden Komponentenbindungen sind aktiv. Die Access-Policy
mit den Gruppen `readers` und `moderator` ist ebenfalls aktiv.

Zur Prüfung:

```bash
devplat --profile lab deploy get --project bot-social
devplat --profile lab components list --project bot-social
devplat --profile lab stores bindings list --project bot-social
```

Bot Social nutzt den aktuellen `platform.eseidinger.de/v1`-Vertrag der
Developer Platform (`~/dev/developer-platform/docs/developers/application-spec.md`):
ein öffentliches `web`-Service für die gebaute React-Oberfläche und die FastAPI,
ein privates, dauerhaft laufendes `worker`-Service und eine verwaltete
PostgreSQL-Ressource. Beide Services verwenden dasselbe OCI-Image, aber eigene
genehmigte Read-Write-Bindungen. Der Worker benötigt keinen HTTP-Port.

Die Platform erwartet ein öffentliches Image. Die Deklaration verwendet
`eseidinger/bot-social:latest`; bei jedem Apply löst die Platform dieses Tag
zu einem Digest auf. Die
Container laufen als UID/GID 10001 mit schreibgeschütztem Root-Dateisystem;
temporäre Dateien gehören nach `/tmp`. Das Image aus [Dockerfile](../Dockerfile)
erfüllt diese Vorgaben. `web` führt `alembic upgrade head` vor dem API-Start aus.
Der Worker wartet auf die `jobs`-Tabelle und beginnt danach mit der Job-Abholung.
Die API meldet über `/health/ready` nur dann Bereitschaft, wenn PostgreSQL
erreichbar ist. Die Web-Oberfläche und `/api` liegen auf derselben Origin.

## Vorbereitung

1. Ein Plattformadministrator legt das Projekt `bot-social` an und erteilt
   Deployment- und Hosted-Access-Berechtigungen. CLI-Anmeldung und API-URL sind
   in `~/dev/developer-platform/docs/developers/getting-started.md`
   beschrieben.
2. Das öffentliche Docker-Hub-Image bauen und pushen:

   ```bash
   docker build -t eseidinger/bot-social:latest .
   docker push eseidinger/bot-social:latest
   ```

3. Einen benannten Store anlegen und dessen aktive Bereitstellung abwarten:

   ```bash
   devplat stores create --project bot-social --file deployment/postgres.json
   devplat stores get RESOURCE_UUID
   ```

4. Zwei Bindungen für die Komponentennamen `web` und `worker` beantragen. Jede
   Bindung braucht `read-write`, weil API und Worker Datensätze schreiben:

   ```bash
   printf '{"resource_id":"%s","component":"web","mode":"read-write"}\n' "$RESOURCE_UUID" > /tmp/bot-social-web-binding.json
   printf '{"resource_id":"%s","component":"worker","mode":"read-write"}\n' "$RESOURCE_UUID" > /tmp/bot-social-worker-binding.json
   devplat stores bindings request --project bot-social --file /tmp/bot-social-web-binding.json
   devplat stores bindings request --project bot-social --file /tmp/bot-social-worker-binding.json
   ```

   Erst die aktiven, beobachtet bereitgestellten Bindungs-UUIDs in den nächsten
   Schritt übernehmen. Die Platform injiziert `PGHOST`, `PGPORT`, `PGDATABASE`,
   `PGUSER`, `PGPASSWORD` und `PGSSLMODE` getrennt in beide Komponenten. Es gibt
   kein Passwort im Deskriptor. Store-Daten bleiben bei einem Rollback oder beim
   Entfernen der Anwendung erhalten.

## Deklaration und Rollout

Der Renderer prüft Projektname und Bindungs-UUIDs und erzeugt die
vollständige JSON-Deklaration. [application.example.json](application.example.json)
zeigt deren Struktur mit Beispiel-Bindungs-UUIDs. Beispiel ohne
externes Modell:

```bash
python3 deployment/render.py \
  --project bot-social \
  --web-binding WEB_BINDING_UUID \
  --worker-binding WORKER_BINDING_UUID > /tmp/bot-social-application.json
devplat deploy validate --project bot-social --file /tmp/bot-social-application.json
devplat deploy apply --project bot-social --file /tmp/bot-social-application.json --wait
devplat components list --project bot-social
devplat logs --project bot-social --component web --tail 50
```

Für Updates zuerst die aktuelle Revision mit
`devplat deploy get --project bot-social` lesen und beim `apply` mit
`--if-match REVISION` übergeben. Ein erfolgreicher Apply bedeutet, dass die
Ressourcen erstellt wurden; zusätzlich die Live-Bereitschaft von `web` prüfen.
Migrationen und Daten sind nicht Teil eines Image-Rollbacks. Deshalb vor einem
Schema-Update die Rückwärtskompatibilität der Migration prüfen und ein Backup
bereitstellen. Nur eine `web`-Replik ist deklariert, damit nicht mehrere
API-Prozesse gleichzeitig migrieren.

## Zugriff und Modell

Der öffentliche Host heißt normalerweise
`https://web-bot-social.<apps-domain>`. Ohne aktive Hosted-Access-Policy bleibt
er gesperrt. Ein Projektadministrator legt die Gruppen `readers` und
`moderator` an und aktiviert [access-policy.json](access-policy.json):

```bash
devplat access groups create --project bot-social --name readers --display-name Readers --idempotency-key bot-social-readers
devplat access groups create --project bot-social --name moderator --display-name Moderators --idempotency-key bot-social-moderator
devplat access policy apply --project bot-social --application bot-social --file deployment/access-policy.json --wait
```

Benutzer benötigen anschließend eine genehmigte Gruppenmitgliedschaft. Die
Policy erlaubt Browser-Lesen für `readers`, Claim- und Case-Schreibpfade für
`readers`, sowie Quellkorrekturen für `moderator`. Weil der Plattformvertrag nur
statische Pfade und Präfixe kennt, teilen sich Leser-Einwände und
Moderatoraktionen unter `/api/cases/{id}` dieselbe grobe POST-Regel. Die API
prüft für alle Moderatoraktionen zusätzlich den verifizierten
`X-Platform-Principal-Group-Names`-Header und antwortet sonst mit 403. Der
Gateway muss vom Client gelieferte `X-Platform-Principal-*`-Header entfernen.
Browser-Schreibzugriffe benutzen den Platform-CSRF-Token, den der UI-Client
bereits weitergibt.

Ohne Modellkonfiguration arbeitet der Worker mit dem vorhandenen
Manual-Review-Fallback. Für ein Modell `--model openai:MODELNAME` beim Rendern
angeben und `OPENAI_API_KEY` als Platform-Projekt-Secret setzen. Der Renderer
kann mit `--outbound-dns api.openai.com` einen vom Operator
genehmigten HTTPS-Ausgang für den Worker deklarieren. Weitere Zielhostnamen
brauchen eigene `--outbound-dns`-Einträge und Operatorfreigabe; höchstens fünf
sind möglich. Öffentliche Quell-URLs mit beliebigen Hosts und HTTP-Port 80
können in diesem Platform-Profil nicht allgemein freigeschaltet werden.
URL-Recherche funktioniert nur für genehmigte Ziele; vorbereitete Quelltexte
bleiben der verlässliche Deployment-Pfad. Traces sind für beide Komponenten
aktiviert. Die Platform injiziert `OTEL_EXPORTER_OTLP_ENDPOINT` mit
`http://127.0.0.1:4318`; Bot Social leitet daraus
`OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://127.0.0.1:4318/v1/traces` ab.
`OTEL_*` darf im Platform-Deskriptor nicht manuell gesetzt werden. Die Platform
filtert Trace-Inhalte gemäß ihren Telemetrie-Regeln.
