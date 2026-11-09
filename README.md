# Shop Payments

The payment part of an online shop. It has an HTTP endpoint that starts the payment for a cart and charges the user's saved card through a mock payment provider.

Built with Python 3.13, Flask, SQLAlchemy 2 and PostgreSQL 17.

## Requirements

- [Docker](https://docs.docker.com/get-docker/) with Docker Compose
- [uv](https://docs.astral.sh/uv/getting-started/installation/), needed only to run the tests and linters locally
- `make`

## Quick start

```bash
make up
```

This starts PostgreSQL and the API at `http://localhost:8000`. The database is created from the files in `migrations/`, which include the sample data from the base schema.

Pay for Alice's sample cart:

```bash
curl -i -X POST http://localhost:8000/carts/c1c1c1c1-c1c1-c1c1-c1c1-c1c1c1c1c1c1/payments \
  -H 'X-User-Id: 11111111-1111-1111-1111-111111111111'
```

Stop everything and delete the database volume:

```bash
make down
```

## Commands

| Command        | What it does                                               |
|----------------|------------------------------------------------------------|
| `make install` | Install the dependencies into `.venv` with uv              |
| `make up`      | Build and start the API and PostgreSQL in Docker           |
| `make down`    | Stop the containers and delete the database volume        |
| `make db`      | Start only PostgreSQL                                      |
| `make run`     | Start PostgreSQL and run the API locally in debug mode     |
| `make test`    | Start PostgreSQL and run the tests                         |
| `make lint`    | Run `ruff check`, `ruff format --check` and `mypy --strict` |
| `make format`  | Auto-fix lint issues and format the code                   |
| `make check`   | Run the linters and the tests                              |

Before the first local run: `make install`.

## API

### Swagger UI

Open [http://localhost:8000/docs](http://localhost:8000/docs) after `make up` or `make run`. To call the endpoint, open it, click **Try it out** and **Execute**. The `X-User-Id` and `cart_id` fields are prefilled with Alice's sample user and cart.

The OpenAPI spec is in `app/static/openapi.yaml` and is served at `/static/openapi.yaml`. The tests check that the spec is valid OpenAPI and that it documents every API route.

### `POST /carts/{cart_id}/payments`

Starts the payment for a cart and charges the card.

**Headers**

| Header      | Required | Description                     |
|-------------|----------|---------------------------------|
| `X-User-Id` | yes      | The id of the user who is paying |

**Body** (optional, JSON)

| Field               | Required | Description                                                 |
|---------------------|----------|-------------------------------------------------------------|
| `payment_method_id` | no       | A saved payment method of the user. If missing, the user's default method is used. |

**Response**

```json
{
  "id": "a751016a-0612-4991-8cd6-a3abf044bba9",
  "cart_id": "c1c1c1c1-c1c1-c1c1-c1c1-c1c1c1c1c1c1",
  "payment_method_id": "11111111-2222-3333-4444-555555555555",
  "amount": "70.00",
  "currency": "USD",
  "status": "succeeded",
  "failure_reason": null,
  "created_at": "2026-11-09T10:26:48.256924+00:00"
}
```

`amount` is a string, so no precision is lost to floats.

**Status codes**

| Code | Body                                  | When                                                      |
|------|---------------------------------------|-----------------------------------------------------------|
| 201  | payment with `status: succeeded`      | The card was charged. The cart is now `checked_out`.      |
| 402  | payment with `status: failed`         | The provider declined the card. The cart stays `active`, so the user can try again. |
| 400  | `{"error": "invalid_request"}`        | The body is not a JSON object, or `payment_method_id` is not a UUID |
| 401  | `{"error": "unauthorized"}`           | `X-User-Id` is missing or is not a UUID                   |
| 404  | `{"error": "cart_not_found"}`         | The cart does not exist or belongs to another user        |
| 409  | `{"error": "cart_not_active"}`        | The cart is `checked_out` or `abandoned`                  |
| 409  | `{"error": "payment_already_started"}` | The cart already has a pending or successful payment      |
| 422  | `{"error": "cart_is_empty"}`          | The cart has no items                                     |
| 422  | `{"error": "payment_method_not_found"}` | The user has no default method, or the given method is not theirs |

## How it works

1. **Reserve.** In one transaction, lock the cart row (`SELECT ... FOR UPDATE`) and run the checks. If they pass, insert a `pending` payment with the cart total. If two requests for the same cart arrive at the same time, the second one waits for the lock and then gets `409 payment_already_started`.
2. **Charge.** Call the payment provider *outside* the transaction, so the database does not hold a lock during a network call.
3. **Record.** In a second transaction, store the result. On success, set the payment to `succeeded` and the cart to `checked_out`. On failure, set the payment to `failed` and keep the cart `active`.

## Database schema

- `migrations/001_base_schema.sql` is the base schema from the task, unchanged.
- `migrations/002_payments.sql` adds the `payments` table.

| Column                | Type          | Notes                                              |
|-----------------------|---------------|----------------------------------------------------|
| `id`                  | UUID          | Primary key                                        |
| `cart_id`             | UUID          | References `carts`                                 |
| `user_id`             | UUID          | References `users`. Lets you list a user's payments without a join. |
| `payment_method_id`   | UUID          | References `user_payment_methods`. Records which card was charged. |
| `amount`              | NUMERIC(12,2) | The amount charged, fixed when the payment starts. Must be `> 0`. |
| `currency`            | CHAR(3)       | ISO 4217 code                                      |
| `status`              | TEXT          | `pending`, `succeeded` or `failed`                 |
| `provider_payment_id` | TEXT          | The provider's id for the charge                   |
| `failure_reason`      | TEXT          | Why the provider declined the charge               |
| `created_at`, `updated_at` | TIMESTAMPTZ |                                                  |

A partial unique index, `uq_payments_cart_open ON payments(cart_id) WHERE status IN ('pending', 'succeeded')`, makes sure the database never has two open or successful payments for one cart. Because it skips failed payments, a cart can have any number of failed attempts before one succeeds.

## Mock payment provider

`app/provider.py` holds the mock. It declines any card whose token starts with `tok_declined` (`failure_reason: card_declined`) and accepts every other card. To try a decline locally:

```bash
docker compose exec db psql -U shop -d shop -c \
  "UPDATE user_payment_methods SET provider_token = 'tok_declined_visa'"
```

## Tests

```bash
make test
```

The tests run against a real PostgreSQL database, `shop_test`, which is created in the same container. Each run rebuilds the schema from `migrations/`, and each test starts with empty tables. Override the connection with `TEST_DATABASE_URL`.

The tests cover the success path, declined cards and retries, double payments, carts that are not active or are empty, ownership checks for carts and payment methods, request validation, the unique index, and the mock provider.

## Project layout

```
app/
  __init__.py   create_app factory
  routes.py     the HTTP endpoint, request parsing and error responses
  docs.py       the Swagger UI page at /docs
  static/       openapi.yaml, the API spec
  templates/    the Swagger UI page
  payments.py   the payment flow: reserve, charge, record
  totals.py     stand-in for the existing total calculation service
  provider.py   the mock payment provider
  models.py     SQLAlchemy models
  errors.py     API errors with their HTTP status and error code
migrations/     SQL schema files, applied in order
tests/          pytest tests
```

## Assumptions

- **Authentication is out of scope.** An upstream gateway is assumed to authenticate the user and pass their id in the `X-User-Id` header.
- **The cart total comes from the existing total calculation service.** `app/totals.py` stands in for it: it adds up `unit_price × quantity` over the cart items and takes the currency from the products. All products in a cart are assumed to use one currency.
- **The payment method** is the one in the request body, or else the user's default. If a user has more than one default (the base schema allows it), the newest one is used.
- **One cart, one successful payment.** Failed payments can be retried. Pending or successful payments block new ones.
- **The provider charges synchronously** and returns the result right away. There are no 3-D Secure redirects or webhooks.
- **Stuck pending payments.** If the process crashes between the charge and the record step, the payment stays `pending` and blocks the cart. A real system would fix this with a reconciliation job that asks the provider for the charge status. That job is out of scope here.
- **Stock is not reserved or reduced.** Fulfilment and inventory are separate parts of the system.
- **Migrations are plain SQL files**, applied by the PostgreSQL Docker entrypoint, because the base schema is given as SQL. No migration tool is used, to keep things simple.
