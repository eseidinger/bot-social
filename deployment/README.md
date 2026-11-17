# Deployment auf der Developer Platform

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

## Deployment prüfen

`devplat deploy get` zeigt die aktuelle Revision und `devplat components list`
den aufgelösten Image-Digest und die Bereitschaft beider Komponenten an:

```bash
devplat --profile lab deploy get --project bot-social
devplat --profile lab components list --project bot-social
devplat --profile lab stores bindings list --project bot-social
```

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

Für das Modell mit der empfohlenen Rechercheliste zusätzlich
`--model openai:gpt-6.1-sol --outbound-dns api.openai.com \
--research-hosts-file deployment/research-hosts.json` an den Renderer übergeben.

Für Updates zuerst die aktuelle Revision mit
`devplat deploy get --project bot-social` lesen und beim `apply` mit
`--if-match REVISION` übergeben. Ein erfolgreicher Apply bedeutet, dass die
Ressourcen erstellt wurden; zusätzlich die Live-Bereitschaft von `web` prüfen.
Migrationen und Daten sind nicht Teil eines Image-Rollbacks. Deshalb vor einem
Schema-Update die Rückwärtskompatibilität der Migration prüfen und ein Backup
bereitstellen. Nur eine `web`-Replik ist deklariert, damit nicht mehrere
API-Prozesse gleichzeitig migrieren.

## GitHub Actions

[deploy.yml](../.github/workflows/deploy.yml) prüft Backend und Frontend bei
Pull Requests. Bei einem Push auf `main` oder einem manuellen Start von `main`
baut es anschließend das Image für `linux/amd64`, veröffentlicht
`eseidinger/bot-social:latest` und einen Tag mit der Commit-SHA auf Docker Hub
und rollt [application.json](application.json) in das bestehende Projekt
`bot-social` aus. Der Workflow validiert die Deklaration, vergleicht den von der
Platform aufgelösten Digest mit dem gebauten Image, verwendet die aktuelle
Revision mit `--if-match` und prüft danach die Bereitschaft beider Komponenten.
Die Jobs laufen für das Lab-Deployment nacheinander. Store, Bindungen,
Access-Policy und das `OPENAI_API_KEY`-Projekt-Secret werden nicht neu angelegt.

In GitHub unter **Settings → Environments → lab** die folgenden Werte für den
Release-Job hinterlegen:

| Name | Art | Zweck |
| --- | --- | --- |
| `DOCKERHUB_USERNAME` | Secret | Docker-Hub-Konto mit Schreibrecht auf `eseidinger/bot-social` |
| `DOCKERHUB_TOKEN` | Secret | Docker-Hub-Zugriffstoken |
| `PLATFORM_API_URL` | Variable | URL der Developer-Platform-API |
| `PLATFORM_TOKEN_ENDPOINT` | Variable | OIDC-Token-Endpunkt |
| `PLATFORM_CLIENT_ID` | Secret | Projektbezogener Deployment-Client |
| `PLATFORM_CLIENT_SECRET` | Secret | Secret dieses Deployment-Clients |

Ein Platform-Administrator muss den projektbezogenen Deployment-Client vorab
einrichten. Eine lokale menschliche `devplat`-Anmeldung steht GitHub Actions
nicht zur Verfügung. Der Workflow installiert `developer-platform-cli==1.0.0`
aus PyPI.

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
Der API-Span übernimmt den `traceparent` des Gateways; Jobs führen diesen
Kontext im Worker fort. Dienstname und parentbasiertes Sampling stammen aus den
von der Platform injizierten `OTEL_*`-Variablen. HTTP-Spans enthalten
Routen-Vorlagen statt konkreter URL-Pfade.
`OTEL_*` darf im Platform-Deskriptor nicht manuell gesetzt werden. Die Platform
filtert Trace-Inhalte gemäß ihren Telemetrie-Regeln.
Ein berechtigter Projektleser kann einen bekannten Trace innerhalb der
Aufbewahrungszeit abrufen:

```bash
devplat --profile lab traces get TRACE_ID --project bot-social
```

Die Platform bietet keine freie Trace-Suche über die CLI.

Die Container-Ausgabe besteht aus einzelnen JSON-Logzeilen mit `level`,
`message`, `logger` und bei aktivem Span `traceId` und `spanId`. API-Anfragen
werden mit Routen-Vorlagen geloggt; Worker-Jobs mit Statusübergängen ohne
Claim-Inhalt oder Quell-URL. Die Platform kann diese Logs zentral behalten:

```bash
devplat --profile lab logs retained --project bot-social
```

