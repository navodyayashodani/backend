# CinnaTend — Backend

> AI-Powered Cinnamon Oil Tendering System  
> Django REST Framework · scikit-learn · PostgreSQL  
> IIT / University of Westminster — Final Year Project 2025/2026  
> Student: K.A. Harindi Navodya | W1953281 / 20220541

---

## Overview

CinnaTend's backend is a Django REST Framework API that powers three core features:

- **ML Quality Grading** — a trained Random Forest model automatically grades uploaded cinnamon oil GC-MS reports into Grade A, B, or C with a confidence score
- **Sealed-Bid Tendering** — manufacturers post tenders; buyers submit confidential bids that are only shown for manufacturers
- **Post-Tender Chat** — after a bid is accepted, a private chat channel is unlocked between the manufacturer and the winning buyer

---

## Tech Stack

| | |
|--|--|
| Framework | Django 4.x + Django REST Framework |
| Language | Python 3.x |
| Database | PostgreSQL (via `psycopg2`) |
| ML Model | scikit-learn Random Forest (`cinnamon_model_enhanced.pkl`) |
| Auth | JWT (via `djangorestframework-simplejwt`) |
| Media files | Django media serving (`/media/`) |
| Environment | Python `venv` |

---

## Getting Started

### Prerequisites

- Python 3.10+
- `pip`
- The [CinnaTend frontend](https://github.com/navodyayashodani/cinnaTend_frontend) (separate repo)

### Install & Run

```bash
git clone https://github.com/your-username/cinnatend-backend.git
cd cinnatend-backend

# Create and activate a virtual environment
python -m venv venv
source venv/bin/activate        # macOS/Linux
venv\Scripts\activate           # Windows

# Install dependencies
pip install -r requirements.txt

# Create .env file (see Environment Variables below)
# Make sure PostgreSQL is running, and the database exists:
# psql -U postgres -c "CREATE DATABASE cinnamon_tender_db;"
# psql -U postgres -c "CREATE USER cinnamon_admin WITH PASSWORD 'your-password';"
# psql -U postgres -c "GRANT ALL PRIVILEGES ON DATABASE cinnamon_tender_db TO cinnamon_admin;"

# Run migrations
python manage.py migrate

# Create a superuser (admin account)
python manage.py createsuperuser

# Start development server
python manage.py runserver
```

API runs at `http://localhost:8000`

---

## Environment Variables

Create a `.env` file in the project root (same level as `manage.py`):

```env
SECRET_KEY=your-django-secret-key
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1

DATABASE_NAME=cinnamon_tender_db
DATABASE_USER=cinnamon_admin
DATABASE_PASSWORD=your-db-password
DATABASE_HOST=localhost
DATABASE_PORT=5432
```

---

## Project Structure

```
backend/                          # Root project directory
├── accounts/                     # User auth, profiles, admin management
│   ├── management/               # Custom management commands
│   ├── migrations/
│   ├── __init__.py
│   ├── admin.py
│   ├── admin_urls.py             # URL routes for admin-specific endpoints
│   ├── admin_views.py            # Admin dashboard stats, user management, reports
│   ├── apps.py
│   ├── models.py                 # User profile model (role, avatar, phone, company)
│   ├── serializers.py            # UserSerializer with role as SerializerMethodField
│   ├── tests.py
│   ├── urls.py                   # Auth + profile endpoints
│   └── views.py                  # Register, login, profile views
│
├── backend/                      # Django project config
│   ├── __init__.py
│   ├── asgi.py
│   ├── settings.py
│   ├── urls.py                   # Root URL config — includes all app URLs
│   └── wsgi.py
│
├── chat/                         # Post-tender chat feature
│   ├── migrations/
│   ├── __init__.py
│   ├── admin.py
│   ├── apps.py
│   ├── models.py                 # ChatRoom, Message models
│   ├── serializers.py
│   ├── tests.py
│   ├── urls.py
│   └── views.py                  # Chat room creation, message send/retrieve
│
├── tenders/                      # Tender, bid, and ML grading
│   ├── migrations/
│   ├── ml_model/
│   │   ├── __init__.py
│   │   ├── cinnamon_model_enhanced.pkl   # Trained Random Forest + Platt scaling
│   │   ├── label_encoder.pkl             # Grade label encoder (A=0, B=1, C=2)
│   │   └── predictor.py                  # Loads model, runs prediction, returns grade + confidence
│   ├── __init__.py
│   ├── admin.py
│   ├── apps.py
│   ├── models.py                 # Tender, TenderBid models
│   ├── serializers.py            # TenderSerializer with display_status field
│   ├── tests.py
│   ├── urls.py
│   └── views.py                  # Tender CRUD, bid submit/accept, grading endpoint
│
├── media/                        # Uploaded files (avatars, lab reports)
├── venv/                         # Python virtual environment (not committed)
├── .env
├── .gitignore
├── db.sqlite3                    # Leftover artifact — not used (PostgreSQL is active)
├── manage.py
└── requirements.txt
```

---

## Apps

### `accounts`

Handles user registration, login, JWT token issuance, and profile management.

**Models — `models.py`**

| Model | Key Fields |
|-------|-----------|
| `UserProfile` | `user` (OneToOne → User), `role` (manufacturer/buyer), `phone`, `company_name`, `avatar` |

**Key design — `serializers.py`**

The `role` field is returned as a `SerializerMethodField` that checks `is_superuser` → `is_staff` → profile role in priority order, so Django superusers are always identified as admin regardless of their profile role.

**`admin_views.py`** provides the endpoints consumed by the admin dashboard:

| Endpoint | View | Description |
|----------|------|-------------|
| `GET /api/admin/stats/` | `AdminStatsView` | Total users, active tenders, total tenders, total bids |
| `GET /api/admin/users/` | `AdminUserListView` | All registered users with role info |
| `GET /api/admin/tenders/` | `AdminTenderListView` | All tenders with `display_status` |
| `GET /api/admin/reports/summary/` | `AdminSummaryReportView` | Tender counts by status, grade breakdown |

---

### `tenders`

Core tendering logic — tender creation, bid submission, bid reveal, and ML grading.

**Models — `models.py`**

| Model | Key Fields |
|-------|-----------|
| `Tender` | `tender_title`, `manufacturer` (FK→User), `oil_type`, `quantity`, `quality_grade`, `quality_score`, `end_date`, `status` (draft/active/closed/awarded) |
| `TenderBid` | `tender` (FK→Tender), `buyer` (FK→User), `bid_amount`, `message`, `status` (pending/accepted/rejected) |

**`serializers.py` — `display_status` field**

`display_status` is a computed `SerializerMethodField` — not stored in the database. It returns an array so a tender can carry multiple labels at once:

```python
# A closed tender with no bids returns: ['closed', 'no bids']
# An awarded tender returns: ['closed', 'awarded']
# An open tender returns: ['active']
```

**`ml_model/predictor.py`**

Loads `cinnamon_model_enhanced.pkl` and `label_encoder.pkl` at startup. Accepts five chemical composition values and returns a predicted grade and confidence score:

| Input Feature | Description |
|--------------|-------------|
| `Eugenol_Percentage` | % eugenol content |
| `Eugenyl_Acetate_Percentage` | % eugenyl acetate |
| `Linalool_Percentage` | % linalool |
| `Cinnamaldehyde_Percentage` | % cinnamaldehyde |
| `Safrole_Percentage` | % safrole |

| Output | Description |
|--------|-------------|
| `quality_grade` | Predicted grade: A, B, or C |
| `quality_score` | Model confidence (e.g. 97.3%) |

**The model:**
- Algorithm: Random Forest (200 trees, max_depth=8, class_weight=balanced)
- Calibration: Platt scaling (sigmoid, 5-fold CV)
- Test accuracy: 96.00% | F1: 0.9603 | ROC-AUC: 0.9925
- No A↔C misclassifications — all errors are adjacent-grade only (A↔B or B↔C)

---

### `chat`

Post-tender private messaging between a manufacturer and the winning buyer.

**Models — `models.py`**

| Model | Key Fields |
|-------|-----------|
| `ChatRoom` | `tender` (FK→Tender), `manufacturer` (FK→User), `buyer` (FK→User), `created_at` |
| `Message` | `room` (FK→ChatRoom), `sender` (FK→User), `content`, `timestamp` |

A `ChatRoom` is created automatically when a bid is accepted. Only the two linked users can access it.

---

## API Endpoints

### Auth & Accounts

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/auth/register/` | Register new user (manufacturer or buyer) |
| `POST` | `/api/auth/login/` | Login — returns JWT access token + user object |
| `GET` | `/api/auth/profile/` | Get logged-in user's profile |
| `PATCH` | `/api/auth/profile/` | Update profile (name, phone, company, avatar) |

### Tenders & Grading

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/grade/` | Upload lab report → OCR → ML grade prediction |
| `GET` | `/api/tenders/` | List active tenders (buyers) |
| `POST` | `/api/tenders/` | Create a new tender (manufacturers) |
| `GET` | `/api/tenders/my/` | List manufacturer's own tenders |
| `GET` | `/api/tenders/:id/` | Get tender detail |
| `GET` | `/api/tenders/:id/bids/` | Get all bids for a tender (after deadline only) |
| `POST` | `/api/tenders/:id/bids/` | Submit a sealed bid |
| `PATCH` | `/api/tenders/:id/bids/:bidId/` | Update bid before deadline |
| `POST` | `/api/tenders/:id/bids/:bidId/accept/` | Accept winning bid + create chat room |
| `GET` | `/api/bids/my/` | Buyer's own bid history |

### Chat

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/chats/:chatId/messages/` | Load chat message history |
| `POST` | `/api/chats/:chatId/messages/` | Send a message |

### Admin

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/admin/stats/` | Dashboard stats |
| `GET` | `/api/admin/users/` | All users |
| `GET` | `/api/admin/tenders/` | All tenders |
| `GET` | `/api/admin/reports/summary/` | Tender + grading summary report |

> All endpoints except `/auth/register/` and `/auth/login/` require a JWT Bearer token in the `Authorization` header.

---

## Database

PostgreSQL is used as the database. Connection details are configured via environment variables in `.env`.

To apply migrations to a fresh database:

```bash
python manage.py migrate
python manage.py createsuperuser
```

---

## ML Model Files

The trained model files live in `tenders/ml_model/` and are loaded once at startup by `predictor.py`.

| File | Description |
|------|-------------|
| `cinnamon_model_enhanced.pkl` | Trained Random Forest Classifier + Platt scaling calibration |
| `label_encoder.pkl` | Encodes grade labels (A=0, B=1, C=2) |
| `predictor.py` | Prediction logic — loads both files, accepts feature dict, returns grade + confidence |

> These `.pkl` files were trained in Google Colab on 3,000 synthetic GC-MS samples. Do not delete or replace them without retraining and updating `predictor.py` accordingly.

---

## Running Tests

```bash
python manage.py test accounts
python manage.py test tenders
python manage.py test chat
```

---

*K.A. Harindi Navodya · W1953281 / 20220541*
