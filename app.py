import os
import json
import psycopg2
from flask import Flask, render_template, request, redirect, url_for
from psycopg2.extras import RealDictCursor

app = Flask(__name__)

# Load the questions when the app starts
with open('final_hr_questions.json', 'r') as f:
    SURVEY_DATA = json.load(f)

def get_db_connection():
    # Looks for 'DATABASE_URL' in environment variables (Render automatically provides this)
    # For local testing, replace os.environ.get(...) with your actual Supabase connection string
    conn = psycopg2.connect(os.environ.get('DATABASE_URL'))
    return conn

@app.route('/')
def index():
    return render_template('survey.html', survey_data=SURVEY_DATA)

@app.route('/submit', methods=['POST'])
def submit():
    form_data = request.form.to_dict()
    
    # Extract the optional name, default to "Anonymous" if empty
    respondent_name = form_data.pop('respondent_name', 'Anonymous')
    if not respondent_name: respondent_name = 'Anonymous'
    
    # The rest of form_data is the answers (e.g., "Creativity_1": "5")
    
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO survey_responses (respondent_name, answers) VALUES (%s, %s)",
            (respondent_name, json.dumps(form_data))
        )
        conn.commit()
        cur.close()
        conn.close()
        # Render the page again with a success flag
        return render_template('survey.html', survey_data=SURVEY_DATA, success=True)
    except Exception as e:
        return f"Database Error: {e}"

@app.route('/admin')
def admin():
    # SECURITY: Require a secret key in the URL (e.g., /admin?key=1234)
    if request.args.get('key') != 'mysecretadminpassword':
        return "Access Denied. Incorrect Key."

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM survey_responses ORDER BY submitted_at DESC")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    
    return render_template('admin.html', responses=rows)

if __name__ == '__main__':
    app.run(debug=True)