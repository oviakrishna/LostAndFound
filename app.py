import os
from werkzeug.utils import secure_filename
from flask import Flask, request, jsonify, render_template
from flask_pymongo import PyMongo
from flask_cors import CORS
from bson.objectid import ObjectId
from datetime import datetime, timedelta
import smtplib
from email.message import EmailMessage
from flask import send_from_directory

def restrict_to_localhost():
    allowed_ips = ["127.0.0.1", "::1"]
    if request.remote_addr not in allowed_ips:
        return jsonify({"error": "Access denied"}), 403

app = Flask(__name__)
CORS(app)

@app.route("/")
def home():
    return render_template("index.html")

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# ================= MONGODB =================
app.config["MONGO_URI"] = "mongodb+srv://ovia_krishna:ovia123@lostandfound.prc7ls9.mongodb.net/lost_found_db?retryWrites=true&w=majority"
mongo = PyMongo(app)

# ================= EMAIL CONFIG =================
EMAIL_ADDRESS = "lostandfoundmanagement82@gmail.com"
EMAIL_PASSWORD = "byvhettbenmgahdj"

def send_email(to, subject, body):
    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = EMAIL_ADDRESS
        msg["To"] = to
        msg.set_content(body)

        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            server.send_message(msg)

        print("Email sent to:", to)

    except Exception as e:
        print("Email error:", e)

# ================= ROUTES =================


# Get all items (except donated)
@app.route("/items", methods=["GET"])
def get_items():
    try:
        # Move items older than 1 day to DONATED
        one_day_ago = datetime.utcnow() - timedelta(days=1)

        mongo.db.items.update_many(
            {
                "status": "FOUND",
                "createdAt": {"$lte": one_day_ago}
            },
            {"$set": {"status": "DONATED"}}
        )

        # Fetch non-donated items
        items = mongo.db.items.find({"status": {"$ne": "DONATED"}})

        result = []
        for i in items:
            result.append({
                "_id": str(i["_id"]),
                "name": i.get("name", ""),
                "category": i.get("category", "-"),
                "publicDescription": i.get("publicDescription", ""),
                "status": i.get("status", "FOUND")
            })

        return jsonify(result)

    except Exception as e:
        print("Fetch items error:", e)
        return jsonify({"error": "Failed to fetch items"}), 500


# Add found item
@app.route("/found", methods=["POST"])
def add_found():
    try:
        data = request.json

        mongo.db.items.insert_one({
            "name": data.get("name"),
            "category": data.get("category"),
            "publicDescription": data.get("publicDescription"),
            "privateDescription": data.get("privateDescription"),
            "dateFound": data.get("dateFound"),
            "status": "FOUND",
            "createdAt": datetime.utcnow()
        })

        return jsonify({"success": True})

    except Exception as e:
        print("Add item error:", e)
        return jsonify({"success": False}), 500


# Submit claim
@app.route("/claim", methods=["POST"])
def submit_claim():
    try:
        item_id = request.form.get("itemId")
        proof = request.form.get("proof")
        email = request.form.get("email")
        image = request.files.get("image")

        if not item_id or not proof or not email:
            return jsonify({"error": "Missing required fields"}), 400

        item = mongo.db.items.find_one({"_id": ObjectId(item_id)})

        if not item:
            return jsonify({"error": "Item not found"}), 404

        if not item.get("privateDescription") or \
           proof.lower() not in item["privateDescription"].lower():
            return jsonify({"error": "Proof does not match item details"}), 400

        image_filename = None

        if image:
            filename = secure_filename(image.filename)
            image_filename = f"{datetime.utcnow().timestamp()}_{filename}"
            image.save(os.path.join(app.config["UPLOAD_FOLDER"], image_filename))

        mongo.db.claims.insert_one({
            "itemId": ObjectId(item_id),
            "proof": proof,
            "email": email,
            "image": image_filename,
            "status": "PENDING",
            "createdAt": datetime.utcnow()
        })

        mongo.db.items.update_one(
            {"_id": ObjectId(item_id)},
            {"$set": {"status": "PENDING"}}
        )

        return jsonify({"success": True})

    except Exception as e:
        print("Claim error:", e)
        return jsonify({"error": "Server error"}), 500

