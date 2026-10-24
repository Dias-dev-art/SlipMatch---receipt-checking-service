# Database (PostgreSQL)

Managed with SQLModel models + Alembic migrations. All ids are UUID. All timestamps are `timestamptz` in UTC. Money is `numeric(10,2)` in MYR, never float.

Every tenant table has `business_id` and an index on it. Queries on tenant data always filter by it.

Customers write through one shared Telegram bot (migration `0007` renamed the last WhatsApp-era
columns and dropped the contact exclusion list).

## Tables

### owners

| Column          | Type        | Notes        |
| --------------- | ----------- | ------------ |
| id              | uuid PK     |              |
| email           | text unique |              |
| hashed_password | text        |              |
| full_name       | text        |              |
| is_active       | bool        | default true |
| created_at      | timestamptz |              |

### businesses

| Column                  | Type             | Notes                                   |
| ----------------------- | ---------------- | --------------------------------------- |
| id                      | uuid PK          |                                         |
| owner_id                | uuid FK → owners | one owner, one business for MVP         |
| name                    | text             | "Kak Ani Kitchen"                       |
| shop_code               | text unique      | `kak-ani-kitchen`; Telegram link `t.me/<bot>?start=<shop_code>` |
| delivery_enabled        | bool             |                                         |
| delivery_fee            | numeric(10,2)    |                                         |
| pickup_enabled          | bool             |                                         |
| payment_qr_url          | text             | uploaded DuitNow QR, stored as `/media/...` path |
| payment_instructions    | text             | bank name / account shown to customer   |
| unique_amount_cents     | bool             | add 0.01–0.99 to make each total unique |
| payment_timeout_minutes | int              | default 10                              |
| greeting                | text nullable    | custom first message                    |
| created_at              | timestamptz      |                                         |

### telegram_chats

Which shop a chat with the shared bot orders from. Set by `/start <shop_code>`; opening another
shop's link switches it. A chat without a row uses `TELEGRAM_DEFAULT_SHOP`.

| Column      | Type        | Notes                    |
| ----------- | ----------- | ------------------------ |
| chat_id     | text PK     | Telegram chat id         |
| business_id | uuid FK     | indexed                  |
| updated_at  | timestamptz | last `/start`            |

### menu_items

| Column       | Type          | Notes                                                              |
| ------------ | ------------- | ------------------------------------------------------------------ |
| id           | uuid PK       |                                                                    |
| business_id  | uuid FK       |                                                                    |
| slug         | text          | stable id shown to the LLM, e.g. `mee_goreng`; unique per business |
| name         | text          |                                                                    |
| price        | numeric(10,2) |                                                                    |
| description  | text          | ingredients, what's in it; the AI answers questions only from this |
| tags         | text[]        | `spicy`, `halal`, `contains egg`, `vegetarian`...                  |
| category     | text nullable |                                                                    |
| is_available | bool          | "sold out" toggle                                                  |
| sort_order   | int           |                                                                    |
| deleted_at   | timestamptz nullable | soft delete when old orders still reference the item        |

### customers

| Column       | Type          | Notes                                           |
| ------------ | ------------- | ----------------------------------------------- |
| id           | uuid PK       |                                                 |
| business_id  | uuid FK       | same chat can be a customer of many businesses  |
| tg_chat_id   | text          | Telegram chat id; unique per business           |
| tg_username  | text nullable | Telegram @username without @                    |
| phone        | text nullable | shared with the "Share phone number" button at checkout; digits with country code |
| display_name | text nullable | Telegram first + last name                      |
| created_at   | timestamptz   |                                                 |

### conversations

| Column                   | Type                 | Notes                              |
| ------------------------ | -------------------- | ---------------------------------- |
| id                       | uuid PK              |                                    |
| business_id              | uuid FK              |                                    |
| customer_id              | uuid FK              |                                    |
| needs_owner              | bool                 | handoff flag; AI silent while true |
| handoff_reason           | text nullable        |                                    |
| handoff_at               | timestamptz nullable | when flagged; AI resumes 24h later |
| ai_paused_until          | timestamptz nullable | AI silent until then               |
| last_customer_message_at | timestamptz          | sorts the handoff list             |
| created_at               | timestamptz          |                                    |

### messages

