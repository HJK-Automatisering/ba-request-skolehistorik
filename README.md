# ba-request-skolehistorik

Worker-service, der overvåger bestillinger af skolehistorik i XFlow, slår
barnets indskrivningshistorik op i Skolekube, genererer en PDF og sender den
til bestilleren. Kører som én container i Portainer.

## Flow

Hvert 5. minut (konfigurerbart):

1. Hent ubehandlede rækker fra request-loggen i XFlow (`status IS NULL`,
   samt fejlede med retries tilbage)
2. Slå `child_cpr` op i Skolekubes sensitive dimensionstabel → `student_id`
3. Hent historikken fra Skolekubes enrollment-tabel
4. Generér PDF (Jinja2-skabelon → WeasyPrint)
5. Send PDF'en til `request_user_email` og markér rækken `sent`

Databaser og tabelnavne er konfigurerbare — se [Miljøvariabler](#2-miljøvariabler).

Fejler en bestilling (fx CPR ikke fundet), markeres den `failed` med
fejlbesked i `error_message`, og resten af køen fortsætter. Fejlede rækker
prøves igen op til `MAX_ATTEMPTS` gange.

## Lokal udvikling

VS Code er sat op til at bruge projektets eget venv via
[.vscode/settings.json](.vscode/settings.json). Efter et frisk klon skal
venv'et oprettes én gang:

```
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Bemærk at `weasyprint` kan installeres på Windows, men ikke importeres uden
GTK-bibliotekerne. Det er kun et problem, hvis du vil køre koden direkte på
Windows — autocomplete og type-tjek i editoren virker fint, og selve
afviklingen sker altid i containeren.

## Opsætning

### 1. Database

Request-loggen `XFlow.dbo.skolekube_enrollment_request_log` skal ud over de
oprindelige felter have disse fire kolonner, som servicen bruger til at holde
styr på, hvad der er behandlet:

| Kolonne | Type | Bemærkning |
| --- | --- | --- |
| `status` | `nvarchar(20)` NULL | `NULL` = afventer, ellers `sent` / `failed` |
| `processed_at` | `datetime` NULL | sættes ved både succes og fejl |
| `error_message` | `nvarchar(MAX)` NULL | fejlårsag, ryddes ved succes |
| `attempts` | `int` NOT NULL, default `0` | tæller forsøg, begrænser retries |

Servicen behandler rækker hvor `status IS NULL`, samt `failed`-rækker med
færre end `MAX_ATTEMPTS` forsøg. Eksisterende rækker har `status = NULL` og
bliver derfor behandlet ved første kørsel — skal de springes over, så sæt dem
til en anden værdi (fx `skipped`), før servicen startes.

DB-brugeren skal have `SELECT` + `UPDATE` på request-loggen, samt `SELECT` på
de to Skolekube-tabeller.

### 2. Miljøvariabler

Server, bruger og password er fælles for begge databaser; kun databasenavn og
tabel skifter. Alle ni er påkrævede — der er ingen defaults, så en manglende
variabel fejler ved opstart med et tydeligt navn.

| Variabel | Eksempel |
| --- | --- |
| `DB_DRIVER` | `ODBC Driver 18 for SQL Server` |
| `DB_SERVER` | `sqlserver.example.local` |
| `DB_USERNAME` | `skolehistorik_svc` |
| `DB_PASSWORD` | *(secret)* |
| `XFLOW_DB` | `XFlow` |
| `XFLOW_TABLE` | `dbo.skolekube_enrollment_request_log` |
| `SKOLEKUBE_DB` | `Skolekube` |
| `SKOLEKUBE_SENSITIVE_TABLE` | `dw.dim_student_sensitive` |
| `SKOLEKUBE_ENROLLMENT_TABLE` | `dw.fact_enrollment` |

Ved `MAILER=api` kræves desuden `MAIL_API_KEY` — mail-clientens `API_KEY`.
Med `MAILER=console` er den ikke nødvendig, så flowet kan testes uden den.

Valgfrit: `POLL_INTERVAL_SECONDS` (300), `MAX_ATTEMPTS` (3), `MAILER`
(`console`), `MAIL_SUBJECT`, `OUTPUT_DIR`, `TZ` (`Europe/Copenhagen`),
`MAIL_API_URL` (`http://mail-client-api:8000`), `SHARED_DIR` (`/shared`),
`MAIL_API_TIMEOUT` (30).

Tabelnavnene kan ikke sendes som SQL-parametre og interpoleres derfor ind i
forespørgslerne. De valideres som `skema.tabel`-identifikatorer ved opstart,
så en tastefejl fejler med det samme frem for inde i en query.

Anførselstegn om værdierne er valgfrie: `docker run --env-file` bevarer dem,
mens Portainer ikke bruger dem, så servicen fjerner omsluttende `'` og `"`
selv. Et password med `#` kan derfor stå i quotes lokalt og uden i Portainer,
uden at der skal ændres noget.

### 3. Portainer

[docker-compose.yml](docker-compose.yml) er skrevet til at køre begge steder,
med to linjer der byttes om ved deployment — som markeret i filen:

- **Lokalt:** `build: .` er aktiv, og `env_file` peger på `.env`
- **Portainer:** kommentér `image:`-linjen ind, fjern `build: .`, og ret
  `env_file` til `stack.env`

Variablerne sættes i stackens miljø-sektion i Portainer, hvorfra de skrives
til `stack.env`. `DB_PASSWORD` sættes som skjult variabel.

`restart: on-failure` er valgt bevidst frem for `unless-stopped`: workeren
kører i et uendeligt loop og bør kun genstartes, hvis den faktisk fejler. Med
`unless-stopped` ville en `--once`-kørsel blive genstartet i det uendelige.

### 4. Test uden mail (part 1)

Med `MAILER=console` (standard) sendes der ingen mails — PDF'erne gemmes i
volumet `pdf-output` (`/data/output` i containeren), og loggen viser, hvem
der ville have fået dem.

Workeren har to flags, der gør testen hurtigere end at vente på
5-minutters-intervallet:

```
docker run --rm --env-file .env ba-request-skolehistorik:latest python -m app.main --check
```

`--check` verificerer forbindelsen til begge databaser, bekræfter at
statuskolonnerne findes, og lister de bestillinger der ligger i kø — uden at
behandle noget. Exit-kode 0 = alt OK. Kør den først.

```
docker run --rm --env-file .env -v pdf-output:/data/output ba-request-skolehistorik:latest python -m app.main --once
```

`--once` kører én runde og afslutter. Herefter kan du tjekke `status` og
`error_message` på rækken i request-loggen.

### PDF-layout uden database

Mappen `tests/` indeholder et smoke-script, der genererer PDF'er ud fra
fabrikerede data uden at røre databasen — nyttigt når skabelonen skal
justeres. Mappen er bevidst holdt uden for git, så den findes ikke i et
frisk klon. Scriptet mountes ind i containeren ved kørsel:

```
docker run --rm -v "$PWD/out:/out" -v "$PWD/tests:/srv/tests:ro" ba-request-skolehistorik:latest python /srv/tests/smoke_pdf.py /out
```

## Mailafsendelse

Ved `MAILER=api` sendes PDF'en via
[mail-client](https://github.com/HJK-Automatisering/mail-client). Det API tager
ikke filindhold i JSON, men **absolutte stier til filer på et delt volume**.
Integrationen kræver derfor to ting ud over API-nøglen:

| | Navn | Formål |
| --- | --- | --- |
| Netværk | `mail-client_default` (external) | Gør `http://mail-client-api:8000` tilgængelig |
| Volume | `mail-client-external-attachments` → `/shared` | Filen skrives her og læses af mail-clienten |

Begge er sat op i [docker-compose.yml](docker-compose.yml). Volumet skal
oprettes i Portainer af mail-client-stacken, før denne stack kan starte.

Flowet pr. bestilling: PDF'en skrives til `/shared`, stien sendes i
`POST /send`, og filen slettes igen umiddelbart efter — også hvis kaldet
fejler. Personfølsomme data ligger derfor ikke på det delte volume længere end
selve kaldet varer.

Fejler kaldet, kommer mail-clientens svartekst med i `error_message` på rækken,
så årsagen er synlig uden at skulle grave i containerlogs.

## GDPR

- Servicen logger aldrig CPR-numre — kun bestillingens `id`
- PDF-filnavne indeholder bestillings-id, ikke CPR
- PDF'en slettes fra det delte volume umiddelbart efter afsendelse
- Med `MAILER=console` bliver PDF'erne derimod liggende i `output/` og i
  `pdf-output`-volumet — husk at tømme dem efter testfasen
- Overvej stadig, om fuldt CPR skal med i PDF'en, og om almindelig e-mail er
  en godkendt kanal til indholdet
