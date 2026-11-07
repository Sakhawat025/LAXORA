# Laxora | Legal Consultation Platform

**Author: Sakhawat Hossain · Backend Engineer**  
A five-member team project built with Next.js, FastAPI and PostgreSQL.

Laxora helps a client find a lawyer who handles their type of case, choose an available consultation time and follow up in a private conversation. Lawyers manage their profiles, availability and appointment requests. Administrators review credentials and oversee bookings while the contents of client–lawyer conversations stay restricted to their participants.

## A consultation from start to finish

A client looking for advice on a property matter can filter the directory by practice area, location, court jurisdiction and years of experience. After reviewing a lawyer’s profile, the client selects a 30-minute slot and submits the legal issue. The lawyer sees a pending request and can approve it, reject it or move it to another available slot. The client receives a notification when the booking changes, and both participants can keep appointment-specific questions in the consultation thread.

| Workspace | What the user can do |
| --- | --- |
| Client | Search lawyers, request and track consultations, message a lawyer directly, and submit identity documents for review. |
| Lawyer | Publish availability, respond to bookings, exchange messages and submit professional credentials for verification. |
| Administrator | Review verification applications, manage accounts and practice areas, issue admin invitations and export reports as CSV. |

## Backend engineering decisions

| Problem | How Laxora handles it |
| --- | --- |
| Two clients request the last slot at the same time | A partial unique database index allows only one pending or approved appointment per slot. A cancelled booking releases the slot for another client. |
| A reviewer approves an outdated application | Verification reviews check the application version. Changes to supporting documents invalidate the earlier approval so the updated evidence can be reviewed. |
| An old browser tab sends a message after an account switch | The API checks the workspace’s expected identity against a signed, role-specific HttpOnly session cookie. A mismatch stops the write before a message is inserted. |
| An administrator needs to manage accounts while preserving message privacy | The API checks participant identity before returning conversation content. The administrative account view omits message previews. |

The browser calls a same-origin API through Next.js. FastAPI validates requests and applies role and ownership checks. SQLAlchemy stores the records in PostgreSQL, and Alembic manages schema changes. Uploaded documents use a private volume by default, with an optional Supabase Storage backend.

## Run locally

Install Python 3 and Docker with Docker Compose. From the repository root, run the following commands. The setup script generates local database and session secrets, and the API applies migrations at startup.

```sh
python scripts/setup.py
docker compose up --build -d
docker compose ps
```

Once the services are ready, open the [web app](http://localhost:3000), [lawyer directory](http://localhost:3000/lawyers) or [interactive API documentation](http://localhost:8000/docs).

### Try one booking with demo accounts

On a fresh local installation, replace the example password below with a local demo password of at least 10 characters. The seed command creates six fictional lawyers with upcoming slots. Their verification badges are demonstration data.

```sh
docker compose exec -e DEMO_PASSWORD="your-local-demo-password" api python -m app.manage seed-demo
```

1. Sign in as `client@laxora.example`. Find **Ayesha Rahman** in Dhaka and request one of her available consultation times.
2. Open the lawyer workspace and sign in as `lawyer1@laxora.example` with the same demo password. Approve the request and send a message in the appointment thread.
3. Return to the client workspace. Check the updated booking status, read the message and reply.

## Explore the implementation

| Start here | What to inspect |
| --- | --- |
| [Booking API](backend/app/main.py) and [data model](backend/app/models.py) | Follow a slot from creation through booking, rescheduling and completion. |
| [Verification workflow](backend/app/verification.py) | Trace document submission, ownership checks and versioned review. |
| [Messaging and onboarding](backend/app/features.py) | Inspect conversation access, read receipts and single-use admin invitations. |
| [Frontend workspace](frontend/components/Workspace.tsx) and [API client](frontend/lib/api.ts) | See how the role-specific interface carries the active user context into API requests. |
| [Integration tests](backend/tests/test_platform.py) and [CI workflow](.github/workflows/ci.yml) | Review tests for conflicting bookings, stale sessions, document access and messaging privacy. GitHub Actions is configured to run backend checks against PostgreSQL and build the Next.js frontend. |
| [Team](frontend/lib/team.ts) | View all five contributors and their frontend and backend roles. |
