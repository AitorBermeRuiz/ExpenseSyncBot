# Feature: real-time capture (replace Curve)

Bank notifications reach a new `POST /transactions` endpoint, are parsed deterministically,
deduplicated, categorized by the "Reglas" tab (LLM only as fallback) and appended to Google Sheets
through the Sheets API directly. Branch `feature/realtime-capture`. Engram mirror: `odd/realtime-capture/tasks`.

## Specs

- **S1** Openbank card payment push is parsed without an LLM. Real samples:
  - `Openbank info: pago con tu tarjeta **7402 el 24/10 18:18 por 14,99 EUR en WWW.AMAZON +18002796620  LU.`
  - `Openbank info: pago con tu tarjeta **7402 el 24/10 13:56 por 10,65 EUR en T175 VILLA DEL PRADO VILLA DEL PRA ES.`
  - `Openbank info: pago con tu tarjeta **7402 el 24/10 12:36 por 2,99 EUR en APPLE.COM/BILL CORK IE.`
- **S2** Received Bizum is recorded as income in the same sheet: "Registrar como ingreso", "Van en la misma hoja". Real samples:
  - `Has recibido un Bizum de 1,00  EUR de Julia Monica R.A. por Tontolaba`
  - `Has recibido un Bizum de 1,00  EUR de Julia Monica R.A. por Bizum de Julia monica`
- **S3** Handoff scope: "A new endpoint, e.g. `POST /transactions`, taking `{source, raw_text, received_at}`. Authenticate it with a token. This is a trust boundary: validate the input."
- **S4** Duplicates: user chose "A" = "En una columna extra de la hoja Gastos (columna F, la podés ocultar)" holding the fingerprint, e.g. `openbank | 24/10 18:18 | 14,99 | WWW.AMAZON`. A movement whose fingerprint is already in column F is not written again.
- **S5** Categories: "Pestaña "Reglas" en la hoja". Handoff: "rules ("Reglas" tab in Sheet) → LLM only if no rule".
- **S6** Sheets: "API directa" (not the C# MCP server). Handoff: "Sheets append, which fixes the overwrite risk of `get_next_row`."
- **S7** CaixaBank arrives by email ("Exploremos primero si caixa puede enviarnos emails"); alerts configured, no sample yet.
- **S8** Telegram confirmation: "Después".

## Tasks

- [x] T1 S1,S2,S4 — Openbank parser + fingerprint (`src/ingestion/parsers.py`) — worker — commit: 4012eaf
- [x] T2 S6 — Sheets API client: batchGet + append, service-account auth — worker — commit: 6eee64e
- [x] T3 S4,S5 — Ingestion service: Reglas lookup, LLM fallback, dedup on column F, append — worker — commit: see git log (feat(ingestion): add ingestion service)
- T4 S3 — `POST /transactions` endpoint, token auth, settings, `.env.example`, README — inline — commit: pending
- T5 S5 — Seed CSV for the "Reglas" tab from `business_rules.txt` — inline — commit: pending
- T6 S7 — CaixaBank email parser — blocked: waiting for a sample email
- T7 S3 — Deploy: env vars, service-account key on server, shortcut/n8n wiring — blocked: needs user OK on server
- T8 S8 — Telegram confirmation — deferred by user

## Log

- L1 (handoff, 2026-10-24) User wants to drop Curve; real-time capture of cards, Bizum, transfers, direct debits; "no me gustaría que un 3rd pudiera acceder a mi banco".
- L2 Shortcut tests: Notification trigger on Openbank captures body unlocked and locked (card 18:18 laptop payment). Body only, no title.
- L3 "Google Sheets ... — API directa"; Bizum recibido — "Registrar como ingreso"; CaixaBank — "Exploremos primero si caixa puede enviarnos emails. Si no, vamos por notificaciones".
- L4 "No se envian notificaciones cuando hago un bizum." Outgoing Bizum not captured; "lo de openbank no he podido cerrarlo, dejemoslo para mas tarde".
- L5 "dejemos esto de las duplicaciones para mas tarde" (shortcut fires twice; S4 dedup covers it).
- L6 CaixaBank: email chosen; "Listo, configurado, pero aun n puedo probarlo. continuemos".
- L7 Reglas: "Pestaña "Reglas" en la hoja"; Telegram: "Después"; dedup: "A".
- L8 Open: column F of Gastos must be confirmed empty before deploy (not checked).
- L9 Finding: Bizum concept is chosen by the sender and rows are written USER_ENTERED, so text cells starting with = + - @ must be escaped (formula injection). Covered in T3.
