# AI Layer Service (Python FastAPI PoC)

This service acts as the AI processing layer for a WhatsApp commerce bot. It processes incoming messages, parses context history, applies system instructions for an African SME merchant persona, and interfaces with the Gemini API using `gemini-3.5-flash`.

## Table of Contents
- [Local Setup](#local-setup)
- [Configuration](#configuration)
- [Running Locally](#running-locally)
- [Deployment](#deployment)
- [API Documentation](#api-documentation)

---

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
- The local server: [http://localhost:8080](http://localhost:8080)
- Interactive API Docs (Swagger UI): [http://localhost:8080/docs](http://localhost:8080/docs)
- Health check: [http://localhost:8080/health](http://localhost:8080/health)

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
> Adjust name, region, and environments variables/secrets configuration according to your cloud setup and security requirements.

---

## API Endpoints

### `GET /health`
* **Description**: Basic health check to verify the service is running.
* **Response**: `{"status": "ok"}`

### `POST /bot`
* **Description**: Triggers chat inference using Gemini with conversation context.
* **Headers**:
  * `X-Internal-Secret`: (Required) Must match `INTERNAL_SECRET` env var.
* **Body** (`ChatRequest`):
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
* **Response** (`ChatResponse`):
  ```json
  {
    "reply": "Yes, we accept various card payments including Visa and Mastercard. We can generate a payment link for you.",
    "action": null
  }
  ```
