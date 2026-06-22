# 🏋️ Biometric Gym Access And Management System

An automated gym entry control system using **ZKTeco biometric devices** for member verification with integrated fee/payment status checking. Built with **FastAPI** for the backend, **Supabase** for database and storage, and **Jinja2** for frontend templates.

---

## 📋 Project Overview

When a member arrives at the gym, the system captures their **fingerprint or face**, identifies them against the database, checks their **fee/payment status**, and either grants or denies access accordingly.

### Access Logic
```
Member Arrives
      ↓
Biometric Scan (Fingerprint / Face)
      ↓
Identity Verified?
  ├── No  → Show "No access"
  └── Yes
        ↓
    Check Fee Status
        ↓
    Fee Paid?
    ├── No  → Show "Your fee is pending"
    └── Yes → Open Door / Grant Access
```

---

## 🛠️ Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Jinja2 Templates + HTMX/Tailwind CSS/JavaScript |
| Backend | FastAPI (Python) |
| Database | Supabase (PostgreSQL) |
| Storage | Supabase Storage |
| Hardware | ZKTeco Biometric Device |

---

## 📁 Project Structure

```
gym-access-system/
│
├── main.py                          # App factory & lifespan events
├── config.py                        # Settings via pydantic-settings
├── .env                             # Secret keys (never commit)
├── .env.example                     # Template for team members
├── .gitignore
├── requirements.txt
├── README.md
│
├── routers/                         # One file per feature module
│   ├── __init__.py
│   ├── auth.py                      # Login, logout, OTP, password reset
│   ├── dashboard.py                 # Dashboard page
│   ├── members.py                   # Member CRUD
│   ├── plans.py                     # Membership plans
│   ├── payments.py                  # Fee collection & history
│   ├── access_logs.py               # Attendance / entry logs
│   ├── biometric.py                 # Biometric enrollment & device mgmt
│   ├── reports.py                   # Reports & exports
│   ├── users.py                     # Staff account management
│   ├── settings.py                  # Gym settings (name, logo, etc.)
│   └── webhooks.py                  # ZKTeco ADMS push endpoint
│
├── services/                        # Pure business logic — NO raw DB calls
│   ├── __init__.py
│   ├── supabase_client.py           # Supabase client singleton
│   ├── auth_service.py              # JWT, password hashing, OTP
│   ├── member_service.py            # Enrollment, status, CNIC check
│   ├── payment_service.py           # Fee collection, receipts, dues
│   ├── access_service.py            # Gate grant/deny logic
│   ├── biometric_service.py         # Enrollment orchestration
│   ├── zkteco_service.py            # pyzk TCP/IP wrapper
│   ├── biometric_mock.py            # Mock device (dev/testing only)
│   └── notification_service.py      # SMS / WhatsApp / Email dispatch
│
├── schemas/                         # Pydantic request & response models
│   ├── __init__.py
│   ├── auth.py
│   ├── member.py
│   ├── plan.py
│   ├── payment.py
│   ├── access_log.py
│   └── biometric.py
│
├── utils/                           # Stateless helper functions
│   ├── __init__.py
│   ├── dependencies.py              # FastAPI Depends() factories (auth, RBAC)
│   ├── rbac.py                      # require_permission() dependency
│   ├── id_generator.py              # M0001, RCP-0001, INV-202601
│   └── formatters.py                # PKR currency, PK date, phone mask
│
├── templates/                       # Jinja2 HTML templates
│   ├── base.html                    # Layout: sidebar, topbar, flash msgs
│   ├── partials/                    # _modal.html, _table.html, _pagination.html
│   ├── auth/
│   │   ├── login.html
│   │   ├── forgot_password.html
│   │   └── otp_verify.html
│   ├── dashboard/
│   │   └── index.html
│   ├── members/
│   │   ├── members.html
│   │   ├── detail.html
│   │   └── register.html
│   ├── payments/
│   │   ├── record.html
│   │   └── history.html
│   ├── plans/
│   │   └── plans.html
│   ├── access_logs/
│   │   └── access_logs.html
│   ├── reports/
│   │   └── reports.html
│   ├── users/
│   │   └── users.html
│   └── settings/
│       └── settings.html
│
└── static/
    ├── css/
    │   ├── input.css                # Tailwind source (directives only)
    │   └── output.css               # Compiled — gitignore this
    ├── js/
    │   └── htmx.min.js              # HTMX local copy
    └── images/
        └── logo.png                 # Placeholder
```

---

## 🗄️ Database Schema (Supabase)

All tables are created in Supabase PostgreSQL with **Row Level Security (RLS) enabled**.

| Table | Description |
|-------|-------------|
| `roles` | System roles — Admin, Receptionist |
| `permissions` | Resource-level permission definitions |
| `role_permissions` | Maps roles to permissions |
| `users` | Staff accounts (admin, receptionist) |
| `members` | Gym member profiles |
| `plans` | Membership plans and pricing |
| `memberships` | Active member plan assignments |
| `past_memberships` | Archived/expired membership history |
| `biometric_devices` | ZKTeco device registry |
| `biometric_templates` | Fingerprint and face template records |
| `attendance_logs` | Entry/exit access logs with timestamps |
| `payments` | Fee collection and payment records |
| `member_notes` | Staff notes per member |
| `settings` | System Settings (Name, Logo, Location)

> Full SQL schema is in `supabase-setup-guide.md`

---

## ☁️ Supabase Storage

| Bucket | Access | Purpose |
|--------|--------|---------|
| `member-photos` | Public | Member face/profile images |
| `logo` | Public | Gym logo |
| `user-photos` | Public | User profile |

---

## ⚙️ Environment Variables

Create a `.env` file in the root directory:

```env
SUPABASE_URL=https://your-project-id.supabase.co
SUPABASE_SERVICE_KEY=your-service-role-key
SECRET_KEY=your-jwt-secret-key
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60
```

> ⚠️ Never commit `.env` to version control. Use `.env.example` as a template.

---

## 🚀 Getting Started

### 1. Clone the repository
```bash
git clone https://github.com/your-username/gym-access-system.git
cd gym-access-system
```

### 2. Create virtual environment
```bash
python -m venv venv
source venv/bin/activate        # Linux/Mac
venv\Scripts\activate           # Windows
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

### 4. Set up environment variables
```bash
cp .env.example .env
# Fill in your Supabase URL and keys in .env
```

### 5. Run the development server
```bash
uvicorn main:app --reload
```

### 6. Open in browser
```
http://localhost:8000
```

---

## 📦 Requirements

```
fastapi
uvicorn
supabase
python-dotenv
python-jose[cryptography]
passlib[bcrypt]
jinja2
python-multipart
```

---

## 👥 User Roles

| Role | Access |
|------|--------|
| **Admin** | Full system — members, plans, payments, reports, devices, accounts |
| **Receptionist** | Members, payments, entry handling, renewals, notes |

---

## 🔄 Current Progress

- [x] Project planning & documentation
- [x] ER diagram & flow diagram
- [x] Tech stack decided
- [x] Supabase project created
- [x] Hardware device (ZKTeco) tested
- [ ] All database tables created with RLS enabled
- [ ] Storage bucket created (`member-photos`, `logo`, `user-photo`)
- [ ] Default roles seeded
- [ ] FastAPI project structure setup
- [ ] Supabase connection service
- [ ] Authentication (login/JWT)
- [ ] Member CRUD APIs
- [ ] Plans & payments APIs
- [ ] Access control logic
- [ ] Jinja2 templates from Figma
- [ ] ZKTeco device integration

---

## 📄 License

This project is private and intended for internal gym management use.