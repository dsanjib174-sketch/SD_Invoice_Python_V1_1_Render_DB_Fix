# SD Invoice Python V1.1 Render DB Fix

Fixed:
- Internal Server Error on /dashboard
- Database now initializes automatically when Render starts with gunicorn
- Added gunicorn in requirements.txt

Render settings:
Build Command:
pip install -r requirements.txt

Start Command:
gunicorn app:app

Login:
Super Admin: superadmin / admin123
Demo Client: demo@sdinvoice.com / admin / 1234
