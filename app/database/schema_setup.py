from .mongo import get_db

async def setup_mongodb_schemas():
    """
    Set up MongoDB collection validation schemas.
    """
    try:
        db = await get_db()
        
        # Sessions collection schema validation
        sessions_schema = {
            "bsonType": "object",
            "required": ["schema_version", "session_id", "doctor_id", "patient_whatsapp_number", "patient_name", "created_at", "status"],
            "properties": {
                "_id": {"bsonType": "objectId"},  # ✅ Add MongoDB's _id field
                "schema_version": {"bsonType": "int", "minimum": 1},
                "session_id": {"bsonType": "string", "minLength": 1},
                "doctor_id": {"bsonType": "string", "minLength": 1, "maxLength": 100},
                "patient_whatsapp_number": {"bsonType": "string", "minLength": 1, "maxLength": 20},
                "patient_name": {"bsonType": "string", "minLength": 1, "maxLength": 100},
                "created_at": {"bsonType": "date"},
                "updated_at": {"bsonType": "date"},
                "status": {"enum": ["active", "closed", "archived"]},
                "consultation_summary": {"bsonType": ["string", "null"]},
                "transcription": {"bsonType": ["string", "null"]},
                "follow_up_count": {"bsonType": "int", "minimum": 0},
                "request_id": {"bsonType": ["string", "null"]}
            },
            "additionalProperties": False
        }
        
        # Update collection validation
        try:
            await db.create_collection(
                "sessions",
                validator={"$jsonSchema": sessions_schema},
                validationLevel="strict",
                validationAction="error"
            )
            print("✅ Sessions collection created with schema validation")
        except Exception as e:
            if "already exists" in str(e):
                await db.command({
                    "collMod": "sessions",
                    "validator": {"$jsonSchema": sessions_schema},
                    "validationLevel": "strict",
                    "validationAction": "error"
                })
                print("✅ Sessions collection validation updated")
            else:
                raise
                
        print("🔒 MongoDB schema validation enabled")
        
    except Exception as e:
        print(f"❌ Failed to setup MongoDB schemas: {e}")
        raise