Ein `ResearchFetchError`-Span bezeichnet einen fehlgeschlagenen Seitenabruf;
der Recherche-Job kann trotzdem weiterlaufen. Der zugehörige Worker-Logeintrag
nennt den freigegebenen Host und den sicheren Fehlergrund ohne die aufgerufene
URL. Bei einer vom Benutzer eingereichten URL erscheint der Grund zusätzlich
als Recherchehinweis im Fall. HTTP 203 wird als erfolgreiche, aber möglicherweise
durch einen Vermittler veränderte Antwort verarbeitet, wenn der Inhalt die
üblichen Sicherheits- und Textprüfungen besteht. PubMeds Cookie-Sperrseite
wird dabei ausdrücklich abgelehnt. Ein Recherchehinweis macht den Vorbehalt
vor der Freigabe eines Urteils sichtbar.

## Wissenschaftliche Recherchequellen

Die Datei [research-hosts.json](research-hosts.json) ist die konfigurierbare
Liste exakter HTTPS-Hosts. Der Renderer schreibt sie als
`BOT_SOCIAL_RESEARCH_HOSTS` in die Platform-Konfiguration und fügt für jeden
Host einen HTTPS-Egress-Eintrag für den Worker hinzu. Der Agent übergibt die
Hosts an die native Websuche. Der eigene `open_page`-Abruf prüft den Host vor
jeder Netzverbindung und erneut nach jeder Weiterleitung. Andere Hosts und
unverschlüsselte HTTP-URLs werden nicht als Belege abgerufen. Review und
Editorial arbeiten anschließend nur mit den gespeicherten Belegen.

| Host | Geeignet für |
| --- | --- |
| `pubmed.ncbi.nlm.nih.gov` | Biomedizinische Literatur und Artikel-URLs mit PMID ([PubMed](https://pubmed.ncbi.nlm.nih.gov/about/)); ein Abstract ersetzt nicht den Volltext. |
| `arxiv.org` | Frei zugängliche Forschungsmanuskripte aus mehreren Fachgebieten ([arXiv](https://info.arxiv.org/about/reports/2023_arXiv_annual_report.pdf)); Publikations- und Reviewstatus prüfen. |
| `eutils.ncbi.nlm.nih.gov` | Offizielle [NCBI-EFetch-API](https://www.ncbi.nlm.nih.gov/books/NBK25499/#chapter4.EFetch) für PubMed-Abstracts; die Anwendung prüft die PMID und speichert die API-Adresse als Recherchehinweis. |
| `ourworldindata.org` | Aufbereitete Daten und Analysen zu Gesundheit, Klima, Bevölkerung und weiteren Themen ([Our World in Data](https://ourworldindata.org/about)); die zugrunde liegende Datenquelle prüfen. |

Die Platform erlaubt höchstens fünf Egress-Ziele pro Komponente. Mit
`api.openai.com` bleiben daher vier Plätze für Recherchequellen. Andere
Quellen erfordern eine geänderte Liste, Operatorfreigabe und einen neuen Apply.
Auch ein Treffer auf einem erlaubten Host kann zu einem anderen Host
weiterleiten; dann wird der Abruf abgelehnt und der Recherche-Job kann den
Treffer nicht als verifizierten Beleg verwenden.
Die native Websuche begrenzt Treffer auf diese Domains, kann dabei aber auch
Subdomains liefern. Der Agent sucht deshalb zusätzlich mit `site:`-Hinweisen
und bevorzugt direkte Artikel-, Abstract- oder Datenseiten auf den exakten
Hosts. Der Fetcher bevorzugt öffentliche IPv4-Adressen, wenn DNS auch IPv6
liefert, weil der Platform-Egress nur IPv4 unterstützt. Für numerische PubMed-
Artikel-URLs ruft er den Abstract über EFetch als XML ab, prüft die PMID und
liefert die Abstract-Abschnitte als zitierbare Passagen. Die kanonische
PubMed-URL bleibt als Quelle erhalten; die EFetch-Adresse steht im
Recherchehinweis. PLOS entfällt im Lab-Profil wegen des Limits von fünf
Egress-Zielen pro Komponente.
Wenn eine Recherche keine Belege findet, kann eine moderierende Person den Fall
über **Retry research** erneut recherchieren lassen. Das startet einen neuen
idempotenten Job, sofern noch kein Beleg vorliegt und kein Job aktiv ist.
Der Recherche-Agent darf bis zu 20 Tool-Aufrufe und 16 Modellanfragen nutzen;
seine Anweisung begrenzt die Suche auf sechs Abfragen und acht Seitenversuche.
So bleibt Raum für fehlgeschlagene Abrufe, während die Recherche begrenzt ist.
