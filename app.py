from flask import Flask, render_template, request, jsonify, Response
from queue_ds import Queue
from datetime import datetime
import sqlite3
import csv
import io

app = Flask(__name__)

# ==========================================================
# QUEUE
# ==========================================================

call_queue = Queue()


# ==========================================================
# DATABASE
# ==========================================================

DATABASE = "call_center.db"


def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


# ==========================================================
# DATABASE INITIALIZATION
# ==========================================================

def init_db():

    conn = get_db()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS calls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT NOT NULL,
            call_type TEXT NOT NULL,
            arrival_time TEXT NOT NULL,
            arrival_datetime TEXT NOT NULL,
            service_time TEXT,
            waiting_time REAL,
            status TEXT NOT NULL,
            agent TEXT
        )
    """)

    # Check old database columns
    columns = [
        row["name"]
        for row in conn.execute("PRAGMA table_info(calls)").fetchall()
    ]

    # Add agent column if using an older database
    if "agent" not in columns:
        conn.execute("ALTER TABLE calls ADD COLUMN agent TEXT")

    conn.commit()
    conn.close()


# ==========================================================
# LOAD WAITING CALLS AFTER RESTART
# ==========================================================

def load_waiting_calls():

    call_queue.clear()

    conn = get_db()

    calls = conn.execute("""
        SELECT *
        FROM calls
        WHERE status = 'Waiting'
        ORDER BY id ASC
    """).fetchall()

    conn.close()

    for row in calls:

        call = {
            "id": row["id"],
            "name": row["name"],
            "phone": row["phone"],
            "type": row["call_type"],
            "arrival_time": row["arrival_time"],
            "arrival_datetime":
                datetime.fromisoformat(row["arrival_datetime"]),
            "agent": row["agent"]
        }

        call_queue.enqueue(call)


# ==========================================================
# HOME PAGE
# ==========================================================

@app.route("/")
def home():

    return render_template("index.html")


# ==========================================================
# ADD CALL
# ==========================================================

@app.route("/add_call", methods=["POST"])
def add_call():

    data = request.json or {}

    name = data.get("name", "").strip()
    phone = data.get("phone", "").strip()
    call_type = data.get("type", "").strip()
    agent = data.get("agent", "").strip()

    if not name or not phone or not call_type:

        return jsonify({
            "message": "Please fill all required fields"
        }), 400

    arrival_datetime = datetime.now()

    arrival_time = arrival_datetime.strftime("%H:%M:%S")

    conn = get_db()

    cursor = conn.execute("""
        INSERT INTO calls
        (
            name,
            phone,
            call_type,
            arrival_time,
            arrival_datetime,
            status,
            agent
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        name,
        phone,
        call_type,
        arrival_time,
        arrival_datetime.isoformat(),
        "Waiting",
        agent
    ))

    call_id = cursor.lastrowid

    conn.commit()
    conn.close()

    call = {

        "id": call_id,

        "name": name,

        "phone": phone,

        "type": call_type,

        "arrival_time": arrival_time,

        "arrival_datetime": arrival_datetime,

        "agent": agent
    }

    call_queue.enqueue(call)

    return jsonify({

        "message": "Customer added successfully",

        "call": call
    })


# ==========================================================
# CURRENT QUEUE
# ==========================================================

@app.route("/queue")
def get_queue():

    queue_data = []

    for call in call_queue.display():

        waiting_seconds = (
            datetime.now()
            - call["arrival_datetime"]
        ).total_seconds()

        waiting_minutes = round(
            max(waiting_seconds, 0) / 60,
            2
        )

        queue_data.append({

            "id": call["id"],

            "name": call["name"],

            "phone": call["phone"],

            "type": call["type"],

            "arrival_time": call["arrival_time"],

            "waiting_time": waiting_minutes,

            "agent": call.get("agent", "")
        })

    return jsonify(queue_data)


# ==========================================================
# SERVE NEXT CALL
# ==========================================================

@app.route("/serve_call", methods=["POST"])
def serve_call():

    call = call_queue.dequeue()

    if call is None:

        return jsonify({
            "message": "Queue is empty"
        }), 400

    service_datetime = datetime.now()

    waiting_seconds = (
        service_datetime
        - call["arrival_datetime"]
    ).total_seconds()

    waiting_minutes = round(
        max(waiting_seconds, 0) / 60,
        2
    )

    service_time = service_datetime.strftime("%H:%M:%S")

    conn = get_db()

    conn.execute("""
        UPDATE calls

        SET
            service_time = ?,
            waiting_time = ?,
            status = 'Served'

        WHERE id = ?
    """, (
        service_time,
        waiting_minutes,
        call["id"]
    ))

    conn.commit()
    conn.close()

    completed_call = {

        "id": call["id"],

        "name": call["name"],

        "phone": call["phone"],

        "type": call["type"],

        "arrival_time": call["arrival_time"],

        "service_time": service_time,

        "waiting_time": waiting_minutes,

        "status": "Served",

        "agent": call.get("agent", "")
    }

    return jsonify({

        "message":
            f"{call['name']} served successfully",

        "call":
            completed_call
    })


# ==========================================================
# ASSIGN AGENT
# ==========================================================

