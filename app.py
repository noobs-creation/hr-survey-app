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
    # 1. Get the raw form data
    raw_data = request.form.to_dict()
    
    # 2. Extract the respondent's name (remove it from the answers list)
    respondent_name = raw_data.pop('respondent_name', 'Anonymous')
    if not respondent_name: respondent_name = 'Anonymous'
    
    # 3. Process the remaining data to convert "5" (string) -> 5 (integer)
    processed_answers = {}
    for key, value in raw_data.items():
        try:
            # Try to convert to an integer (e.g., "5" becomes 5)
            processed_answers[key] = int(value)
        except ValueError:
            # If it's not a number, keep it as text
            processed_answers[key] = value
    
    # 4. Save to Supabase
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO survey_responses (respondent_name, answers) VALUES (%s, %s)",
            (respondent_name, json.dumps(processed_answers))
        )
        conn.commit()
        cur.close()
        conn.close()
        return render_template('survey.html', survey_data=SURVEY_DATA, success=True)
    except Exception as e:
        return f"Database Error: {e}"

@app.route('/admin')
def admin():
    # SECURITY: Require a secret key in the URL
    if request.args.get('key') != 'mysecretadminpassword':
        return "Access Denied. Incorrect Key."

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM survey_responses ORDER BY submitted_at DESC")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    
    # Pass 'survey_data' so we can show the actual question text, not just the ID
    return render_template('admin.html', responses=rows, survey_data=SURVEY_DATA)

if __name__ == '__main__':
    app.run(debug=True)