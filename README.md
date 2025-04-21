# Setup Instructions

## Installation

### 1. Clone Repository
```bash
git clone <repository-url>
cd <repository-name>
```

### 2. Create and Activate Python Virtual Environment
```bash
# On Windows
python -m venv venv
.\venv\Scripts\activate

# On macOS/Linux
python3 -m venv venv
source venv/bin/activate
```

### 3. Install Dependencies
```bash
# Install from requirements.txt
pip install -r requirements.txt
```

## Database Configuration

### Option 1: SQLite (Default)
- Automatically creates `app.db` file in project directory
- No additional configuration needed

### Option 2: MySQL
1. Create database:
   ```sql
   CREATE DATABASE your_database_name;
   ```

2. Configure environment:
   ```bash
   cp .env .env
   ```

3. Edit `.env` file with your database credentials:
   ```
   FLASK_SECRET_KEY=your_secret_key_here
   FLASK_DEBUG=True
   DATABASE_URL=mysql://username:password@localhost:3306/your_database_name
   ```

## Launch Application
```bash
python main.py
```

## Login Information

### Administrator Access
- **Role:** Administrator
- **Username:** `admin@example.com`
- **Password:** `admin123`

### Other User Types (HOD, Teacher, Student)
1. Log in as administrator
2. Go to Admin Panel
3. Add new user profiles
4. A generated password will appear at the top of the website
5. Use the provided email and generated password to log in

> **Important:** Save the generated password when displayed as it won't be shown again.