@app.route("/assign_agent", methods=["POST"])
def assign_agent():

    data = request.json or {}

    call_id = data.get("id")
    agent = data.get("agent", "").strip()

    if not call_id or not agent:

        return jsonify({
            "message": "Please select an agent"
        }), 400

    conn = get_db()

    call = conn.execute("""
        SELECT *
        FROM calls
        WHERE id = ?
    """, (call_id,)).fetchone()

    if call is None:

        conn.close()

        return jsonify({
            "message": "Call not found"
        }), 404

    conn.execute("""
        UPDATE calls
        SET agent = ?
        WHERE id = ?
    """, (agent, call_id))

    conn.commit()
    conn.close()

    # Update in-memory queue
    for item in call_queue.items:

        if item["id"] == int(call_id):

            item["agent"] = agent

            break

    return jsonify({

        "message":
            f"Agent {agent} assigned successfully"
    })


# ==========================================================
# STATISTICS
# ==========================================================

@app.route("/stats")
def get_stats():

    conn = get_db()

    total_calls = conn.execute("""
        SELECT COUNT(*)
        FROM calls
    """).fetchone()[0]

    served_calls = conn.execute("""
        SELECT COUNT(*)
        FROM calls
        WHERE status = 'Served'
    """).fetchone()[0]

    waiting_calls = conn.execute("""
        SELECT COUNT(*)
        FROM calls
        WHERE status = 'Waiting'
    """).fetchone()[0]

    total_waiting_time = conn.execute("""
        SELECT COALESCE(SUM(waiting_time), 0)
        FROM calls
        WHERE status = 'Served'
    """).fetchone()[0]

    average_waiting_time = conn.execute("""
        SELECT COALESCE(AVG(waiting_time), 0)
        FROM calls
        WHERE status = 'Served'
    """).fetchone()[0]

    maximum_waiting_time = conn.execute("""
        SELECT COALESCE(MAX(waiting_time), 0)
        FROM calls
        WHERE status = 'Served'
    """).fetchone()[0]

    conn.close()

    return jsonify({

        "total_calls": total_calls,

        "served_calls": served_calls,

        "waiting_calls": waiting_calls,

        "total_waiting_time":
            round(total_waiting_time, 2),

        "average_waiting_time":
            round(average_waiting_time, 2),

        "maximum_waiting_time":
            round(maximum_waiting_time, 2)
    })


# ==========================================================
# CALL HISTORY
# ==========================================================

@app.route("/history")
def call_history():

    conn = get_db()

    calls = conn.execute("""
        SELECT
            id,
            name,
            phone,
            call_type,
            arrival_time,
            service_time,
            waiting_time,
            status,
            agent
        FROM calls
        ORDER BY id DESC
    """).fetchall()

    conn.close()

    history = []

    for call in calls:

        history.append({

            "id": call["id"],

            "name": call["name"],

            "phone": call["phone"],

            "type": call["call_type"],

            "arrival_time": call["arrival_time"],

            "service_time":
                call["service_time"]
                if call["service_time"]
                else "-",

            "waiting_time":
                call["waiting_time"]
                if call["waiting_time"] is not None
                else 0,

            "status": call["status"],

            "agent":
                call["agent"]
                if call["agent"]
                else "-"
        })

    return jsonify(history)


# ==========================================================
# ANALYTICS
# ==========================================================

@app.route("/analytics")
def analytics():

    conn = get_db()

    # Calls by type
    type_data = conn.execute("""
        SELECT
            call_type,
            COUNT(*) AS count
        FROM calls
        GROUP BY call_type
    """).fetchall()

    # Served calls waiting time
    waiting_data = conn.execute("""
        SELECT
            id,
            name,
            waiting_time
        FROM calls
        WHERE status = 'Served'
        ORDER BY id ASC
    """).fetchall()

    conn.close()

    return jsonify({

        "call_types": [
            {
                "type": row["call_type"],
                "count": row["count"]
            }
            for row in type_data
        ],

        "waiting_times": [
            {
                "id": row["id"],
                "name": row["name"],
                "waiting_time":
                    round(row["waiting_time"], 2)
            }
            for row in waiting_data
        ]
    })


# ==========================================================
# EXPORT CSV
# ==========================================================

@app.route("/export_csv")
def export_csv():

    conn = get_db()

    calls = conn.execute("""
        SELECT
            id,
            name,
            phone,
            call_type,
            arrival_time,
            service_time,
            waiting_time,
            status,
            agent
        FROM calls
        ORDER BY id ASC
    """).fetchall()

    conn.close()

    output = io.StringIO()

    writer = csv.writer(output)

    writer.writerow([
        "ID",
        "Customer Name",
        "Phone",
        "Call Type",
        "Arrival Time",
        "Service Time",
        "Waiting Time (min)",
        "Status",
        "Agent"
    ])

    for call in calls:

        writer.writerow([

            call["id"],

            call["name"],

            call["phone"],

            call["call_type"],

            call["arrival_time"],

            call["service_time"]
            if call["service_time"]
            else "-",

            call["waiting_time"]
            if call["waiting_time"] is not None
            else 0,

            call["status"],

            call["agent"]
            if call["agent"]
            else "-"
        ])

    output.seek(0)

    return Response(

        output.getvalue(),

        mimetype="text/csv",

        headers={
            "Content-Disposition":
                "attachment; filename=call_center_history.csv"
        }
    )


# ==========================================================
# CLEAR SERVED HISTORY
# ==========================================================

@app.route("/clear_history", methods=["DELETE"])
def clear_history():

    conn = get_db()

    conn.execute("""
        DELETE FROM calls
        WHERE status = 'Served'
    """)

    conn.commit()
    conn.close()

    return jsonify({

        "message":
            "Served call history cleared"
    })


# ==========================================================
# START APPLICATION
# ==========================================================

init_db()
load_waiting_calls()


if __name__ == "__main__":

    app.run(
        debug=True,
        host="127.0.0.1",
        port=5001
    )