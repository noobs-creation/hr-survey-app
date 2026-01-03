import os
import json
import psycopg2
from flask import Flask, render_template, request
from psycopg2.extras import RealDictCursor
from datetime import datetime
import pytz # New library for Timezones

app = Flask(__name__)

# Load questions
with open('final_hr_questions.json', 'r') as f:
    SURVEY_DATA = json.load(f)

def get_db_connection():
    conn = psycopg2.connect(os.environ.get('DATABASE_URL'))
    return conn

def get_ist_time():
    """Returns current time in Indian Standard Time"""
    utc_now = datetime.now(pytz.utc)
    ist_tz = pytz.timezone('Asia/Kolkata')
    return utc_now.astimezone(ist_tz)

@app.route('/')
def index():
    return render_template('survey.html', survey_data=SURVEY_DATA)

@app.route('/submit', methods=['POST'])
def submit():
    form_data = request.form.to_dict()
    respondent_name = form_data.pop('respondent_name', 'Anonymous') or 'Anonymous'
    
    # Process answers to integers
    processed_answers = {}
    for key, value in form_data.items():
        try:
            processed_answers[key] = int(value)
        except ValueError:
            processed_answers[key] = value
    
    # Get current time in IST
    ist_now = get_ist_time()

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        # We explicitly insert the IST timestamp
        cur.execute(
            "INSERT INTO survey_responses (respondent_name, answers, submitted_at) VALUES (%s, %s, %s)",
            (respondent_name, json.dumps(processed_answers), ist_now)
        )
        conn.commit()
        cur.close()
        conn.close()
        return render_template('survey.html', survey_data=SURVEY_DATA, success=True)
    except Exception as e:
        return f"Database Error: {e}"

@app.route('/admin')
def admin():
    if request.args.get('key') != 'mysecretadminpassword':
        return "Access Denied."

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM survey_responses ORDER BY submitted_at DESC")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    
    return render_template('admin.html', responses=rows, survey_data=SURVEY_DATA)

@app.route('/report')
def report():
    # SECURITY: Require secret key
    if request.args.get('key') != 'mysecretadminpassword':
        return "Access Denied."

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT answers FROM survey_responses")
    rows = cur.fetchall()
    cur.close()
    conn.close()

    if not rows:
        return "No data available to generate report."

    # --- CALCULATION ENGINE (NORMALIZED) ---
    
    # 1. Initialize storage
    category_scores = {category: [] for category in SURVEY_DATA.keys()}
    
    total_responses = len(rows)
    
    # 2. Collect all raw scores into their categories
    for row in rows:
        answers = row['answers']
        for key, value in answers.items():
            if not isinstance(value, int): continue

            # Parse key (e.g. "Creativity_1") -> "Creativity"
            if '_' in key:
                category_part = key.rsplit('_', 1)[0]
                if category_part in category_scores:
                    category_scores[category_part].append(value)

    # 3. Calculate Normalized Category Averages
    # Example: {'Creativity': 4.2, 'Innovation': 3.5, ...}
    final_averages = {}
    valid_categories_count = 0
    sum_of_category_averages = 0

    for cat, scores in category_scores.items():
        if scores:
            # This is the average for this specific category (Scale 1-5)
            # It is automatically normalized by the number of questions because we divide by len(scores)
            avg = sum(scores) / len(scores)
            final_averages[cat] = round(avg, 2)
            
            # Add to the running total for the Overall Score
            sum_of_category_averages += avg
            valid_categories_count += 1
        else:
            final_averages[cat] = 0

    # 4. Calculate Overall Engagement Score (NORMALIZED)
    # We divide by the number of CATEGORIES, not the number of questions.
    # This ensures "Creativity" (4 questions) has equal weight to "Satisfaction" (6 questions).
    if valid_categories_count > 0:
        overall_score = round(sum_of_category_averages / valid_categories_count, 2)
    else:
        overall_score = 0

    # 5. Find Strongest and Weakest Areas
    # Filter out categories with 0 score (no data) to avoid showing them as "Weakest"
    active_cats = {k:v for k,v in final_averages.items() if v > 0}
    sorted_cats = sorted(active_cats.items(), key=lambda x: x[1], reverse=True)
    
    strongest = sorted_cats[0] if sorted_cats else ("None", 0)
    weakest = sorted_cats[-1] if sorted_cats else ("None", 0)

    # IST Timestamp
    ist_now = get_ist_time()

    return render_template('report.html', 
                           averages=final_averages, 
                           total=total_responses,
                           overall=overall_score,
                           strongest=strongest,
                           weakest=weakest,
                           timestamp=ist_now.strftime('%Y-%m-%d %I:%M %p'))

if __name__ == '__main__':
    app.run(debug=True)