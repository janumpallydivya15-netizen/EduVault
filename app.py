from flask import Flask, render_template, request, redirect, url_for, session
from werkzeug.utils import secure_filename
import os
from datetime import datetime
import json
import boto3

# ===============================
# CONFIG
# ===============================

USERS_FILE = "users.json"
UPLOAD_FOLDER = "uploads"
DEADLINE = datetime(2026, 3, 1, 9, 30)
SUBMISSIONS_FILE = "submissions.json"

AWS_REGION = "ap-south-1"
SNS_TOPIC_ARN = "arn:aws:sns:ap-south-1:120121146931:EduVault-Notifications"

app = Flask(__name__)
app.secret_key = "eduvault-secret-key"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ===============================
# AWS SNS CLIENT
# ===============================

sns_client = boto3.client("sns", region_name=AWS_REGION)

def send_sns_notification(subject, message):
    try:
        print("Sending SNS...")
        response = sns_client.publish(
            TopicArn=SNS_TOPIC_ARN,
            Subject=subject,
            Message=message
        )
        print("SNS Sent:", response)
    except Exception as e:
        print("SNS Error:", e)
        
# ===============================
# LOAD USERS
# ===============================

if os.path.exists(USERS_FILE):
    with open(USERS_FILE, "r") as f:
        users = json.load(f)
else:
    users = {}

if os.path.exists(SUBMISSIONS_FILE):
    with open(SUBMISSIONS_FILE, "r") as f:
        submissions = json.load(f)
        # Convert submitted_at back to datetime
        for s in submissions:
            s["submitted_at"] = datetime.fromisoformat(s["submitted_at"])
else:
    submissions = []

    SUBMISSIONS_FILE = "submissions.json"

def save_submissions():
    data = []

    for s in submissions:
        copy = s.copy()
        copy["submitted_at"] = s["submitted_at"].isoformat()
        data.append(copy)

    with open(SUBMISSIONS_FILE, "w") as f:
        json.dump(data, f)
# ===============================
# ROLE DECORATOR
# ===============================

def login_required(role=None):
    def wrapper(func):
        def decorated(*args, **kwargs):
            if "user" not in session:
                return redirect(url_for("home"))
            if role and session.get("role") != role:
                return redirect(url_for("home"))
            return func(*args, **kwargs)
        decorated.__name__ = func.__name__
        return decorated
    return wrapper

# ===============================
# HOME
# ===============================

@app.route("/")
def home():
    return render_template("index.html")

# ===============================
# STUDENT
# ===============================

@app.route("/student-register", methods=["GET", "POST"])
def student_register():
    if request.method == "POST":
        student_id = request.form.get("student_id")
        email = request.form.get("email")
        password = request.form.get("password")

        if student_id in users:
            return render_template("student_register.html", error="Student exists")

        users[student_id] = {
            "email": email,
            "password": password,
            "role": "student"
        }

        with open(USERS_FILE, "w") as f:
            json.dump(users, f)

        return redirect(url_for("student_login"))

    return render_template("student_register.html")


@app.route("/student-login", methods=["GET", "POST"])
def student_login():
    if request.method == "POST":
        student_id = request.form.get("student_id")
        password = request.form.get("password")

        if student_id in users and users[student_id]["password"] == password:
            session["user"] = student_id
            session["role"] = "student"
            return redirect(url_for("student_dashboard"))

        return render_template("student_login.html", error="Invalid credentials")

    return render_template("student_login.html")


@app.route("/student-dashboard")
@login_required("student")
def student_dashboard():
    user_submissions = [
        s for s in submissions
        if s["student"] == session["user"]
    ]

    return render_template("student_dashboard.html",
                           submissions=user_submissions)


@app.route("/upload", methods=["GET", "POST"])
@login_required("student")
def upload():
    if request.method == "POST":

        assignment = request.form.get("assignment")
        file = request.files.get("file")

        if not assignment or not file:
            return render_template("upload.html", error="Please fill all fields")

        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        file.save(filepath)

        submission_time = datetime.now()
        status = "Late" if submission_time > DEADLINE else "Submitted"

        submissions.append({
            "student": session["user"],
            "assignment": assignment,
            "filename": filename,
            "status": status,
            "grade": None,
            "feedback": None,
            "submitted_at": submission_time
        })

        # 🔥 ADD SNS HERE (IMPORTANT)
        try:
            response = sns.publish(
                TopicArn=SNS_TOPIC_ARN,
                Message=f"""
New Assignment Uploaded

Student: {session['user']}
Assignment: {assignment}
Status: {status}
Submitted At: {submission_time}
""",
                Subject="New Assignment Submission - EduVault"
            )
            print("SNS SENT:", response)

        except Exception as e:
            print("SNS ERROR:", e)

        return render_template(
            "upload.html",
            success="File uploaded successfully!"
        )

    return render_template("upload.html")
