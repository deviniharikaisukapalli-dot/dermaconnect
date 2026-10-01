from io import BytesIO
import hmac
import math
import os
import secrets
import sqlite3

import qrcode
from flask import Flask, Response, abort, g, jsonify, render_template, request, send_file, url_for

from init_db import DB_PATH, initialize_database


app = Flask(__name__)
initialize_database()
DEMO_AUTH_REQUIRED = os.environ.get("DEMO_AUTH_REQUIRED", "").lower() == "true"
DEMO_USERNAME = os.environ.get("DEMO_USERNAME", "demo")
DEMO_PASSWORD = os.environ.get("DEMO_PASSWORD")


@app.before_request
def require_demo_login():
    if not DEMO_AUTH_REQUIRED:
        return None
    if not DEMO_PASSWORD:
        return "Demo password is not configured.", 503

    credentials = request.authorization
    if (
        credentials is None
        or not hmac.compare_digest(credentials.username or "", DEMO_USERNAME)
        or not hmac.compare_digest(credentials.password or "", DEMO_PASSWORD)
    ):
        return Response(
            "Login required.",
            401,
            {"WWW-Authenticate": 'Basic realm="DermaConnect demo"'},
        )


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_error=None):
    connection = g.pop("db", None)
    if connection is not None:
        connection.close()


def payload():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        abort(400, description="Request body must be a JSON object.")
    return data


def required(data, *keys):
    missing = [key for key in keys if data.get(key) is None or data.get(key) == ""]
    if missing:
        abort(400, description=f"Missing required field(s): {', '.join(missing)}.")


def as_dicts(rows):
    return [dict(row) for row in rows]


def optional_coordinate(value, field):
    if value is None:
        return None
    try:
        coordinate = float(value)
    except (TypeError, ValueError):
        abort(400, description=f"{field} must be a number.")
    if not math.isfinite(coordinate):
        abort(400, description=f"{field} must be finite.")
    return coordinate


def distance_km(latitude_a, longitude_a, latitude_b, longitude_b):
    radius = 6371.0
    lat_a, lat_b = math.radians(latitude_a), math.radians(latitude_b)
    delta_lat = lat_b - lat_a
    delta_lon = math.radians(longitude_b - longitude_a)
    arc = math.sin(delta_lat / 2) ** 2 + math.cos(lat_a) * math.cos(lat_b) * math.sin(delta_lon / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(arc))


@app.errorhandler(sqlite3.IntegrityError)
def handle_integrity_error(error):
    return jsonify(error="Database constraint failed", detail=str(error)), 409


@app.errorhandler(404)
def handle_not_found(error):
    return jsonify(error="Not found", detail=getattr(error, "description", "Resource not found.")), 404


@app.errorhandler(400)
def handle_bad_request(error):
    return jsonify(error="Bad request", detail=getattr(error, "description", "Invalid request.")), 400


@app.errorhandler(409)
def handle_conflict(error):
    return jsonify(error="Conflict", detail=getattr(error, "description", "Request conflicts with current state.")), 409


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/patient/<token>")
def patient_page(token):
    return render_template("patient.html", token=token)


@app.get("/api/health")
def health():
    get_db().execute("SELECT 1")
    return jsonify(status="ok", database="connected")


@app.get("/api/doctors")
def list_doctors():
    rows = get_db().execute("SELECT * FROM doctors ORDER BY full_name").fetchall()
    return jsonify(doctors=as_dicts(rows))


@app.post("/api/doctors")
def create_doctor():
    data = payload()
    required(data, "full_name", "license_number")
    db = get_db()
    with db:
        cursor = db.execute(
            "INSERT INTO doctors (full_name, license_number, phone, email) VALUES (?, ?, ?, ?)",
            (data["full_name"].strip(), data["license_number"].strip(), data.get("phone"), data.get("email")),
        )
    return jsonify(id=cursor.lastrowid), 201


@app.get("/api/patients")
def list_patients():
    rows = get_db().execute("SELECT * FROM patients ORDER BY full_name").fetchall()
    return jsonify(patients=as_dicts(rows))


