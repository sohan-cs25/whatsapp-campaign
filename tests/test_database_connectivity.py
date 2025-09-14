# test_db_connection.py
# Save this file in your project root and run it to test database connection

import pymysql
pymysql.install_as_MySQLdb()

import MySQLdb
import sys

def test_connection():
    """Test MySQL database connection"""
    
    # Database configuration - Update these values
    config = {
        'host': 'localhost',
        'user': 'fp_campaign_user',  # or 'root'
        'passwd': 'fp_campaign',  # your password
        'db': 'whatsapp_campaign',
        'charset': 'utf8mb4'
    }
    
    try:
        # Attempt to connect
        print("🔄 Attempting to connect to MySQL...")
        connection = MySQLdb.connect(**config)
        cursor = connection.cursor()
        
        # Test query
        cursor.execute("SELECT VERSION()")
        version = cursor.fetchone()
        print(f"✅ Successfully connected to MySQL!")
        print(f"📊 MySQL Version: {version[0]}")
        
        # Check database
        cursor.execute("SELECT DATABASE()")
        db = cursor.fetchone()
        print(f"📁 Current Database: {db[0]}")
        
        # Check tables (should be empty initially)
        cursor.execute("SHOW TABLES")
        tables = cursor.fetchall()
        if tables:
            print(f"\n📋 Tables in database:")
            for table in tables:
                print(f"   - {table[0]}")
        else:
            print("\n📋 No tables yet (this is normal before migrations)")
        
        # Check character set
        cursor.execute("""
            SELECT DEFAULT_CHARACTER_SET_NAME, DEFAULT_COLLATION_NAME 
            FROM INFORMATION_SCHEMA.SCHEMATA 
            WHERE SCHEMA_NAME = %s
        """, (config_dict['db'],))
        charset_info = cursor.fetchone()
        if charset_info:
            print(f"\n🔤 Database Character Set: {charset_info[0]}")
            print(f"🔤 Database Collation: {charset_info[1]}")
        
        cursor.close()
        connection.close()
        
        print("\n✨ Database connection test PASSED! You can proceed with Django setup.")
        print("\n📌 Next steps:")
        print("1. Run: python manage.py makemigrations")
        print("2. Run: python manage.py migrate")
        print("3. Run: python manage.py createsuperuser")
        print("4. Run: python manage.py runserver")
        return True
        
    except MySQLdb.Error as e:
        print(f"❌ MySQL Error: {e}")
        print("\n🔧 Troubleshooting tips:")
        print("1. Make sure MySQL service is running:")
        print("   - Ubuntu: sudo systemctl status mysql")
        print("   - Mac: brew services list")
        print("2. Verify your .env file has correct credentials")
        print("3. Ensure the database 'whatsapp_campaign' exists:")
        print("   - Login to MySQL: mysql -u root -p")
        print("   - Run: SHOW DATABASES;")
        print("4. Check user permissions:")
        print(f"   - GRANT ALL PRIVILEGES ON {config_dict['db']}.* TO '{config_dict['user']}'@'{config_dict['host']}';")
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        print("\n📦 Make sure mysqlclient is installed:")
        print("pip install mysqlclient")
        print("\nIf installation fails:")
        print("- Ubuntu: sudo apt-get install python3-dev default-libmysqlclient-dev build-essential")
        print("- Mac: brew install mysql-client")
        return False

if __name__ == "__main__":
    print("=" * 50)
    print("🔍 WhatsApp Campaign - Database Connection Test")
    print("=" * 50)
    test_connection()
    print("=" * 50)