| Column          | Type                                               | Notes                                        |
| --------------- | -------------------------------------------------- | -------------------------------------------- |
| id              | uuid PK                                            |                                              |
| business_id     | uuid FK                                            |                                              |
| conversation_id | uuid FK                                            |                                              |
| direction       | enum `in`, `out`                                   |                                              |
| sender          | enum `customer`, `ai`, `owner`, `system`           |                                              |
| tg_message_id   | text nullable                                      | Telegram `message_id` of incoming messages   |
| type            | enum `text`, `image`, `location`, `audio`, `other` |                                              |
| body            | text nullable                                      |                                              |
| payload         | jsonb nullable                                     | location, media id, tool calls for debugging |
| created_at      | timestamptz                                        |                                              |

### orders

| Column                      | Type                      | Notes                                                                    |
| --------------------------- | ------------------------- | ------------------------------------------------------------------------ |
| id                          | uuid PK                   |                                                                          |
| business_id                 | uuid FK                   |                                                                          |
| conversation_id             | uuid FK                   |                                                                          |
| customer_id                 | uuid FK                   |                                                                          |
| code                        | text                      | short human code `A123`, unique per business; payment reference          |
| status                      | enum                      | `chatting`, `awaiting_payment`, `payment_check`, `approved`, `cancelled` |
| order_type                  | enum nullable             | `pickup`, `delivery`                                                     |
| address_text                | text nullable             |                                                                          |
| location_lat / location_lng | numeric nullable          |                                                                          |
| subtotal                    | numeric(10,2)             | computed by Python                                                       |
| delivery_fee                | numeric(10,2)             | copied from business at the time                                         |
| total                       | numeric(10,2)             | frozen at `awaiting_payment`                                             |
| payment_proof_media_url     | text nullable             | screenshot, hint only                                                    |
| expires_at                  | timestamptz nullable      | timer for current status                                                 |
| approved_by                 | uuid FK → owners nullable |                                                                          |
| approved_at                 | timestamptz nullable      |                                                                          |
| cancelled_reason            | text nullable             | `payment_timeout`, `owner_timeout`, `owner_rejected`, `customer`         |
| created_at / updated_at     | timestamptz               |                                                                          |

Index: `(status, expires_at)` for the timer job; `(business_id, status, created_at desc)` for the dashboard.

### order_items

| Column              | Type          | Notes                 |
| ------------------- | ------------- | --------------------- |
| id                  | uuid PK       |                       |
| order_id            | uuid FK       |                       |
| menu_item_id        | uuid FK       |                       |
| name_snapshot       | text          | menu may change later |
| unit_price_snapshot | numeric(10,2) |                       |
| qty                 | int           | > 0                   |
| note                | text nullable | "less spicy"          |

### processed_webhooks

| Column        | Type        | Notes                |
| ------------- | ----------- | -------------------- |
| update_key    | text PK     | `tg:<update_id>`, dedupes Telegram retries |
| received_at   | timestamptz | cleanup after 7 days |

### media_files

Payment QRs and customer screenshots, kept in Postgres because hosting disks are wiped on deploy.

| Column       | Type         | Notes                                      |
| ------------ | ------------ | ------------------------------------------ |
| id           | uuid PK      |                                            |
| business_id  | uuid FK      | indexed                                    |
| path         | text unique  | public link path `/media/<business>/<file>` |
| content_type | text         | `image/png`, `image/jpeg`, `image/webp`    |
| data         | bytea        | ≤ 2 MB for QRs                             |
| created_at   | timestamptz  |                                            |

## Relations

```
owners 1─1 businesses 1─* telegram_chats
businesses 1─* menu_items
businesses 1─* customers 1─* conversations 1─* messages
conversations 1─* orders 1─* order_items *─1 menu_items
businesses 1─* media_files
```

A conversation has at most one order in `chatting`, `awaiting_payment` or `payment_check` at a time (enforce with a partial unique index).

## Seed data

`backend/app/seed.py` creates a demo owner (`demo@demo.my` / `demo1234`), business "Kak Ani Kitchen" (shop code `kak-ani-kitchen`), and menu: Nasi Lemak RM8, Mee Goreng RM7 (chicken, egg, vegetables, sweet-spicy sauce), Roti Canai RM2, Teh Tarik RM3. Delivery fee RM3.
