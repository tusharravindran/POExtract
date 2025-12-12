# PO Extract Application

A Flask web application for extracting and managing Purchase Order (PO) data from PDF files.

## Prerequisites

- Python 3.8 or higher
- Virtual environment (recommended)

## Installation

1. Create a virtual environment (if not already created):
   ```bash
   python3 -m venv venv
   ```

2. Activate the virtual environment:
   ```bash
   source venv/bin/activate  # On macOS/Linux
   # or
   venv\Scripts\activate  # On Windows
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Running the Application

1. Make sure you're in the project directory and the virtual environment is activated:
   ```bash
   cd /Users/tusharr/Desktop/POExtract
   source venv/bin/activate
   ```

2. Run the Flask application:
   ```bash
   python app.py
   ```

3. Open your web browser and navigate to:
   ```
   http://127.0.0.1:5000
   ```

## Application Features

- **Upload PDFs**: Upload multiple PO PDF files for processing
- **Extract Data**: Automatically extracts PO information from PDFs
- **Dashboard**: View and manage all PO items with inline editing
- **Style Master**: Manage EAN to Style Number and Buyer mappings
- **Excel Export**: Download dashboard data as Excel file

## Project Structure

- `app.py` - Main Flask application
- `extractor.py` - PDF text extraction and parsing logic
- `database.py` - Database initialization and connection management
- `templates/` - HTML templates for the web interface
- `uploads/` - Directory for uploaded PDF files
- `po_data.db` - SQLite database for PO items
- `style_master.db` - SQLite database for style master data

## Notes

- The application runs in debug mode by default
- Database tables are automatically created on first run
- Uploaded PDFs are stored in the `uploads/` directory

