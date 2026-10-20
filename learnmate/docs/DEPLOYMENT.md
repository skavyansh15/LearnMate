# Production Deployment Guide

This guide covers deploying LearnMate to a cloud environment using Render (Web Service) and Supabase (Serverless PostgreSQL).

---

## 1. Prerequisites

- A GitHub account with the LearnMate repository.
- A free Render account (https://render.com).
- A free Supabase account (https://supabase.com).
- An NVIDIA NIM API key (or OpenAI-compatible API key).

---

## 2. Database Setup (Supabase)

Render's free tier uses an ephemeral filesystem. Attaching a free Supabase PostgreSQL database ensures that user courses, uploaded notes, quizzes, and progress persist permanently across restarts.

1. Log in to [Supabase](https://supabase.com) and click **New Project**.
   - Project Name: `learnmate`
   - Database Password: Create and securely save a strong password.
   - Region: Choose a region geographically close to your target users.
2. Once provisioned, navigate to **Project Settings** (gear icon) -> **Database**.
3. Under **Connection string**, select the **URI** tab.
4. Copy the connection string. It will look like:
   ```text
   postgresql://postgres.[project-ref]:[YOUR-PASSWORD]@aws-0-[region].pooler.supabase.com:5432/postgres
   ```
5. Replace `[YOUR-PASSWORD]` with the database password set in step 1.

---

## 3. Web Service Deployment (Render)

1. Log in to [Render](https://render.com) and click **New +** -> **Web Service**.
2. Select **Build and deploy from a Git repository** and connect your `LearnMate` repository.
3. Configure service parameters:
   - **Name**: `learnmate` (or your preferred service name)
   - **Region**: Select a region matching or near your Supabase database.
   - **Branch**: `main`
   - **Root Directory**:
     - Leave **blank** if `app.py` is located at the repository root.
     - Set to `learnmate` if your repository has a nested folder structure.
   - **Runtime**: `Python 3`
   - **Build Command**:
     ```bash
     pip install -r requirements.txt
     ```
   - **Start Command**:
     ```bash
     gunicorn "app:create_app()" --bind 0.0.0.0:$PORT --workers 2 --timeout 120
     ```
   - **Instance Type**: Select **Free** ($0/month).

---

## 4. Environment Variables

In the Render service dashboard, open the **Environment** tab and define the following variables:

| Key | Value | Purpose |
| :--- | :--- | :--- |
| `DATABASE_URL` | `postgresql://postgres...` | Supabase connection URI for permanent storage |
| `LLM_API_KEY` | `nvapi-...` | Provider API key for live LLM inference |
| `LLM_BASE_URL` | `https://integrate.api.nvidia.com/v1` | NVIDIA NIM OpenAI-compatible endpoint |
| `LLM_MODEL` | `openai/gpt-oss-20b` | Target inference model |
| `SECRET_KEY` | `64-character random hex string` | Session cookie encryption key |
| `COOKIE_SECURE` | `1` | Enforces HTTPS-only cookies |
| `PYTHONUNBUFFERED` | `1` | Ensures immediate stdout streaming in Render logs |
| `DAILY_AI_CALLS` | `100` | Per-user daily AI call budget |
| `RATE_PER_MIN` | `30` | Per-user request rate limit |

---

## 5. Verification and Health Check

Once the deployment build completes and the service status displays **Live**:

1. **Verify Health Endpoint**:
   Navigate to `https://<your-service-name>.onrender.com/api/health`.
   Expected response:
   ```json
   {"status": "ok"}
   ```
2. **Verify Database Initialization**:
   Check your Render logs. On the initial request, `store.py` connects to Supabase and automatically creates the table `learnmate_kv`.
3. **Verify Interactive Playback**:
   Open the application root `https://<your-service-name>.onrender.com/`. Verify that the bundled sample lecture plays, the video time-gate restricts questions asked early in the lecture, and document downloads operate correctly.

---

## 6. Cold Starts on Free Tier

Render free tier instances sleep after 15 minutes of inactivity. The first request after a period of dormancy takes approximately 30 to 50 seconds while the container spins up. Subsequent requests respond with normal low latency.
