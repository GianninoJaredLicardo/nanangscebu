# Nanang's Inventory and Sales (Flask + Firebase)

A web-based inventory system for your frozen products business.

- **Backend:** Python **Flask**
- **Pages:** HTML + CSS (pink theme), works on phone and computer
- **Database:** **Firebase Cloud Firestore** (free Spark plan, data is kept permanently)
- **Hosting:** **Render** (free plan)
- **Login:** one built-in admin account only

## What it does

- **New order:** tap products, set quantities, and it computes the total. It picks the price level automatically (SRP, Reseller from ₱2,000, Dealer from ₱5,000) or you can choose. Handles discount, payment method, amount received and change.
- **Complete sale:** the server re-checks prices and stock, deducts the stock, and saves the order with the date and time, all in one step. If there isn't enough stock, the sale is blocked.
- **Receipt:** printable receipt for every order. Void an order and the stock goes back.
- **Products:** all 50 Nanang's products with SRP, Reseller and Dealer prices, stock count and low-stock alerts.
- **Stock in:** record deliveries.
- **Sales:** today, yesterday, last 7 days, this month or any dates, with totals, packs sold and best-selling items. Export to CSV (opens in Excel).
- **Stock log:** every stock movement with date and time.
- **Backup:** download all your data from the Products page.

## Files

```
app.py              Flask app (pages, login, sales, reports)
store.py            Database code (Firebase Firestore)
pricing.py          Order math (price level, totals, stock check)
products.json       Your 50 products and prices
templates/          HTML pages
static/             CSS and JavaScript
make_password.py    Makes your admin password hash
requirements.txt    Python packages
render.yaml         Render settings
.env.example        Settings for running on your computer
```

---

## Part 1: Firebase (the database)

1. Go to https://console.firebase.google.com and click **Create a project**. Name it (e.g. `nanangs-inventory`). You can turn off Google Analytics. Stay on the free **Spark** plan.
2. **Build > Firestore Database > Create database.**
   Location: **asia-southeast1 (Singapore)**. Choose **Start in production mode**.
   Production mode blocks everyone from reading your data directly. Your Flask app still has access through its private key.
3. **Project settings (gear icon) > Service accounts > Generate new private key.**
   A `.json` file downloads. Rename it to **`serviceAccountKey.json`**.
   **Keep this file private.** It is the master key to your database. Never upload it to GitHub or send it to anyone.

You don't need Firebase Authentication or Firebase Hosting for this version.

## Part 2: Try it on your computer (optional but recommended)

1. Install **Python 3.12** from https://python.org (tick "Add Python to PATH" on Windows).
2. Put `serviceAccountKey.json` in this folder (next to `app.py`).
3. Open Command Prompt / Terminal in this folder and run:
   ```
   pip install -r requirements.txt
   python make_password.py
   ```
4. Copy `.env.example` to a new file named `.env`. Paste the `ADMIN_PASSWORD_HASH='...'` line that `make_password.py` printed, and change `SECRET_KEY` to any long random text.
5. Start it:
   ```
   python app.py
   ```
   Open http://localhost:5000 and log in with username `admin` and your password.
6. Go to **Products** and click **Load Nanang's price list**, then enter your current stock in **Stock in**.

Your data is saved in Firebase, so it will still be there after you put the app online.

## Part 3: Put it online with Render (free)

Render needs your code on GitHub.

1. Create a free account at https://github.com and make a **new private repository**.
2. Upload all the files in this folder **except** `.env` and `serviceAccountKey.json`. (The `.gitignore` file already keeps them out if you use Git or GitHub Desktop.)
3. Create a free account at https://render.com and sign in with GitHub.
4. Click **New > Blueprint**, pick your repository, and click **Apply**. Render reads `render.yaml` and sets everything up on the free plan in Singapore.
5. Render asks for two secret values:
   - **ADMIN_PASSWORD_HASH:** paste the long value from `python make_password.py` (without the quotes).
   - **FIREBASE_CREDENTIALS:** open `serviceAccountKey.json` in Notepad, copy **all** of it, and paste it.
