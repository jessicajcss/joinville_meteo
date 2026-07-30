# Push notifications — step-by-step setup (beginner friendly)

Goal: when a **risk Alerta** appears, people who tapped **"Receber alertas"** get a phone
notification. This runs free on **Cloudflare**. You set it up **once**, in about 15 minutes.

You do everything in a terminal (Command Prompt / PowerShell / Anaconda Prompt), **inside the
`push/` folder** of your project. To get there:

```bash
cd "C:\Users\air_p\Desktop\2026\PostDoc_UDESC\projeto_resposta_eventos\dashboard\joinville_meteo\push"
```

---

## The 5 values you'll create (and where each one goes)

The one thing that confuses people is that this uses a few keys and each goes in a **different
place**. Here's the whole map — keep it open while you work. You'll fill it in as you go.

| # | Value | You get it in | It goes into |
|---|-------|---------------|--------------|
| A | **VAPID public key** | Step 3 | `wrangler.toml` **and** `site/assets/js/push.js` |
| B | **VAPID private key** | Step 3 | a Cloudflare secret (Step 6) — **never in a file** |
| C | **KV namespace id** | Step 4 | `wrangler.toml` |
| D | **SEND_SECRET** (you invent it) | Step 6 | a Cloudflare secret + you keep a copy to test |
| E | **Worker URL** | Step 7 | `site/assets/js/push.js` |

Rule of thumb: **public** things (A, E) go in files; **private** things (B, D) go into Cloudflare
secrets and are never written in a file or committed to Git.

---

## Step 1 — Install Wrangler (Cloudflare's tool)

In the terminal:

```bash
npm install -g wrangler
```

Check it worked:

```bash
wrangler --version
```

You should see a version number (e.g. `4.x.x`). If "command not found", close and reopen the
terminal and try again.

## Step 2 — Log in to Cloudflare

First make a **free** account at <https://dash.cloudflare.com/sign-up> (email + password, no card).
Then, in the terminal:

```bash
wrangler login
```

Your browser opens and asks "Allow Wrangler to access your account?" → click **Allow**. The terminal
then says *"Successfully logged in."* Done.

## Step 3 — Create your VAPID keys  →  values A and B

```bash
npx web-push generate-vapid-keys
```

It prints two long lines, like:

```
Public Key:
BJ8k...very long...q7Y      ← this is value A (VAPID PUBLIC key)
Private Key:
h3Nc...shorter...9s0        ← this is value B (VAPID PRIVATE key)
```

Copy both somewhere safe for the next steps. **A** is public (goes in files). **B** is secret.

## Step 4 — Create the storage (KV)  →  value C

This is where subscriptions are stored.

```bash
wrangler kv namespace create SUBSCRIPTIONS
```

*(If that errors, your Wrangler is older — use `wrangler kv:namespace create SUBSCRIPTIONS` instead.)*

It prints something like:

```
[[kv_namespaces]]
binding = "SUBSCRIPTIONS"
id = "a1b2c3d4e5f6......"      ← this is value C
```

Copy that **id**.

## Step 5 — Fill in `wrangler.toml`

Open **`wrangler.toml`** (in the `push/` folder) in any text editor. Change these lines:

- Find `id = "PASTE_YOUR_KV_NAMESPACE_ID_HERE"` → replace with your **value C**.
- Find `VAPID_PUBLIC_KEY = "PASTE_YOUR_VAPID_PUBLIC_KEY"` → replace with your **value A**.

Leave `VAPID_SUBJECT`, `SITE_BASE_URL`, `ALLOWED_ORIGIN` as they are (already set for your site).
Save the file.

## Step 6 — Set the two secrets  →  value B and value D

Secrets are stored **inside Cloudflare**, never in a file. Run these two commands one at a time:

```bash
wrangler secret put VAPID_PRIVATE_KEY
```
It asks you to paste a value → paste your **value B** (the VAPID private key) → Enter.

```bash
wrangler secret put SEND_SECRET
```
It asks for a value → **make one up**: any long random string, e.g. `joinville-8f3k9x2p-alertas`.
That's **value D** — write it down, you'll use it in Step 9 to send a test.

## Step 7 — Deploy the Worker  →  value E

```bash
wrangler deploy
```

When it finishes it prints your Worker address:

```
https://joinville-push.YOURNAME.workers.dev     ← this is value E
```

Copy it. You can also open it in a browser — it will say `{"error":"not found"}`, which is normal
(it means the Worker is alive).

## Step 8 — Tell the website about the Worker

Open **`site/assets/js/push.js`** and change the **first two lines** of real code:

```js
var WORKER_URL = 'https://joinville-push.YOUR-SUBDOMAIN.workers.dev'; // ← paste value E
var VAPID_PUBLIC_KEY = 'REPLACE_WITH_YOUR_VAPID_PUBLIC_KEY';          // ← paste value A
```

Save. Then commit and push your site the way you normally do, so GitHub Pages publishes it.
(Until you do this, the button on the site just says *"servidor a configurar"* — that's expected.)

## Step 9 — Try it on your phone

1. Open the live site on your phone and **install it**:
   - **iPhone:** Share button → *Adicionar à Tela de Início*. Then open it from the Home Screen.
     (On iPhone, notifications **only** work from the installed app — Apple's rule.)
   - **Android / desktop Chrome:** accept the "Install" prompt, or use the menu → *Install*.
2. In the installed app, tap **🔔 Receber alertas** and allow notifications.
3. Now send yourself a test. On your computer, paste this — **replace the URL with value E and the key
   with value D**:

   ```bash
   curl -X POST "https://joinville-push.YOURNAME.workers.dev/test?key=YOUR_SEND_SECRET"
   ```

   Your phone should buzz with a **"Joinville — teste"** notification, and the terminal shows
   `{"ok":true,"sent":1,...}`.

That's everything. From now on the Worker checks for alerts **every hour** and notifies
automatically — you don't touch it again.

---

## When will real notifications fire?

Only when a hazard reaches **Alerta** (severe): rain ≥ 10 mm/h, wind ≥ 17.2 m/s, heat ≥ 36 °C or
frost ≤ 3 °C, or apparent temperature ≥ 41 °C — observed on *Agora* or forecast on *Previsão*.
The `/test` above is how you confirm delivery works even when there's no real alert.

To also notify on the milder **Atenção** level: open `worker.js`, change
`const NOTIFY_LEVEL = 'alert'` to `'warn'`, and run `wrangler deploy` again.

## If something doesn't work

- **Button still says "servidor a configurar"** → Step 8 not done (or site not re-published yet).
- **iPhone: nothing happens when you tap** → you must *install* the app and open it from the Home
  Screen first; Safari tabs can't receive push (Apple).
- **`/test` says `unauthorized`** → the `key=` in your curl doesn't match value D (SEND_SECRET).
- **`/test` says `"sent":0`** → nobody is subscribed on that device yet — do Step 9.2 first.
- **Want to watch what the Worker is doing** → run `wrangler tail` and trigger a `/test`.
- **Re-deploy anytime** you change `worker.js`/`wrangler.toml`: just `wrangler deploy` again.

## Checking the code is correct (optional, for peace of mind)

```bash
npm install      # one-time, installs test-only tools
npm test         # runs the crypto + alert + Worker tests — all should pass
```