@app.route("/history")
@login_required("student")
def history():
    user_submissions = [
        s for s in submissions
        if s["student"] == session["user"]
    ]

    return render_template("history.html", submissions=user_submissions)

# ===============================
# INSTRUCTOR
# ===============================

@app.route("/instructor-login", methods=["GET", "POST"])
def instructor_login():
    if request.method == "POST":
        instructor_id = request.form.get("instructor_id")
        password = request.form.get("password")

        if instructor_id in users and users[instructor_id]["password"] == password:
            session["user"] = instructor_id
            session["role"] = "instructor"
            return redirect(url_for("instructor_dashboard"))

        return render_template("instructor_login.html", error="Invalid credentials")

    return render_template("instructor_login.html")

@app.route("/instructor-register", methods=["GET", "POST"])
def instructor_register():
    if request.method == "POST":
        instructor_id = request.form.get("instructor_id")
        email = request.form.get("email")
        password = request.form.get("password")

        if instructor_id in users:
            return render_template("instructor_register.html", error="Instructor already exists")

        users[instructor_id] = {
            "email": email,
            "password": password,
            "role": "instructor"
        }

        with open(USERS_FILE, "w") as f:
            json.dump(users, f)

        return redirect(url_for("instructor_login"))

    return render_template("instructor_register.html")


@app.route("/instructor-dashboard")
@login_required("instructor")
def instructor_dashboard():
    total = len(submissions)
    graded = len([s for s in submissions if s["status"] == "Graded"])
    pending = len([s for s in submissions if s["status"] == "Submitted"])
    late = len([s for s in submissions if s["status"] == "Late"])

    return render_template("instructor_dashboard.html",
                           total=total,
                           graded=graded,
                           pending=pending,
                           late=late,
                           submissions=submissions)


@app.route("/grade/<int:index>", methods=["GET", "POST"])
@login_required("instructor")
def grade_submission(index):

    submission = submissions[index]

    if request.method == "POST":
        grade = int(request.form.get("grade"))
        feedback = request.form.get("feedback")
        late_action = request.form.get("late_action")

        if submission["status"] == "Late":

            if late_action == "reject":
                submission["status"] = "Rejected"
                submission["grade"] = 0

                send_sns_notification(
                    "Assignment Rejected",
                    f"{submission['student']}'s submission was rejected due to being late."
                )

                return redirect(url_for("instructor_dashboard"))

            elif late_action == "accept":
                grade = max(0, grade - 10)

        submission["grade"] = grade
        submission["feedback"] = feedback
        submission["status"] = "Graded"

        # 🔥 SNS ALERT WHEN GRADED
        send_sns_notification(
            "Assignment Graded",
            f"{submission['student']}'s assignment graded.\nMarks: {grade}"
        )

        return redirect(url_for("instructor_dashboard"))

    return render_template("grade.html", submission=submission)


@app.route("/report")
@login_required("instructor")
def report():
    total = len(submissions)
    graded = len([s for s in submissions if s["status"] == "Graded"])
    pending = len([s for s in submissions if s["status"] == "Submitted"])
    late = len([s for s in submissions if s["status"] == "Late"])
    rejected = len([s for s in submissions if s["status"] == "Rejected"])

    data = {
        "total": total,
        "graded": graded,
        "pending": pending,
        "late": late,
        "rejected": rejected
    }

    return render_template("report.html", data=data)

@app.route("/delete/<int:index>")
@login_required("instructor")
def delete_submission(index):
    if index < len(submissions):
        submissions.pop(index)
    return redirect(url_for("instructor_dashboard"))

@app.route("/reopen/<int:index>")
@login_required("instructor")
def reopen_submission(index):

    if index < len(submissions):

        submission = submissions[index]

        # If original_status exists, restore it
        if "original_status" in submission:
            submission["status"] = submission["original_status"]

        else:
            # Fallback logic for old submissions
            # If it was graded and originally late, detect again
            if submission["submitted_at"] > DEADLINE:
                submission["status"] = "Late"
            else:
                submission["status"] = "Submitted"

        submission["grade"] = None
        submission["feedback"] = None

    return redirect(url_for("instructor_dashboard"))
# ===============================
# LOGOUT
# ===============================

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))

# ===============================
# RUN
# ===============================

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)