6. Wait for the build to finish. Your link looks like **https://nanangs-inventory.onrender.com**. Open it and log in.

**If you don't want to use Blueprint:** New > Web Service, pick your repo, then set
Build command `pip install -r requirements.txt`, Start command `gunicorn app:app --workers 1 --threads 4 --timeout 60`, Instance type **Free**, and add the environment variables `PYTHON_VERSION=3.12.7`, `SECRET_KEY` (any long random text), `ADMIN_USERNAME=admin`, `ADMIN_PASSWORD_HASH`, and `FIREBASE_CREDENTIALS`.

### About the free Render plan

- If nobody opens the site for **15 minutes**, Render puts it to sleep. The next visit takes **about a minute** to load while it wakes up. After that it's fast.
- Your data is **never lost** when it sleeps, because it lives in Firebase, not on Render.
- **Optional:** to keep it awake, create a free monitor at https://uptimerobot.com that visits `https://YOUR-APP.onrender.com/healthz` every 5 minutes. One always-on app fits in Render's 750 free hours per month.

---

## Everyday use

| To do this | Go to |
|---|---|
| Sell to a buyer | **New order** → tap products → **Complete sale** |
| Record a delivery | **Stock in** |
| Fix a wrong stock count | **Products** → **Edit** → change stock and give a reason |
| Cancel a sale | **Sales** → **View** → **Void order** |
| See daily or monthly sales | **Sales** |
| Get a spreadsheet | **Sales** → **Export sales (CSV)**, or **Products** → **Export stock (CSV)** |
| Back up everything | **Products** → **Download backup** |

**Tip:** On your phone, open the site and use **Add to Home screen** so it opens like an app.

## Changing settings

On Render: **your service > Environment**, then save (it restarts automatically). On your computer: edit `.env`.

| Setting | What it does | Default |
|---|---|---|
| `ADMIN_USERNAME` | Login username | `admin` |
| `ADMIN_PASSWORD_HASH` | Login password (run `make_password.py` to change it) | |
| `RESELLER_MIN` | Order amount for Reseller price | `2000` |
| `DEALER_MIN` | Order amount for Dealer price | `5000` |
| `LOW_STOCK` | Default low-stock alert level | `5` |
| `SHOP_NAME`, `SHOP_CONTACT` | Shown on receipts | `Nanang's`, `0961 565 5590` |

To **change your password**, run `python make_password.py` and replace `ADMIN_PASSWORD_HASH` on Render.

## Backups

The free Firebase plan has no automatic backups. Once a week or month, go to **Products > Download backup** and keep the file somewhere safe (Google Drive, email to yourself).

## Free plan limits

Firebase's free plan allows **50,000 reads and 20,000 writes per day**. Opening the Home page reads about 50 records (one per product) plus today's orders, so a small shop uses only a small part of this. If a limit is ever reached, the app shows a message and works again the next day. **You are never charged** on the free plan.

## Security

- Only one account exists: the username and password hash in your settings. There's no sign-up page.
- After 5 wrong passwords, logins are blocked for 10 minutes.
- Every form is protected against fake requests (CSRF).
- The Firebase database is closed to the public; only your app's private key can reach it.

## Troubleshooting

| Problem | Fix |
|---|---|
| "Firebase key not found" | On Render, check `FIREBASE_CREDENTIALS` has the whole JSON text. On your computer, check `serviceAccountKey.json` is next to `app.py`. |
| "Wrong username or password" | Run `make_password.py` again and update `ADMIN_PASSWORD_HASH`. |
| Site takes a minute to open | It was asleep (free plan). See the UptimeRobot tip above. |
| Logged out after every restart | Set `SECRET_KEY` to a fixed value. |
