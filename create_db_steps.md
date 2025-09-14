# ==========================================
# MySQL INSTALLATION & DATABASE SETUP
# ==========================================

# STEP 1: INSTALL MySQL 
# ==========================================

sudo apt update
sudo apt install mysql-server
sudo systemctl start mysql.service


# ==========================================
# STEP 2: SECURE MySQL INSTALLATION (Optional but recommended)
# ==========================================
sudo mysql_secure_installation

# ==========================================
# STEP 3: LOGIN TO MySQL
# ==========================================

# Option A: If you set root password
mysql -u root -p
# Enter your root password when prompted

# Option B: If no root password (Ubuntu default)
sudo mysql

# Option C: If you have issues with root, create a new user first
sudo mysql
# Then run: ALTER USER 'root'@'localhost' IDENTIFIED WITH mysql_native_password BY 'your_password';
# Then: FLUSH PRIVILEGES;
# Then: exit
# Now login with: mysql -u root -p

# ==========================================
# STEP 4: CREATE DATABASE AND USER (Run these in MySQL prompt)
# ==========================================

sudo mysql
ALTER USER 'root'@'localhost' IDENTIFIED WITH mysql_native_password BY 'newpassword';
FLUSH PRIVILEGES;
EXIT;

CREATE DATABASE whatsapp_campaign CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
SHOW DATABASES;
EXIT;

# ==========================================
# STEP 5: Create migrations for your models
# ==========================================

python manage.py makemigrations

# ==========================================
# STEP 6: Apply migrations to create tables
# ==========================================

python manage.py migrate

# ==========================================
# STEP 7: Create Django Superuser
# ==========================================

### Enter username, email, and password when prompted
python manage.py createsuperuser

# ==========================================
# STEP 8: Start the development server
# ==========================================

python manage.py runserver