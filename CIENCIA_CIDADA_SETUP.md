# Ciência Cidadã — setup (once, ~15 min)

The **Ciência Cidadã** page (`site/ciencia_cidada.html`) is ready. It already: explains the project in
plain language, lets a person pick their **bairro**, shows **what the WRF forecast says for that bairro
right now**, and has a footer with the project + your contact. The only thing to wire up is **where the
answers go** — because a static site (GitHub Pages) can't save a file by itself, the answers flow:

```
person answers the Google Form  →  Google Sheet (responses)  →  published as CSV
        →  GitHub Action pulls it  →  site/data/ciencia_cidada.csv  (in your repo)
```

Nobody needs a login to answer. Follow the steps once.

---

## 1 · Create the Google Form

1. Go to **forms.google.com** → blank form. Title it e.g. **"Ciência Cidadã — Chuva em Joinville"**.
2. Add these questions (keep the wording simple):

   | # | Question | Type | Options |
   |---|----------|------|---------|
   | 1 | **Seu bairro** | Dropdown (or Short answer) | the 43 bairros (or let people type) |
   | 2 | **Está chovendo agora onde você está?** | Multiple choice | `Sim` · `Não` |
   | 3 | **Como está a chuva?** | Multiple choice | `Não está chovendo` · `Garoa (bem fininha)` · `Fraca` · `Moderada (dá pra molhar)` · `Forte (temporal)` |
   | 4 | **Previsão do modelo (automático)** | Short answer | *(leave blank — the page fills this in; optional)* |
   | 5 | **Comentário (opcional)** | Paragraph | — |

3. **Settings → Responses:** turn **OFF** "Collect email addresses" (keep it anonymous), allow more than
   one response. Don't make it a quiz.

> Question 4 is optional but valuable: it stores *what the model predicted* next to *what the person saw*,
> so you can later measure forecast accuracy. The page fills it automatically if you do step 4 below.

## 2 · Link the responses to a Sheet

In the Form, open the **Responses** tab → the green **Sheets** icon → **Create a new spreadsheet**. This
sheet now gets one row per answer, with a `Carimbo de data/hora` (timestamp) column added automatically.

## 3 · Embed the Form in the page

1. In the Form, click **Send** (top right) → the **`< >`** (embed) tab → copy the **`src`** URL
   (looks like `https://docs.google.com/forms/d/e/AAAA.../viewform?embedded=true`).
2. Open `site/ciencia_cidada.html`, find the **`CONFIG`** block near the top of the `<script>`, and paste
   it:
   ```js
   FORM_EMBED_URL: "https://docs.google.com/forms/d/e/AAAA.../viewform?embedded=true",
   ```
   Save. The questionnaire now appears inside the page. (Until you do this, the page shows a friendly
   "not configured yet" note — everything else still works.)

## 4 · (Optional) Pre-fill bairro + forecast automatically

So the person doesn't type their bairro twice and the forecast is recorded:

1. In the Form → **⋮ (three dots) → Get pre-filled link**. Choose any bairro in Q1 and type anything in
   Q4, then **Get link → Copy link**.
2. The link contains `entry.NUMBERS=...` for each field. Note the number for **Bairro** (Q1) and for
   **Previsão do modelo** (Q4).
3. In `CONFIG.PREFILL` set:
   ```js
   PREFILL: {
     enabled: true,
     base: "https://docs.google.com/forms/d/e/AAAA.../viewform?embedded=true&usp=pp_url",
     bairro_entry:   "entry.111111111",   // Bairro
     forecast_entry: "entry.222222222"    // Previsão do modelo (automático)
   }
   ```
   Now, when a visitor picks their bairro, the embedded form arrives with the bairro and the current
   forecast already filled in.

## 5 · Publish the Sheet as CSV and tell GitHub where it is

1. Open the **responses Google Sheet** → **File → Share → Publish to web**.
2. Choose the **responses sheet/tab**, format **Comma-separated values (.csv)** → **Publish** → copy the
   URL it gives you.
3. In your GitHub repo: **Settings → Secrets and variables → Actions → Variables tab → New repository
   variable**:
   - **Name:** `CITIZEN_SHEET_CSV_URL`
   - **Value:** the published CSV URL from step 2.
4. The workflow **`.github/workflows/citizen-science-sync.yml`** now pulls the responses into
   `site/data/ciencia_cidada.csv` every 6 hours (and you can run it on demand from the **Actions** tab →
   *Citizen-science sync* → *Run workflow*). The page reads that file to show "N pessoas já participaram".

> **Privacy:** publishing the sheet makes the *responses* readable by anyone with the link — that's fine
> here because we collect no names or emails, only bairro + observation + time. Keep it that way (email
> collection stays OFF in step 1). The published CSV contains only what the Form asks.

---

## Recap of what's already in the repo

- `site/ciencia_cidada.html` — the page (with the `CONFIG` block to fill in steps 3–4).
- `site/data/ciencia_cidada.csv` — starts empty (header only); the Action overwrites it with real responses.
- `.github/workflows/citizen-science-sync.yml` — the Sheet→repo sync (no-ops until `CITIZEN_SHEET_CSV_URL` is set).
- The nav link **"Ciência cidadã"** was added to every page.

Questions? `jessica.jcss@gmail.com`.