@app.post("/api/patients")
def create_patient():
    data = payload()
    required(data, "full_name")
    db = get_db()
    with db:
        cursor = db.execute(
            "INSERT INTO patients (full_name, phone, email) VALUES (?, ?, ?)",
            (data["full_name"].strip(), data.get("phone"), data.get("email")),
        )
    return jsonify(id=cursor.lastrowid), 201


@app.get("/api/stores")
def list_stores():
    rows = get_db().execute(
        "SELECT * FROM stores WHERE is_partner = 1 ORDER BY name"
    ).fetchall()
    return jsonify(stores=as_dicts(rows))


@app.post("/api/stores")
def create_store():
    data = payload()
    required(data, "name", "address")
    latitude = optional_coordinate(data.get("latitude"), "latitude")
    longitude = optional_coordinate(data.get("longitude"), "longitude")
    if latitude is not None and not -90 <= latitude <= 90:
        abort(400, description="latitude must be between -90 and 90.")
    if longitude is not None and not -180 <= longitude <= 180:
        abort(400, description="longitude must be between -180 and 180.")
    db = get_db()
    with db:
        cursor = db.execute(
            """INSERT INTO stores (name, address, latitude, longitude, phone, is_partner)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                data["name"].strip(), data["address"].strip(), latitude, longitude,
                data.get("phone"), int(bool(data.get("is_partner", True))),
            ),
        )
    return jsonify(id=cursor.lastrowid), 201


@app.get("/api/products")
def list_products():
    rows = get_db().execute("SELECT * FROM products ORDER BY name").fetchall()
    return jsonify(products=as_dicts(rows))


@app.post("/api/products")
def create_product():
    data = payload()
    required(data, "name")
    db = get_db()
    with db:
        cursor = db.execute(
            """INSERT INTO products (name, brand, category, description, sku)
               VALUES (?, ?, ?, ?, ?)""",
            (
                data["name"].strip(), data.get("brand"), data.get("category"),
                data.get("description"), data.get("sku"),
            ),
        )
    return jsonify(id=cursor.lastrowid), 201


@app.route("/api/stores/<int:store_id>/inventory", methods=["GET", "PUT"])
def store_inventory(store_id):
    db = get_db()
    if request.method == "GET":
        rows = db.execute(
            """SELECT p.id AS product_id, p.name, p.brand, i.stock_quantity, i.updated_at
               FROM inventory i JOIN products p ON p.id = i.product_id
               WHERE i.store_id = ? ORDER BY p.name""",
            (store_id,),
        ).fetchall()
        return jsonify(store_id=store_id, inventory=as_dicts(rows))

    data = payload()
    required(data, "product_id", "stock_quantity")
    try:
        product_id = int(data["product_id"])
        stock_quantity = int(data["stock_quantity"])
    except (TypeError, ValueError):
        abort(400, description="product_id and stock_quantity must be integers.")
    if stock_quantity < 0:
        abort(400, description="stock_quantity cannot be negative.")
    with db:
        db.execute(
            """INSERT INTO inventory (store_id, product_id, stock_quantity)
               VALUES (?, ?, ?)
               ON CONFLICT(store_id, product_id) DO UPDATE SET
                   stock_quantity = excluded.stock_quantity,
                   updated_at = CURRENT_TIMESTAMP""",
            (store_id, product_id, stock_quantity),
        )
    return jsonify(status="updated", store_id=store_id, product_id=product_id, stock_quantity=stock_quantity)


@app.post("/api/prescriptions")
def create_prescription():
    data = payload()
    required(data, "doctor_id", "patient_id", "items")
    items = data["items"]
    if not isinstance(items, list) or not items:
        abort(400, description="items must be a non-empty array.")
    try:
        doctor_id = int(data["doctor_id"])
        patient_id = int(data["patient_id"])
        refill_days = int(data.get("refill_interval_days", 30))
    except (TypeError, ValueError):
        abort(400, description="doctor_id, patient_id, and refill_interval_days must be integers.")
    if not 1 <= refill_days <= 365:
        abort(400, description="refill_interval_days must be between 1 and 365.")

    normalized_items = []
    seen_product_ids = set()
    for item in items:
        if not isinstance(item, dict):
            abort(400, description="Each prescription item must be an object.")
        required(item, "product_id", "quantity", "instructions")
        try:
            product_id = int(item["product_id"])
            quantity = int(item["quantity"])
        except (TypeError, ValueError):
            abort(400, description="Each product_id and quantity must be an integer.")
        if quantity <= 0:
            abort(400, description="Prescription quantities must be positive.")
        if product_id in seen_product_ids:
            abort(400, description="A product may only appear once in a prescription.")
        seen_product_ids.add(product_id)
        normalized_items.append((product_id, quantity, str(item["instructions"]).strip()))

    token = secrets.token_urlsafe(32)
    db = get_db()
    with db:
        cursor = db.execute(
            """INSERT INTO prescriptions (qr_token, doctor_id, patient_id, refill_interval_days)
               VALUES (?, ?, ?, ?)""",
            (token, doctor_id, patient_id, refill_days),
        )
        prescription_id = cursor.lastrowid
        db.executemany(
            """INSERT INTO prescription_items
               (prescription_id, product_id, quantity, instructions) VALUES (?, ?, ?, ?)""",
            [(prescription_id, product_id, quantity, instructions)
             for product_id, quantity, instructions in normalized_items],
        )
        due_at = db.execute(
            "SELECT datetime('now', ?)", (f"+{refill_days} days",)
        ).fetchone()[0]
        db.execute(
            "INSERT INTO refill_reminders (prescription_id, due_at) VALUES (?, ?)",
            (prescription_id, due_at),
        )

    patient_url = request.url_root.rstrip("/") + url_for("patient_page", token=token)
    return jsonify(
        id=prescription_id,
        status="issued",
        qr_token=token,
        patient_url=patient_url,
        qr_image_url=url_for("prescription_qr", token=token, _external=True),
        refill_due_at=due_at,
    ), 201


def prescription_view(token):
    db = get_db()
    prescription = db.execute(
        """SELECT p.id, p.qr_token, p.status, p.issued_at, p.fulfilled_at,
                  p.refill_interval_days, d.full_name AS doctor_name,
                  pa.full_name AS patient_name
           FROM prescriptions p
           JOIN doctors d ON d.id = p.doctor_id
           JOIN patients pa ON pa.id = p.patient_id
           WHERE p.qr_token = ?""",
        (token,),
    ).fetchone()
    if prescription is None:
        abort(404, description="Prescription not found.")

    items = db.execute(
        """SELECT pi.product_id, pr.name, pr.brand, pi.quantity, pi.instructions
           FROM prescription_items pi JOIN products pr ON pr.id = pi.product_id
           WHERE pi.prescription_id = ? ORDER BY pr.name""",
        (prescription["id"],),
    ).fetchall()
    store_rows = db.execute(
        """SELECT s.id, s.name, s.address, s.phone, s.latitude, s.longitude,
                  pi.product_id, pr.name AS product_name, pi.quantity AS required_quantity,
                  COALESCE(i.stock_quantity, 0) AS stock_quantity
           FROM stores s
           CROSS JOIN prescription_items pi
           JOIN products pr ON pr.id = pi.product_id
           LEFT JOIN inventory i ON i.store_id = s.id AND i.product_id = pi.product_id
           WHERE s.is_partner = 1 AND pi.prescription_id = ?
           ORDER BY s.name, pr.name""",
        (prescription["id"],),
    ).fetchall()

    stores = {}
    latitude = optional_coordinate(request.args.get("lat"), "lat")
    longitude = optional_coordinate(request.args.get("lng"), "lng")
    for row in store_rows:
        store = stores.setdefault(row["id"], {
            "id": row["id"], "name": row["name"], "address": row["address"],
            "phone": row["phone"], "items": [], "can_fulfill": True,
        })
        stock = row["stock_quantity"]
        store["items"].append({
            "product_id": row["product_id"],
            "name": row["product_name"],
            "required_quantity": row["required_quantity"],
            "stock_quantity": stock,
            "available": stock >= row["required_quantity"],
        })
        store["can_fulfill"] = store["can_fulfill"] and stock >= row["required_quantity"]
        if latitude is not None and longitude is not None and row["latitude"] is not None and row["longitude"] is not None:
            store["distance_km"] = round(
                distance_km(latitude, longitude, row["latitude"], row["longitude"]), 2
            )

    stores = list(stores.values())
    stores.sort(key=lambda store: (
        store.get("distance_km", math.inf) if latitude is not None and longitude is not None else 0,
        not store["can_fulfill"],
        store["name"].lower(),
    ))
    patient_name = prescription["patient_name"].split()[0]
    result = {
        "id": prescription["id"],
        "status": prescription["status"],
        "patient_first_name": patient_name,
        "doctor_name": prescription["doctor_name"],
        "issued_at": prescription["issued_at"],
        "fulfilled_at": prescription["fulfilled_at"],
        "refill_interval_days": prescription["refill_interval_days"],
        "items": as_dicts(items),
        "stores": stores,
    }
    return result


@app.get("/api/prescriptions/<token>")
def patient_prescription(token):
    return jsonify(prescription_view(token))


@app.get("/api/verify/<token>")
def verify_prescription(token):
    result = prescription_view(token)
    return jsonify(valid=result["status"] in ("issued", "fulfilled"), **result)


@app.get("/api/prescriptions/<token>/qr.png")
def prescription_qr(token):
    db = get_db()
    exists = db.execute("SELECT 1 FROM prescriptions WHERE qr_token = ?", (token,)).fetchone()
    if exists is None:
        abort(404, description="Prescription not found.")
    patient_url = request.url_root.rstrip("/") + url_for("patient_page", token=token)
    image = qrcode.make(patient_url)
    output = BytesIO()
    image.save(output, format="PNG")
    output.seek(0)
    response = send_file(output, mimetype="image/png", download_name="prescription-qr.png")
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/api/prescriptions")
def list_prescriptions():
    status = request.args.get("status")
    db = get_db()
    if status:
        rows = db.execute(
            """SELECT p.id, p.status, p.issued_at, p.fulfilled_at,
                      d.full_name AS doctor_name, pa.full_name AS patient_name
               FROM prescriptions p JOIN doctors d ON d.id = p.doctor_id
               JOIN patients pa ON pa.id = p.patient_id
               WHERE p.status = ? ORDER BY p.issued_at DESC""",
            (status,),
        ).fetchall()
    else:
        rows = db.execute(
            """SELECT p.id, p.status, p.issued_at, p.fulfilled_at,
                      d.full_name AS doctor_name, pa.full_name AS patient_name
               FROM prescriptions p JOIN doctors d ON d.id = p.doctor_id
               JOIN patients pa ON pa.id = p.patient_id
               ORDER BY p.issued_at DESC"""
        ).fetchall()
    return jsonify(prescriptions=as_dicts(rows))


@app.post("/api/prescriptions/<int:prescription_id>/fulfill")
def fulfill_prescription(prescription_id):
    data = payload()
    required(data, "qr_token", "store_id")
    try:
        store_id = int(data["store_id"])
    except (TypeError, ValueError):
        abort(400, description="store_id must be an integer.")

    db = get_db()
    with db:
        prescription = db.execute(
            """SELECT id, status, refill_interval_days FROM prescriptions
               WHERE id = ? AND qr_token = ?""",
            (prescription_id, data["qr_token"]),
        ).fetchone()
        if prescription is None:
            abort(404, description="Prescription or QR token not found.")
        if prescription["status"] != "issued":
            abort(409, description="Only issued prescriptions can be fulfilled.")

        store = db.execute(
            "SELECT id FROM stores WHERE id = ? AND is_partner = 1", (store_id,)
        ).fetchone()
        if store is None:
            abort(404, description="Partner store not found.")

        items = db.execute(
            """SELECT product_id, quantity FROM prescription_items
               WHERE prescription_id = ?""",
            (prescription_id,),
        ).fetchall()
        for item in items:
            inventory = db.execute(
                "SELECT stock_quantity FROM inventory WHERE store_id = ? AND product_id = ?",
                (store_id, item["product_id"]),
            ).fetchone()
            available = inventory["stock_quantity"] if inventory else 0
            if available < item["quantity"]:
                abort(409, description=f"Insufficient stock for product {item['product_id']}.")

        points = sum(item["quantity"] for item in items)
        for item in items:
            db.execute(
                """UPDATE inventory SET stock_quantity = stock_quantity - ?,
                          updated_at = CURRENT_TIMESTAMP
                   WHERE store_id = ? AND product_id = ?""",
                (item["quantity"], store_id, item["product_id"]),
            )
        db.execute(
            "UPDATE prescriptions SET status = 'fulfilled', fulfilled_at = CURRENT_TIMESTAMP WHERE id = ?",
            (prescription_id,),
        )
        fulfillment = db.execute(
            """INSERT INTO fulfillments (prescription_id, store_id, reward_points)
               VALUES (?, ?, ?)""",
            (prescription_id, store_id, points),
        )
        db.execute(
            "INSERT INTO loyalty_transactions (store_id, fulfillment_id, points) VALUES (?, ?, ?)",
            (store_id, fulfillment.lastrowid, points),
        )

    return jsonify(
        status="fulfilled",
        prescription_id=prescription_id,
        store_id=store_id,
        reward_points=points,
        points_rule="1 point per prescribed unit",
    )


@app.get("/api/refills")
def list_refills():
    status = request.args.get("status", "scheduled")
    rows = get_db().execute(
        """SELECT r.id, r.prescription_id, r.due_at, r.status,
                  pa.full_name AS patient_name, pa.phone AS patient_phone,
                  GROUP_CONCAT(pr.name, ', ') AS products
           FROM refill_reminders r
           JOIN prescriptions p ON p.id = r.prescription_id
           JOIN patients pa ON pa.id = p.patient_id
           JOIN prescription_items pi ON pi.prescription_id = p.id
           JOIN products pr ON pr.id = pi.product_id
           WHERE r.status = ? GROUP BY r.id ORDER BY r.due_at""",
        (status,),
    ).fetchall()
    return jsonify(refills=as_dicts(rows))


@app.get("/api/dashboard")
def dashboard():
    db = get_db()
    totals = db.execute(
        """SELECT COUNT(*) AS total,
                  SUM(CASE WHEN status = 'fulfilled' THEN 1 ELSE 0 END) AS fulfilled
           FROM prescriptions"""
    ).fetchone()
    total = totals["total"]
    fulfilled = totals["fulfilled"] or 0
    top_products = db.execute(
        """SELECT pr.id, pr.name, pr.brand, SUM(pi.quantity) AS units_prescribed
           FROM prescription_items pi JOIN products pr ON pr.id = pi.product_id
           GROUP BY pr.id ORDER BY units_prescribed DESC, pr.name LIMIT 5"""
    ).fetchall()
    store_points = db.execute(
        """SELECT s.id AS store_id, s.name AS store_name,
                  COALESCE(SUM(lt.points), 0) AS points
           FROM stores s LEFT JOIN loyalty_transactions lt ON lt.store_id = s.id
           GROUP BY s.id ORDER BY points DESC, s.name"""
    ).fetchall()
    return jsonify(
        total_prescriptions=total,
        fulfilled_prescriptions=fulfilled,
        fulfillment_rate=round(fulfilled / total * 100, 1) if total else 0,
        top_products=as_dicts(top_products),
        shopkeeper_points=as_dicts(store_points),
    )


if __name__ == "__main__":
    app.run(debug=True)