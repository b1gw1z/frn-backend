# Food Rescue Network (Backend)

This is the backend API for the **Food Rescue Network**, a platform designed to reduce food waste and combat hunger in Ogun State, Nigeria. It connects food donors (restaurants, farms, individuals) with rescuers (NGOs, volunteers) using geolocation to find the nearest available food.

##  Tech Stack
* **Language:** Python 3.x
* **Framework:** Flask
* **Database:** PostgreSQL + PostGIS (for spatial queries)
* **ORM:** SQLAlchemy + GeoAlchemy2
* **Authentication:** JWT (JSON Web Tokens) with `flask-jwt-extended`
* **Migrations:** Flask-Migrate

---

## Setup Instructions

Follow these steps to get the backend running on your local machine.

# 1. Prerequisites
Ensure you have the following installed:
* [Python](https://www.python.org/downloads/)
* [PostgreSQL](https://www.postgresql.org/download/) (Version 14 or higher recommended)
* **PostGIS Extension** (Required for location features)

# 2. Clone the Repository
```bash
git clone [https://github.com/YOUR_GITHUB_USERNAME/frn-backend.git](https://github.com/YOUR_GITHUB_USERNAME/frn-backend.git)
cd frn-backend

3. Create a Virtual EnvironmentWindows:
python -m venv venv
.\venv\Scripts\activate
Mac/Linux:
python3 -m venv venv
source venv/bin/activate

4. Install Dependencies
pip install -r requirements.txt

5. Environment ConfigurationCreate a file named .env in the root folder and add the following variables.(Note: Change the database password 'root' to your password)
SECRET_KEY=super_secret_key_change_this
DATABASE_URL=postgresql://postgres:root@localhost:5432/frn_new
JWT_SECRET_KEY=another_super_secret_key

6. Database SetupYou need to create the database and enable PostGIS before running migrations.
In your Terminal (or pgAdmin)

# 1. Create the database
createdb -U postgres frn_new

# 2. Enable PostGIS extension
psql -U postgres -d frn_new -c "CREATE EXTENSION postgis;"

Then apply the migrations:
flask db upgrade

7. Run the Server
python app.py

The server will start at http://127.0.0.1:5000 

Method,Endpoint,Description,Auth Required
POST,/api/register,Register a new Donor or Rescuer,No
POST,/api/login,Login to receive an Access Token,No
POST,/api/donations,Post a new food donation,Yes (Token)
GET,/api/donations,View available food. Optional params: ?lat=x&lng=y to see distance.,No
POST,/api/claim,Claim a donation,Yes (Token)

Testing
Use Postman to test the API.

Register a user.

Login to get the access_token.

For protected routes (Create Donation, Claim), go to the Authorization tab in Postman, select Bearer Token, and paste your token.