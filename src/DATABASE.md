# Database (PostgreSQL)

Managed with SQLModel models + Alembic migrations. All ids are UUID. All timestamps are `timestamptz` in UTC. Money is `numeric(10,2)` in MYR, never float.

Every tenant table has `business_id` and an index on it. Queries on tenant data always filter by it.

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
| delivery_enabled        | bool             |                                         |
| delivery_fee            | numeric(10,2)    |                                         |
| pickup_enabled          | bool             |                                         |
| payment_qr_url          | text             | uploaded DuitNow QR image               |
| payment_instructions    | text             | bank name / account shown to customer   |
| unique_amount_cents     | bool             | add 0.01–0.99 to make each total unique |
| payment_timeout_minutes | int              | default 10                              |
| greeting                | text nullable    | custom first message                    |
| created_at              | timestamptz      |                                         |

### whatsapp_accounts

| Column                 | Type        | Notes                                        |
| ---------------------- | ----------- | -------------------------------------------- |
| id                     | uuid PK     |                                              |
| business_id            | uuid FK     |                                              |
| phone_number_id        | text unique | from Meta, used to resolve tenant on webhook |
| display_phone          | text        |                                              |
| access_token_encrypted | text        | never returned by API                        |
| coexistence            | bool        | number also used in WhatsApp Business app    |

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

### customers

| Column       | Type          | Notes                                           |
| ------------ | ------------- | ----------------------------------------------- |
| id           | uuid PK       |                                                 |
| business_id  | uuid FK       | same phone can be a customer of many businesses |
| wa_phone     | text          | E.164 without +; unique per business            |
| display_name | text nullable | WhatsApp profile name                           |
| created_at   | timestamptz   |                                                 |

### contact_exclusions

| Column      | Type    | Notes             |
| ----------- | ------- | ----------------- |
| id          | uuid PK |                   |
| business_id | uuid FK |                   |
| wa_phone    | text    |                   |
| label       | text    | "Mum", "Supplier" |

### conversations

| Column                   | Type                 | Notes                              |
| ------------------------ | -------------------- | ---------------------------------- |
| id                       | uuid PK              |                                    |
| business_id              | uuid FK              |                                    |
| customer_id              | uuid FK              |                                    |
| needs_owner              | bool                 | handoff flag; AI silent while true |
| handoff_reason           | text nullable        |                                    |
| ai_paused_until          | timestamptz nullable | owner takeover                     |
| last_customer_message_at | timestamptz          | for the 24h window                 |
| created_at               | timestamptz          |                                    |

### messages

| Column          | Type                                               | Notes                                        |
| --------------- | -------------------------------------------------- | -------------------------------------------- |
| id              | uuid PK                                            |                                              |
| business_id     | uuid FK                                            |                                              |
| conversation_id | uuid FK                                            |                                              |
| direction       | enum `in`, `out`                                   |                                              |
| sender          | enum `customer`, `ai`, `owner`, `system`           |                                              |
| wa_message_id   | text nullable                                      |                                              |
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
| wa_message_id | text PK     | dedupe Meta retries  |
| received_at   | timestamptz | cleanup after 7 days |

## Relations

```
owners 1─1 businesses 1─* whatsapp_accounts
businesses 1─* menu_items
businesses 1─* customers 1─* conversations 1─* messages
conversations 1─* orders 1─* order_items *─1 menu_items
businesses 1─* contact_exclusions
```

A conversation has at most one order in `chatting`, `awaiting_payment` or `payment_check` at a time (enforce with a partial unique index).

## Seed data

`backend/app/seed.py` creates a demo owner (`demo@demo.my` / `demo1234`), business "Kak Ani Kitchen", and menu: Nasi Lemak RM8, Mee Goreng RM7 (chicken, egg, vegetables, sweet-spicy sauce), Roti Canai RM2, Teh Tarik RM3. Delivery fee RM3.
