# Local end-to-end test: orders review flow

Runs the whole orders flow on your machine: Streamlit UI, Django API, a Celery worker and,
in place of WhatsApp, a fake 360dialog server that saves each message to a folder.

Nothing touches production:

- **Database:** `e2e/.data/db.sqlite3`, not MySQL.
- **Celery broker:** a folder under `e2e/.data/`, not RabbitMQ.
- **Uploaded and processed files:** also under `e2e/.data/`.

Delete `e2e/.data/` at any time to start over.

The one real outside call is the LLM, when you upload a chat. It uses `LLM_PROVIDER` and its
API key from `.env`.

## Commands

```bash
e2e/run.sh reset --with-orders   # fresh DB: login, 4 products, and a chat file with 5 orders ready to review
e2e/run.sh reset                 # same, without the ready-made orders (upload the sample chat yourself)
e2e/run.sh up                    # start everything
e2e/run.sh status                # running? last log lines (full logs: e2e/.data/logs/)
e2e/run.sh outbox                # messages the fake WhatsApp received (JSON in e2e/.data/whatsapp_outbox/)
e2e/run.sh down                  # stop everything
```

- **Orders UI:** http://localhost:8502. Log in as `e2e` / `e2e-pass-123`.
- **Django admin:** http://127.0.0.1:8001/admin/. To use it, create an admin login with:
  `DJANGO_SETTINGS_MODULE=whatsapp_campaign.settings_e2e venv/bin/python manage.py createsuperuser`

The seeded products are:

| Product        | Price        |
|----------------|--------------|
| Kesar Mango    | ₹120 / kg    |
| Alphonso Mango | ₹900 / dozen |
| Lychee         | ₹250 / box   |
| Tender Coconut | ₹45 / piece  |

## Checklist

### A. Review the seeded orders (no LLM)

Start with `e2e/run.sh reset --with-orders && e2e/run.sh up`. Then open **🧾 Review Orders**.

1. **Open the seeded file.** It shows 5 orders, and the 2 flagged ones are listed first:
   - **Ramesh** has no phone number, and a "Dragon Fruit" line priced at ₹0. Approving it is
     refused.
   - **919000000005** is flagged `had_cancellation`. Their mango was cancelled, so only 2 boxes
     of Lychee remain (₹500).
2. **Check the clean orders.**
   - 919000000001: 3 kg Kesar Mango, ₹360.
   - 919000000002: 1 dozen Alphonso + 2 Lychee, ₹1,400.
   - Priya Sharma: 500 g Kesar + 1 Lychee, ₹310. Her number, 919000000003, was taken from her
     message.
3. **Fix Ramesh's order.**
   - Add a phone number.
   - Either remove the Dragon Fruit line, or add a Dragon Fruit product on the
     **Products & prices** tab and pick it on that line.
   - Save. The blocking issues should clear and the total update.
4. **Change a price** on **Products & prices**, then edit and save an order. Its line is
   re-priced. Orders you have not saved keep their old price.
5. **Reject an order.** It drops out of the summary total.
6. **Approve, then send.**
   - Click **Approve all clean**, then **Send approved**.
   - Within a few seconds, each sent order shows `sent`.
   - `e2e/run.sh outbox` lists one JSON per order.
   - In each file, the item amounts add up to `total_amount`, and `reference_id` is the order ID.
7. **Try to change a sent order.** Editing it is refused.

### B. Real extraction from a chat file (calls the LLM)

1. Open **Extract Orders** and upload `e2e/sample_chat.txt`.
2. Processing takes about 30–60 seconds. When it finishes, the page tells you to open Review
   Orders.
3. Expected result: 7 orders.
   - Ramesh is flagged: no phone, and dragon fruit is not in the catalogue.
   - 919000000005 shows the cancellation: 2 Lychee only.
   - "Same as last week" from 919000000006 is not an order.
4. Upload your own exported chat the same way. If the sellers aren't "Aj", set
   `CHAT_SELLER_NAMES` in settings first.

### C. One real WhatsApp message, to your own phone

The fake server only shows what would be sent. To see the real template on a phone:

```bash
e2e/run.sh down
E2E_REAL_WHATSAPP=1 E2E_SEND_TO=91XXXXXXXXXX e2e/run.sh up
```

1. In Review Orders, set one order's number to your own, approve only that order, and send it.
2. Any other number is refused. The order is marked `failed` with the message
   "not in ORDERS_SEND_ALLOWLIST".
3. **This sends a real message** using the 360dialog key in `.env`.
4. Payment-success messages need the payment webhook, which needs a public URL. They are not
   covered here.

### D. Failure cases

- **Worker killed mid-send.** Stop Celery (`kill $(cat e2e/.data/pids/celery.pid)`) right after
  clicking Send. Some orders stay in `sending`. After 15 minutes, the `fail_stuck_sending_orders`
  task marks them `failed`. It runs from Celery beat, which `run.sh` does not start, so run it by
  hand:
  `DJANGO_SETTINGS_MODULE=whatsapp_campaign.settings_e2e venv/bin/python manage.py shell -c "from orders.tasks import fail_stuck_sending_orders as f; print(f())"`
- **Fake WhatsApp down.** Run `kill $(cat e2e/.data/pids/fake_whatsapp.pid)` and send. Orders
  become `failed` with the connection error.
