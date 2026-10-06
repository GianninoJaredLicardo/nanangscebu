# Nanang's Authentic Recipes Mandaue - Cebu Distributor: Inventory and Sales (Flask + Firebase)

A web-based inventory system for your frozen products business.

- **Backend:** Python **Flask**
- **Pages:** HTML + CSS (pink theme), works on phone and computer
- **Database:** **Firebase Cloud Firestore** (free Spark plan, data is kept permanently)
- **Hosting:** **Railway**
- **Login:** one built-in admin account only

## What it does

- **New order:** tap products, set quantities, and it computes the total. You choose the price level (SRP, Reseller or Dealer). Handles discount and payment method. Returning buyers' contact number and address fill in by themselves.
- **Complete sale:** the server re-checks prices and stock, deducts the stock, and saves the order with the date and time, all in one step. If there isn't enough stock, the sale is blocked. Orders are numbered per day: `260929-001`, `260929-002`, ...
- **Receipt:** printable receipt for every order, plus **Download JPEG** and (on phones) **Share** to send it on Messenger or Viber. Void an order and the stock goes back.
- **Draft quote:** make a price estimate without touching stock. Customer name, contact number and address are optional. **Save draft** keeps it in **History** so you can reopen, edit, print or delete it anytime. **Turn into order** moves it to New order when the buyer agrees.
- **To collect:** every order saved with payment "To collect", who owes what, and a **Mark as paid** button.
- **Products:** all 61 Nanang's Authentic Recipes products (including per-pack prices) with SRP, Reseller and Dealer prices, your own cost (optional), stock count and low-stock alerts.
- **Stock in/out:** record deliveries, and remove spoiled, expired, damaged or free packs with a reason.
- **Sales:** today, yesterday, last 7 days, this month or any dates, with totals, packs sold, best-selling items and profit (when your cost is filled in). Export to CSV (opens in Excel).
- **Calendar:** a month view with each day's sales. Tap a day to see its orders and the items sold.
- **Stock log:** every stock movement with date and time.
- **Backup:** download all your data from the Products page. Home reminds you when your last backup is over a week old.

## Files

```
app.py              Flask app (pages, login, sales, reports)
store.py            Database code (Firebase Firestore)
pricing.py          Order math (price level, totals, stock check)
products.json       Your 61 products and prices (the official Cebu price list)
templates/          HTML pages
static/             CSS and JavaScript
make_password.py    Makes your admin password hash (ADMIN_PASSWORD_HASH)
requirements.txt    Python packages
render.yaml         Old Render settings (not used on Railway)
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
   Open http://localhost:5000 and log in with username `nanangsadmin` and the password you typed into `make_password.py`.
6. Go to **Products** and click **Load Price List**, then enter your current stock in **Stock in**.

Your data is saved in Firebase, so it will still be there after you put the app online.

## Part 3: Put it online with Railway

Railway deploys your code from GitHub every time you push to `main`.

1. Keep your GitHub repository **private**. Never upload `.env` or `serviceAccountKey.json` (`.gitignore` already keeps them out).
2. At https://railway.app, create a project with **Deploy from GitHub repo** and pick this repository.
3. In **your service > Variables**, add:
   - **SECRET_KEY:** any long random text.
   - **ADMIN_PASSWORD_HASH:** the long value from `python make_password.py` (without the quotes).
   - **FIREBASE_CREDENTIALS:** open `serviceAccountKey.json` in Notepad, copy **all** of it, and paste it.
4. If Railway asks for a start command, use `gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 60`.
5. In **Settings > Networking**, click **Generate Domain** to get your link, then open it and log in.

Your data lives in Firebase, not on Railway, so redeploying never loses it.

---

## Everyday use

| To do this | Go to |
|---|---|
| Sell to a buyer | **New order** → tap products → **Complete sale** |
| Record a delivery | **Stock in/out** → **Stock in** |
| Remove spoiled or expired packs | **Stock in/out** → **Stock out** |
| Send a receipt to a buyer | Open the order → **Share** (phone) or **Download JPEG** |
| Turn a quote into a sale | **Draft quote** → **Turn into order** |
| Reopen a saved quote | **Draft quote** → **History** → **Open** |
| Use a new price list | Update `products.json`, then **Products** → **Apply Price List** |
| See who still owes you | **To collect** → **Paid** when they pay |
| Fix a wrong stock count | **Products** → **Edit** → change stock and give a reason |
| Cancel a sale | **Sales** → **View** → **Void order** |
| See daily or monthly sales | **Sales**, or **Calendar** and tap a day |
| Get a spreadsheet | **Sales** → **Export sales (CSV)**, or **Products** → **Export stock (CSV)** |
| Back up everything | **Products** → **Download backup** |

**Tip:** On your phone, open the site and use **Add to Home screen** so it opens like an app.

## Changing settings

On Railway: **your service > Variables**, then deploy the change (Railway restarts the app). On your computer: edit `.env`.

| Setting | What it does | Default |
|---|---|---|
| `ADMIN_PASSWORD_HASH` | Login password (run `make_password.py` to change it). **Required:** nobody can sign in without it. | |
| `RESELLER_MIN` | Order amount for Reseller price | `2000` |
| `DEALER_MIN` | Order amount for Dealer price | `5000` |
| `LOW_STOCK` | Default low-stock alert level | `5` |
| `SHOP_CONTACT` | Shown on receipts | `0961 565 5590` |

The login username is always `nanangsadmin`. To **change your password**, run `python make_password.py` and replace `ADMIN_PASSWORD_HASH` in Railway Variables. The password itself is never stored in the code or on Railway, only its hash.

## Backups

The free Firebase plan has no automatic backups (Firestore's scheduled exports need the paid Blaze plan). Once a week, go to **Products > Download backup** and keep the file somewhere safe (Google Drive, email to yourself). The Home page reminds you when it has been 7 days or more.

## Free plan limits

Firebase's free plan allows **50,000 reads and 20,000 writes per day**. Opening the Home page reads about 50 records (one per product) plus today's orders, so a small shop uses only a small part of this. If a limit is ever reached, the app shows a message and works again the next day. **You are never charged** on the free plan.

## Security

- Only one account exists: the username and password hash in your settings. There's no sign-up page.
- After 5 wrong passwords, logins from that device are blocked for 15 minutes.
- Every form is protected against fake requests (CSRF).
- The Firebase database is closed to the public; only your app's private key can reach it.

## Troubleshooting

| Problem | Fix |
|---|---|
| "Firebase key not found" | On Railway, check `FIREBASE_CREDENTIALS` has the whole JSON text. On your computer, check `serviceAccountKey.json` is next to `app.py`. |
| "Wrong username or password" | Run `make_password.py` again and update `ADMIN_PASSWORD_HASH`. |
| Logged out after every restart | Set `SECRET_KEY` to a fixed value. |
