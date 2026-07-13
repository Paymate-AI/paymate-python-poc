# AI Layer Service (Python FastAPI PoC)

This service acts as the AI processing layer for a WhatsApp commerce bot. It receives user messages from the TypeScript webhook service, uses Gemini to interpret intent, and returns a structured reply plus an optional action payload that the TypeScript layer can act on.

## Table of Contents
- [What this service does](#what-this-service-does)
- [Request flow](#request-flow)
- [How the LLM handles intent](#how-the-llm-handles-intent)
- [Payments and idempotency](#payments-and-idempotency)
- [Background payment reconciliation](#background-payment-reconciliation)
- [Local Setup](#local-setup)
- [Configuration](#configuration)
- [Running Locally](#running-locally)
- [Deployment](#deployment)
- [Live deployment](#live-deployment)
- [API Endpoints](#api-endpoints)
- [Security and data handling note](#security-and-data-handling-note)

## What this service does

- Parses incoming chat messages and recent conversation context.
- Uses an LLM to infer the customer intent such as browsing products, placing an order, requesting payment help, or asking for account details.
- Returns a human-friendly reply and an action object for the TypeScript service to handle.
- Coordinates order and payment workflows through the backend services.

## Request flow

1. The TypeScript WhatsApp service receives a message from WhatsApp.
2. It calls the Python service at `POST /bot` with the customer ID and message text.
3. The Python service builds a business-aware prompt, calls the LLM, and returns a response shaped as:
   - `reply`: the message to send back to the customer
   - `action`: an optional structured action for the TS service to process
4. The TypeScript layer sends the reply to WhatsApp and can decide how to handle the returned action.

## How the LLM handles intent

The LLM is used to decide the next best step for the customer conversation. In this PoC it is responsible for understanding intent and producing an action plan such as:

- browse catalog
- place an order
- create a payment virtual account
- ask for human handoff

The LLM does not directly write to the database. We intentionally did not expose database-writing tools to the model, because we did not want to give an AI direct write access to business or payment data. Instead, the model suggests the intended action and the backend services perform the actual writes in a controlled way.

## Payments and idempotency

Payments are designed to be safe for retries and reconciliation:

- Each payment is created with a unique UUID-based reference.
- The reference is stored as a unique value in the payment record.
- Payment verification and reconciliation look up the existing payment by reference and update that record in place instead of creating a duplicate payment.
- This makes repeated verification or reconciliation requests idempotent from the perspective of the payment record, which prevents accidental double-processing of the same logical payment.

<!--
For production, you would typically add a client-supplied idempotency key or a dedicated idempotency table for stricter replay protection.
-->

## Background payment reconciliation

The service starts a background reconciliation worker when the FastAPI app boots. That worker runs every 5 minutes and checks all payments still marked as pending. For each pending payment it verifies the status with the payment gateway and updates the payment record to `successful` or `failed` as appropriate.

This background process helps reconcile delayed or asynchronous payment confirmations without requiring a manual trigger.

## Local Setup

### 1. Prerequisites
- Python 3.11 or higher installed on your system.

### 2. Create and Activate Virtual Environment
From the project root directory:

```bash
# Create a virtual environment named 'venv'
python3 -m venv venv

# Activate virtual environment
# On macOS/Linux:
source venv/bin/activate

# On Windows:
# venv\Scripts\activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

---

## Configuration

1. Copy the sample environment file to create your local `.env`:
   ```bash
   cp .env.example .env
   ```
2. Populate the environment variables in `.env`:
   * `GEMINI_API_KEY`: Your Google Gemini API Key.
   * `INTERNAL_SECRET`: A secure token used to authenticate calls between your webhook service and this AI layer.
     > [!IMPORTANT]
     > The `INTERNAL_SECRET` must match the secret configured in the TypeScript WhatsApp webhook service so that requests from it are authorized.
   * `PORT`: Port to run the application on (defaults to `8080`).

---

## Running Locally

To run the FastAPI service locally with hot reloading enabled:

```bash
uvicorn main:app --reload --port 8080
```

Once running, you can access:
- The local server: http://localhost:8080
- Interactive API Docs (Swagger UI): http://localhost:8080/docs
- Health check: http://localhost:8080/health

---

## Deployment

To deploy this service to Google Cloud Run:

```bash
gcloud run deploy whatsapp-ai-service \
  --source . \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars="INTERNAL_SECRET=your-shared-secret,PORT=8080" \
  --set-secrets="GEMINI_API_KEY=GEMINI_API_KEY:latest"
```

> [!NOTE]
> Adjust the service name, region, and environment variables/secrets according to your cloud setup and security requirements.

## Live deployment

Use the sections below to add the live URLs once they are ready.

- Hosted API: [paymate-ai-payment-service docs](https://python-service-533396938460.africa-south1.run.app/docs)
- WhatsApp bot test link: [WhatsApp bot](https://wa.me/+2347033814063)

---

## API Endpoints

The Python service currently exposes the following endpoints.

### `GET /health`
- **Description**: Basic health check to verify the service is running.
- **Response**: `{"status": "ok"}`

### `POST /bot`
- **Description**: Triggers chat inference using Gemini with conversation context.
- **Headers**:
  - `Authorization`: Bearer token matching `INTERNAL_SECRET` (used by the TS service in this PoC)
- **Body** (`ChatRequest`):
  ```json
  {
    "customerId": "customer-123",
    "message": "Do you accept card payments?",
    "history": [
      {
        "role": "user",
        "content": "Hello"
      },
      {
        "role": "assistant",
        "content": "Hi there! I am a helpful payment assistant. How can I assist you with payments or products today?"
      }
    ]
  }
  ```
- **Response** (`ChatResponse`):
  ```json
  {
    "reply": "Yes, we accept various card payments including Visa and Mastercard. We can generate a payment link for you.",
    "action": null
  }
  ```

### `POST /payments/order/{order_id}`
- **Description**: Creates a payment record for an order and generates a virtual account via the payment gateway.
- **Body**: No request body is required.
- **Response**:
  ```json
  {
    "id": 12,
    "order_id": 7,
    "amount": 4500,
    "reference": "8f2b3f4d-2e6b-4b5e-95a4-abb8df0f2b7c",
    "status": "pending",
    "transaction_id": "txn_123456",
    "virtual_account": {
      "account_number": "1234567890",
      "account_name": "Paymate Ai",
      "bank_name": "ALAT",
      "expiry_date": "2026-07-13T12:00:00Z"
    }
  }
  ```

### `POST /payments/verify/{reference}`
- **Description**: Verifies the status of a payment using the payment reference.
- **Body**: No request body is required.
- **Response**:
  ```json
  {
    "id": 12,
    "order_id": 7,
    "amount": 4500,
    "reference": "8f2b3f4d-2e6b-4b5e-95a4-abb8df0f2b7c",
    "status": "successful",
    "gateway_response": "{...}",
    "transaction_id": "txn_123456"
  }
  ```

### `GET /payments/reference/{reference}`
- **Description**: Retrieves payment information by reference.
- **Response**:
  ```json
  {
    "id": 12,
    "order_id": 7,
    "amount": 4500,
    "reference": "8f2b3f4d-2e6b-4b5e-95a4-abb8df0f2b7c",
    "status": "pending",
    "gateway_response": null,
    "transaction_id": "txn_123456"
  }
  ```

### `GET /payments/pending`
- **Description**: Lists payments that are still pending and awaiting reconciliation.
- **Response**:
  ```json
  [
    {
      "id": 12,
      "order_id": 7,
      "amount": 4500,
      "reference": "8f2b3f4d-2e6b-4b5e-95a4-abb8df0f2b7c",
      "status": "pending",
      "gateway_response": null,
      "transaction_id": "txn_123456"
    }
  ]
  ```

---

## Security and data handling note

This PoC uses SQLite for local development and testing. If you want to test the service with sensitive or production-like data, use a more secure database such as PostgreSQL and ensure secrets are managed through a proper secrets store or environment management strategy. This is especially important for payment and customer data.