#Image Upload
@app.route("/uploads/<filename>")
def uploaded_file(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)

# Admin view pending claims
@app.route("/admin/claims", methods=["GET"])
def view_claims():
    restricted = restrict_to_localhost()
    if restricted:
        return restricted
    try:
        claims = mongo.db.claims.find({"status": "PENDING"})

        result = []
        for c in claims:
            item = mongo.db.items.find_one({"_id": c["itemId"]})
            result.append({
    "_id": str(c["_id"]),
    "email": c.get("email"),
    "proof": c.get("proof"),
    "image": c.get("image"),
    "itemId": {
        "_id": str(item["_id"]) if item else "",
        "name": item.get("name") if item else ""
    }
})
        return jsonify(result)

    except Exception as e:
        print("Admin claims error:", e)
        return jsonify({"error": "Failed to fetch claims"}), 500


# Approve claim
@app.route("/admin/claim/approve/<claim_id>", methods=["POST"])
def approve_claim(claim_id):
    restricted = restrict_to_localhost()
    if restricted:
        return restricted
    try:
        claim = mongo.db.claims.find_one({"_id": ObjectId(claim_id)})

        if not claim:
            return jsonify({"success": False}), 404

        mongo.db.claims.update_one(
            {"_id": ObjectId(claim_id)},
            {"$set": {"status": "APPROVED"}}
        )

        mongo.db.items.update_one(
            {"_id": claim["itemId"]},
            {"$set": {"status": "CLAIMED"}}
        )

        item = mongo.db.items.find_one({"_id": claim["itemId"]})

        send_email(
            claim["email"],
            "Claim Approved - Lost & Found",
            f"""
Hello,

Good news!

Your claim for "{item.get('name')}" has been APPROVED.

Please contact the office to collect your item.

Thank you,
Lost & Found Team
"""
        )

        return jsonify({"success": True})

    except Exception as e:
        print("Approve error:", e)
        return jsonify({"success": False}), 500


# Reject claim
@app.route("/admin/claim/reject/<claim_id>", methods=["POST"])
def reject_claim(claim_id):
    restricted = restrict_to_localhost()
    if restricted:
        return restricted
    try:
        claim = mongo.db.claims.find_one({"_id": ObjectId(claim_id)})

        if not claim:
            return jsonify({"success": False}), 404

        mongo.db.claims.update_one(
            {"_id": ObjectId(claim_id)},
            {"$set": {"status": "REJECTED"}}
        )

        mongo.db.items.update_one(
            {"_id": claim["itemId"]},
            {"$set": {"status": "FOUND"}}
        )

        item = mongo.db.items.find_one({"_id": claim["itemId"]})

        send_email(
            claim["email"],
            "Claim Rejected - Lost & Found",
            f"""
Hello,

Your claim for "{item.get('name')}" has been REJECTED.

The provided proof did not match the item details.

Thank you,
Lost & Found Team
"""
        )

        return jsonify({"success": True})

    except Exception as e:
        print("Reject error:", e)
        return jsonify({"success": False}), 500


# Donated items
@app.route("/donations", methods=["GET"])
def donations():
    try:
        items = mongo.db.items.find({"status": "DONATED"})
        result = []
        for i in items:
            i["_id"] = str(i["_id"])
            result.append(i)

        return jsonify(result)

    except Exception as e:
        print("Donation error:", e)
        return jsonify({"error": "Failed to fetch donations"}), 500
    
# ================= IMAGE ===================
@app.route("/admin/images", methods=["GET"])
def get_uploaded_images():
    restricted = restrict_to_localhost()
    if restricted:
        return restricted
    try:
        files = os.listdir(app.config["UPLOAD_FOLDER"])
        return jsonify(files)
    except Exception as e:
        print("Image list error:", e)
        return jsonify([])


# ================= SERVER =================
if __name__ == "__main__":
    app.run(port=3000, debug=True)