# PO Extract Application

A Flask web application for extracting and managing Purchase Order (PO) data from PDF files.

## Features

- **Upload PDFs**: Upload multiple PO PDF files for processing
- **Extract Data**: Automatically extracts PO information from PDFs
- **Dashboard**: View and manage all PO items with inline editing
- **Style Master**: Manage EAN to Style Number and Buyer mappings
- **Excel Export**: Download dashboard data as Excel file
- **PostgreSQL Database**: Production-grade database with foreign key relationships

## Prerequisites

- Python 3.8 or higher
- PostgreSQL (for production) or SQLite (for development)
- Virtual environment (recommended)

## Installation

### 1. Clone the repository

```bash
git clone <your-repo-url>
cd POExtract
```

### 2. Create and activate virtual environment

```bash
# Create virtual environment
python3 -m venv venv

# Activate virtual environment
source venv/bin/activate  # On macOS/Linux
# or
venv\Scripts\activate      # On Windows
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

Copy `.env.example` to `.env` and update with your database credentials:

```bash
cp .env.example .env
```

Edit `.env` file:

```env
# Database Configuration
DB_TYPE=postgresql          # or 'sqlite' for local dev
DB_HOST=localhost
DB_PORT=5432
DB_NAME=poextract_db
DB_USER=postgres
DB_PASSWORD=your_password

# Flask Configuration
FLASK_ENV=development        # 'development' or 'production'
FLASK_DEBUG=True             # True for dev, False for production
PORT=5001                    # Port for development server
```

**For local development with SQLite:**
```env
DB_TYPE=sqlite
# Other DB_* variables are ignored when using SQLite
```

## Running the Application

### Development Mode (Recommended for Local Development)

Development mode uses Flask's built-in development server with auto-reload and debug features:

```bash
# Make sure virtual environment is activated
source venv/bin/activate

# Set development environment
export FLASK_ENV=development
export FLASK_DEBUG=True

# Run the application
python app.py
```

Or use the shorthand:
```bash
FLASK_ENV=development FLASK_DEBUG=True python app.py
```

The application will start on **http://127.0.0.1:5001** (or the port specified in `.env`).

**Development Mode Features:**
- ✅ Auto-reload on code changes
- ✅ Debug mode enabled (detailed error pages)
- ✅ Flask development server
- ✅ Runs on port 5001 (configurable via PORT env var)

### Production Mode (For Render.com Deployment)

Production mode uses Waitress server (configured for Render.com):

```bash
# Set production environment
export FLASK_ENV=production

# Run the application
python app.py
```

**Production Mode Features:**
- ✅ Waitress WSGI server (production-ready)
- ✅ Runs on port 10000 (or PORT env var)
- ✅ No debug mode
- ✅ Optimized for production

### Quick Start (Development)

```bash
# 1. Activate virtual environment
source venv/bin/activate

# 2. Run in development mode
FLASK_ENV=development python app.py

# 3. Open browser
# http://localhost:5001
```

## Database Setup

### PostgreSQL (Production)

1. Create a PostgreSQL database:
   ```bash
   createdb poextract_db
   ```

2. Update `.env` with your PostgreSQL credentials

3. Tables are automatically created on first run via `initialize_db()`

### SQLite (Development)

1. Set `DB_TYPE=sqlite` in `.env`

2. Database file `poextract.db` will be created automatically

3. Tables are automatically created on first run

### Migrating from SQLite to PostgreSQL

If you have existing SQLite data to migrate:

```bash
# 1. Ensure PostgreSQL is running and .env is configured
# 2. Run migration script
python migrate_to_postgresql.py
```

## Project Structure

```
POExtract/
├── app.py                 # Main Flask application
├── extractor.py            # PDF text extraction and parsing logic
├── database.py             # Database models and connection management
├── templates/              # HTML templates
│   ├── dashboard.html
│   ├── style_master.html
│   ├── upload.html
│   └── results.html
├── uploads/                # Directory for uploaded PDF files
├── requirements.txt        # Python dependencies
├── .env                    # Environment variables (not in git)
├── .env.example            # Environment variables template
├── render.yaml             # Render.com deployment configuration
├── Procfile                # Process file for deployment
└── runtime.txt             # Python version specification
```

## Database Schema

### `style_master` Table
- `id` (PRIMARY KEY, auto-increment)
- `ean` (UNIQUE, indexed) - European Article Number
- `style_no` - Style number
- `buyer` - Buyer name

### `po_items` Table
- `id` (PRIMARY KEY, auto-increment)
- `ean` (FOREIGN KEY → `style_master.ean`)
- `po_number` - Purchase Order number
- `style` - Style (populated from style_master)
- `buyer` - Buyer (populated from style_master)
- `factory` - Factory name
- `transporter` - Transporter name
- `delivery_date` - Delivery date
- `quantity` - Quantity
- `factory_remarks` - Factory remarks
- `created_at` - Timestamp

## Deployment

### Render.com

1. Push your code to GitHub

2. In Render Dashboard:
   - Create PostgreSQL database
   - Create Web Service
   - Connect GitHub repository
   - Render will use `render.yaml` for configuration

3. The app will automatically:
   - Install dependencies
   - Connect to PostgreSQL
   - Start with Waitress on port 10000

See `render.yaml` for deployment configuration.

## Environment Variables

| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `DB_TYPE` | Database type (`postgresql` or `sqlite`) | `sqlite` | No |
| `DB_HOST` | PostgreSQL host | `localhost` | Yes (if PostgreSQL) |
| `DB_PORT` | PostgreSQL port | `5432` | Yes (if PostgreSQL) |
| `DB_NAME` | Database name | `poextract_db` | Yes (if PostgreSQL) |
| `DB_USER` | Database user | `postgres` | Yes (if PostgreSQL) |
| `DB_PASSWORD` | Database password | - | Yes (if PostgreSQL) |
| `DATABASE_URL` | Full database URL (Render/Heroku style) | - | No (alternative to above) |
| `FLASK_ENV` | Flask environment (`development` or `production`) | `development` | No |
| `FLASK_DEBUG` | Enable debug mode | `True` | No |
| `PORT` | Server port | `5001` (dev) / `10000` (prod) | No |

## Development Tips

### Running Tests

```bash
# Test database connection
python test_psql_connection.py

# Test app connection
python test_app_connection.py

# Test functionality
python test_functionality.py
```

### Resetting Database

```bash
# Reset PostgreSQL database (drops and recreates tables)
python reset_database.py
```

### Viewing Logs

Development mode shows detailed logs in the terminal. For production on Render, check the Render dashboard logs.

## Troubleshooting

### Port Already in Use

If port 5001 is in use, change it in `.env`:
```env
PORT=5002
```

### Database Connection Errors

1. Verify PostgreSQL is running:
   ```bash
   psql -U postgres -l
   ```

2. Check `.env` file has correct credentials

3. Test connection:
   ```bash
   python test_psql_connection.py
   ```

### Import Errors

Make sure virtual environment is activated and dependencies are installed:
```bash
source venv/bin/activate
pip install -r requirements.txt
```

## License

[Your License Here]

## Support

[Your Support Information Here]
