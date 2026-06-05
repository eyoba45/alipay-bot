# 🤖 AliPay ETB Bot

> A Telegram bot that lets Ethiopians shop on AliExpress using Ethiopian Birr (ETB)

[![Python](https://img.shields.io/badge/Python-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![Telegram Bot API](https://img.shields.io/badge/Telegram_Bot_API-26A5E4?style=flat-square&logo=telegram&logoColor=white)](https://core.telegram.org/bots/api)
[![Chapa](https://img.shields.io/badge/Chapa_Payment-1DBF73?style=flat-square&logo=stripe&logoColor=white)](https://chapa.co)
[![Railway](https://img.shields.io/badge/Deployed_on-Railway-0B0D0E?style=flat-square&logo=railway&logoColor=white)](https://railway.app)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow?style=flat-square)](LICENSE)

---

## 🌍 The Problem

Millions of Ethiopians want to shop on AliExpress but face a major barrier — international payment. Most Ethiopians don't have international credit cards, and cross-border payments are complicated and inaccessible for the average person.

## ✅ The Solution

AliPay ETB Bot removes that barrier entirely. Users simply message the bot on Telegram, pay in **Ethiopian Birr via Chapa** (Ethiopia's leading payment gateway), and the bot handles the order on their behalf. No international card needed.

---

## ✨ Features

- 💳 **Chapa payment integration** — pay in ETB with full webhook verification
- 📦 **Full order lifecycle** — place order → track status → mark complete
- 👤 **User accounts** — registration, profile management, balance tracking
- 🎁 **Referral system** — users earn rewards for bringing others
- 🛡️ **Admin dashboard** — manage orders, users, and payments via Telegram commands
- ⚡ **Auto-recovery** — bot restarts automatically if it crashes
- 📊 **Uptime monitoring** — continuous health checks keep it running 24/7
- 🗄️ **Database migrations** — schema versioning for safe updates

---

## 🏗️ Architecture

```
User (Telegram)
      │
      ▼
Telegram Bot API
      │
      ▼
┌─────────────────────────────┐
│         bot.py              │  ← Main entry point
│   ┌─────────────────────┐   │
│   │   bot_commands.py   │   │  ← User commands handler
│   │   admin_handlers.py │   │  ← Admin commands handler
│   │   referral_system.py│   │  ← Referral logic
│   └─────────────────────┘   │
│                             │
│   ┌─────────────────────┐   │
│   │  chapa_payment.py   │   │  ← Payment processing
│   │  chapa_webhook.py   │   │  ← Webhook verification
│   └─────────────────────┘   │
│                             │
│   ┌─────────────────────┐   │
│   │    database.py      │   │  ← PostgreSQL via SQLAlchemy
│   └─────────────────────┘   │
└─────────────────────────────┘
      │
      ▼
PostgreSQL (Neon DB)
```

---

## 🚀 Getting Started

### Prerequisites

- Python 3.10+
- PostgreSQL database (or [Neon](https://neon.tech) free tier)
- Telegram Bot Token (from [@BotFather](https://t.me/BotFather))
- Chapa API Key ([chapa.co](https://chapa.co))

### Installation

```bash
# Clone the repository
git clone https://github.com/eyoba45/alipay-bot.git
cd alipay-bot

# Install dependencies
pip install -r requirements.txt

# Set up environment variables
cp .env.example .env
# Edit .env with your credentials
```

### Environment Variables

```env
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
ADMIN_CHAT_ID=your_telegram_chat_id
DATABASE_URL=your_postgresql_connection_string
CHAPA_SECRET_KEY=your_chapa_secret_key
CHAPA_WEBHOOK_SECRET=your_chapa_webhook_secret
```

### Run the Bot

```bash
python forever.py
```

---

## ☁️ Deployment

The bot is configured for deployment on **Railway** or **Replit**.

**Railway (recommended):**
1. Connect your GitHub repo to Railway
2. Add environment variables in Railway dashboard
3. Deploy — Railway auto-detects the `Procfile`

**PythonAnywhere:**
Follow the detailed guide in [PYTHONANYWHERE_SETUP.md](PYTHONANYWHERE_SETUP.md)

---

## 🛠️ Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.10+ |
| Bot Framework | python-telegram-bot |
| Payment Gateway | Chapa API |
| Database | PostgreSQL (Neon) |
| ORM | SQLAlchemy |
| Deployment | Railway / Replit |
| AI Integration | Groq API |

---

## 📁 Project Structure

```
alipay-bot/
├── bot.py                    # Main bot entry point
├── forever.py                # Auto-restart wrapper
├── bot_commands.py           # User-facing commands
├── admin_handlers.py         # Admin commands
├── admin_order_commands.py   # Order management
├── chapa_payment.py          # Payment processing
├── chapa_webhook.py          # Webhook handler
├── chapa_autopay.py          # Automated payment flows
├── database.py               # Database models & connection
├── models.py                 # SQLAlchemy models
├── referral_system.py        # Referral rewards logic
├── error_handler.py          # Global error handling
├── monitor_bot.py            # Health monitoring
├── keep_alive.py             # Uptime ping service
└── requirements.txt          # Python dependencies
```

---

## 🗺️ Roadmap

- [ ] Multi-platform support (beyond AliExpress)
- [ ] In-bot order tracking with real-time updates
- [ ] Mobile-friendly web dashboard for admins
- [ ] Automated order fulfillment pipeline
- [ ] Support for more Ethiopian payment methods (Telebirr, CBE Birr)

---

## 👤 Author

**Eyob Mulugeta**
- TikTok: [@wealth_hustle](https://www.tiktok.com/@wealth_hustle)
- Academy: [elitestartacadamy.com](https://elitestartacadamy.com)
- GitHub: [@eyoba45](https://github.com/eyoba45)

---

## 📄 License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.

---

<div align="center">

*Built in Ethiopia 🇪🇹 — solving real problems for real people*

</div>
