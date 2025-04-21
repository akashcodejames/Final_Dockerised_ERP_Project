# NITRA Educational ERP - Dockerized Setup

A comprehensive Educational ERP system built with Flask and containerized using Docker. This system includes features like timetable generation, library management, and user management with different role types (Administrator, HOD, Teacher, Student).

## 🚀 Features

- **Multi-User Role System**: Admin, HOD, Teacher, and Student portals
- **Timetable Generator**: AI-powered timetable generation using genetic algorithms
- **Library Management System**: Complete book management and tracking
- **Email Notifications**: Automated email system for important updates
- **Database Management Interface**: Easy-to-use database administration
- **File Upload System**: Secure file management for notes and resources
- **Responsive Design**: Mobile-friendly interface

## 🛠 Tech Stack

- **Backend**: Python/Flask
- **Database**: MySQL 8.0
- **Cache & Message Broker**: Redis
- **Web Server**: Nginx
- **Task Queue**: Celery
- **Frontend**: Bootstrap 5, JavaScript
- **Containerization**: Docker & Docker Compose

## 📋 Prerequisites

- Docker Engine 20.10+
- Docker Compose 2.0+
- Git

## 🔧 Installation & Setup

1. **Clone the Repository**
   ```bash
   git clone https://github.com/akashcodejames/Final_Dockerised_ERP_Project.git
   cd Final_Dockerised_ERP_Project
   ```

2. **Environment Configuration**
   ```bash
   # Copy example environment file
   cp .env.example .env
   
   # Edit .env file with your configurations
   nano .env
   ```

   3. **Required Environment Variables**
      ```env
      # ========================
         # Flask Configuration
         # ========================
         FLASK_SECRET_KEY=82944b2a04fc1b5d0be4ddec11744106005b77ee40645d0142b5bb2bf1601f64
         FLASK_DEBUG=True
      
         # ========================
         # Database Configuration
         # ========================
         MYSQL_DATABASE=xyz
         MYSQL_USER=docking_docker
         MYSQL_PASSWORD=tooring_toor
         MYSQL_ROOT_PASSWORD=rootpassword_password
         DATABASE_URL=mysql://docking_docker:tooring_toor@db:3306/xyz
         # Tip: Use "db" as hostname in DATABASE_URL since it's the service name in docker-compose
      
         # ========================
         # Mail Configuration
         # (Email credentials removed for security)
         # ========================
         MAIL_USERNAME=
         MAIL_PASSWORD=
         MAIL_USE_TLS=False
         MAIL_PORT=587
         MAIL_SERVER=smtp.gmail.com
      
         SMTP_USERNAME=
         SMTP_PASSWORD=
         SMTP_USE_TLS=False
         SMTP_PORT=587
         SMTP_SERVER=smtp.gmail.com
      
         # ========================
         # Redis Configuration
         # ========================
         REDIS_HOST=redis
      ```

4. **Build and Start Services**
   ```bash
   # Build and start all services
   docker-compose up --build -d
   
   # View logs
   docker-compose logs -f
   ```

## 🌐 Accessing the Application

- **Main Application**: http://localhost:8000
- **Database Admin (Adminer)**: http://localhost:8080
- **Default Admin Login**:
  - Email: `admin@example.com`
  - Password: `admin123`

## 🔌 Service Architecture

- **Nginx** (Port 8000): Reverse proxy and static file serving
- **Flask Application** (Port 5001): Main application server
- **MySQL** (Port 3308): Database server
- **Redis** (Port 6379): Cache and message broker
- **Celery**: Background task processing
- **Adminer** (Port 8080): Database management interface

## 📁 Project Structure

```
.
├── app/
│   ├── static/
│   ├── templates/
│   └── uploads/
├── services/
│   ├── celery_worker.py
│   └── tasks.py
├── docker-compose.yml
├── Dockerfile
├── Dockerfile_nginx
├── nginx.conf
├── requirements.txt
└── gunicorn.conf.py
```

## 🛡 Security Features

- Rate limiting on API endpoints
- Secure file upload handling
- Password hashing
- SQL injection protection
- CSRF protection
- Secure session handling

## 💾 Backup and Restore

**Backup Database**:
```bash
docker exec -it [mysql_container_name] mysqldump -u [user] -p[password] [database_name] > backup.sql
```

**Restore Database**:
```bash
docker exec -i [mysql_container_name] mysql -u [user] -p[password] [database_name] < backup.sql
```

## 🔄 Scaling and Performance

- Gunicorn workers automatically scale based on CPU cores
- Redis caching for improved performance
- Nginx configured for optimal static file serving
- Database connection pooling
- Celery for handling background tasks

## 🐛 Troubleshooting

1. **Services Not Starting**:
   ```bash
   # Check service status
   docker-compose ps
   
   # View detailed logs
   docker-compose logs [service_name]
   ```

2. **Database Connection Issues**:
   - Verify MySQL container is running
   - Check environment variables in .env
   - Ensure database port is not conflicting

3. **Email Not Working**:
   - Verify SMTP credentials
   - Check email service logs
   - Ensure port 587 is not blocked

   