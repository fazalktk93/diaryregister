@echo off
echo 🔧 Creating virtual environment...
python -m venv venv

echo ✅ Activating virtual environment...
call venv\Scripts\activate

echo 📦 Upgrading pip...
python -m pip install --upgrade pip

echo 📦 Installing requirements...
pip install -r requirements.txt

echo 🗄️ Running migrations...
python manage.py makemigrations
python manage.py migrate

echo 🚀 Starting server...
python manage.py runserver 0.0.0.0:7000

pause
