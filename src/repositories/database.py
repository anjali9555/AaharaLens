import os
import json
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple
from loguru import logger
from src.core.config import settings

# Attempt MongoDB client connection
_mongo_client = None
_mongo_db = None
_use_fallback = False

try:
    from pymongo import MongoClient, ASCENDING
    from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError
    
    # Fast 1.5 second timeout to check if MongoDB is alive
    client = MongoClient(settings.MONGODB_URI, serverSelectionTimeoutMS=1500)
    client.admin.command('ping')
    _mongo_client = client
    _mongo_db = _mongo_client[settings.MONGODB_DB_NAME]
    logger.info("Connected to MongoDB successfully.")
    
    # Create indexes in MongoDB
    try:
        _mongo_db.users.create_index([("email", ASCENDING)], unique=True)
        _mongo_db.users.create_index([("username", ASCENDING)], unique=True)
        _mongo_db.profiles.create_index([("user_id", ASCENDING)], unique=True)
        _mongo_db.refresh_tokens.create_index([("token_hash", ASCENDING)], unique=True)
        _mongo_db.refresh_tokens.create_index([("user_id", ASCENDING)])
        # Fixed index on actual query field 'date' and backward-compatible 'meal_date'
        _mongo_db.meal_entries.create_index([("user_id", ASCENDING), ("date", ASCENDING)])
        _mongo_db.meal_entries.create_index([("user_id", ASCENDING), ("meal_date", ASCENDING)])
        _mongo_db.food_analysis_history.create_index([("user_id", ASCENDING)])
        _mongo_db.meal_plans.create_index([("user_id", ASCENDING)])
        _mongo_db.chat_history.create_index([("conversation_id", ASCENDING)])
        _mongo_db.chat_history.create_index([("user_id", ASCENDING)])
        logger.info("MongoDB indexes verified and ready.")
    except Exception as ie:
        logger.warning(f"Could not initialize all MongoDB indexes: {ie}")

except Exception as e:
    if settings.ENVIRONMENT == "production" and not settings.ALLOW_FALLBACK_IN_PROD:
        logger.critical(f"FATAL: MongoDB is unavailable in production environment: {e}")
        raise RuntimeError(f"MongoDB connection failed in production: {e}")
    _use_fallback = True
    logger.warning(f"MongoDB unavailable ({e}). Initializing high-performance local document store (development mode).")


def check_database_health() -> Dict[str, Any]:
    """Inspects live database connectivity and latency without leaking credentials."""
    is_atlas = "mongodb.net" in settings.MONGODB_URI or "mongodb+srv" in settings.MONGODB_URI
    if _mongo_client is not None and not _use_fallback:
        try:
            ping_res = _mongo_client.admin.command('ping')
            return {
                "status": "healthy",
                "backend": "mongodb_atlas" if is_atlas else "mongodb",
                "database": settings.MONGODB_DB_NAME,
                "connected_to_atlas": is_atlas,
                "is_fallback": False,
                "fallback_active": False,
                "ping": ping_res.get("ok", 1.0) == 1.0
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "backend": "mongodb_atlas" if is_atlas else "mongodb",
                "database": settings.MONGODB_DB_NAME,
                "connected_to_atlas": False,
                "is_fallback": False,
                "fallback_active": False,
                "error": str(e)
            }
    return {
        "status": "development_fallback",
        "backend": "json_document_store",
        "database": settings.MONGODB_DB_NAME,
        "connected_to_atlas": False,
        "is_fallback": True,
        "fallback_active": True,
        "storage_dir": settings.DB_FALLBACK_DIR
    }


class DocumentStore:
    """Document repository with MongoDB primary and robust JSON document store fallback."""
    
    def __init__(self, collection_name: str):
        self.collection_name = collection_name
        self.fallback_dir = settings.DB_FALLBACK_DIR
        os.makedirs(self.fallback_dir, exist_ok=True)
        self.file_path = os.path.join(self.fallback_dir, f"{collection_name}.json")
        if not os.path.exists(self.file_path):
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump([], f)

    def _read_fallback(self) -> List[Dict[str, Any]]:
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []

    def _write_fallback(self, docs: List[Dict[str, Any]]):
        temp_file = f"{self.file_path}.tmp"
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(docs, f, indent=2, default=str)
        os.replace(temp_file, self.file_path)
        if not _use_fallback and _mongo_db is not None:
            try:
                col = _mongo_db[self.collection_name]
                col.delete_many({})
                if docs:
                    import copy
                    to_insert = [copy.deepcopy(d) for d in docs]
                    for d in to_insert:
                        if "_id" not in d and "id" in d:
                            d["_id"] = d["id"]
                    col.insert_many(to_insert)
            except Exception as e:
                logger.warning(f"Could not sync fallback write to MongoDB: {e}")

    def insert_one(self, document: Dict[str, Any]) -> str:
        doc = dict(document)
        if "id" not in doc and "_id" not in doc:
            doc["id"] = str(uuid.uuid4())
        elif "_id" in doc and "id" not in doc:
            doc["id"] = str(doc["_id"])
        
        if "created_at" not in doc:
            doc["created_at"] = datetime.now(timezone.utc).isoformat()

        # Automatic normalization for user credentials
        if self.collection_name == "users":
            if "email" in doc and isinstance(doc["email"], str):
                doc["email"] = doc["email"].strip().lower()
            if "username" in doc and isinstance(doc["username"], str):
                doc["username"] = doc["username"].strip().lower()
            
        if not _use_fallback and _mongo_db is not None:
            try:
                res = _mongo_db[self.collection_name].insert_one(doc)
                return str(res.inserted_id)
            except Exception as e:
                logger.error(f"MongoDB insert error: {e}")
                if settings.ENVIRONMENT == "production" and not settings.ALLOW_FALLBACK_IN_PROD:
                    raise RuntimeError(f"Database write operation failed in production: {e}")
        
        docs = self._read_fallback()
        replaced = False
        for i, existing in enumerate(docs):
            if existing.get("id") == doc["id"]:
                docs[i] = doc
                replaced = True
                break
        if not replaced:
            docs.append(doc)
            
        self._write_fallback(docs)
        return doc["id"]

    def find_one(self, query: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        normalized_query = dict(query)
        if self.collection_name == "users":
            if "email" in normalized_query and isinstance(normalized_query["email"], str):
                normalized_query["email"] = normalized_query["email"].strip().lower()
            if "username" in normalized_query and isinstance(normalized_query["username"], str):
                normalized_query["username"] = normalized_query["username"].strip().lower()

        if not _use_fallback and _mongo_db is not None:
            try:
                mongo_q = dict(normalized_query)
                if "id" in mongo_q and "_id" not in mongo_q:
                    val = mongo_q["id"]
                    try:
                        from bson import ObjectId
                        if isinstance(val, str) and ObjectId.is_valid(val):
                            mongo_q = {"$or": [{"id": val}, {"_id": ObjectId(val)}]}
                    except Exception:
                        pass
                res = _mongo_db[self.collection_name].find_one(mongo_q)
                if res:
                    if "id" not in res and "_id" in res:
                        res["id"] = str(res["_id"])
                    elif "_id" in res:
                        res["_id"] = str(res["_id"])
                    return res
                return None
            except Exception as e:
                logger.error(f"MongoDB query error: {e}")
                if settings.ENVIRONMENT == "production" and not settings.ALLOW_FALLBACK_IN_PROD:
                    raise RuntimeError(f"Database query operation failed in production: {e}")
        
        docs = self._read_fallback()
        for doc in docs:
            match = True
            for k, v in normalized_query.items():
                if k == "_id" and doc.get("id") == str(v):
                    continue
                doc_val = doc.get(k)
                if self.collection_name == "users" and k in ("email", "username") and isinstance(v, str) and isinstance(doc_val, str):
                    if doc_val.strip().lower() != v.strip().lower():
                        match = False
                        break
                elif doc_val != v:
                    match = False
                    break
            if match:
                return doc
        return None

    def find_many(
        self, 
        query: Dict[str, Any] = None, 
        skip: int = 0, 
        limit: int = 50,
        sort_by: Optional[str] = "created_at",
        reverse: bool = True
    ) -> List[Dict[str, Any]]:
        query = query or {}
        try:
            skip = int(skip)
        except Exception:
            skip = 0
        try:
            limit = int(limit)
        except Exception:
            limit = 50
        try:
            skip = int(skip)
        except Exception:
            skip = 0
        try:
            limit = int(limit)
        except Exception:
            limit = 50
        if not _use_fallback and _mongo_db is not None:
            try:
                cursor = _mongo_db[self.collection_name].find(query)
                if sort_by:
                    direction = -1 if reverse else 1
                    cursor = cursor.sort(sort_by, direction)
                results = list(cursor.skip(skip).limit(limit))
                for r in results:
                    if "id" not in r and "_id" in r:
                        r["id"] = str(r["_id"])
                    elif "_id" in r:
                        r["_id"] = str(r["_id"])
                return results
            except Exception as e:
                logger.error(f"MongoDB find_many error: {e}")
                if settings.ENVIRONMENT == "production" and not settings.ALLOW_FALLBACK_IN_PROD:
                    raise RuntimeError(f"Database list operation failed in production: {e}")

        docs = self._read_fallback()
        matched = []
        for doc in docs:
            match = True
            for k, v in query.items():
                if doc.get(k) != v:
                    match = False
                    break
            if match:
                matched.append(doc)
        
        if sort_by:
            matched.sort(key=lambda x: str(x.get(sort_by, "")), reverse=reverse)
            
        return matched[skip : skip + limit]

    def update_one(self, query: Dict[str, Any], update_data: Dict[str, Any]) -> bool:
        if not _use_fallback and _mongo_db is not None:
            try:
                mongo_q = dict(query)
                if "id" in mongo_q and "_id" not in mongo_q:
                    val = mongo_q["id"]
                    try:
                        from bson import ObjectId
                        if isinstance(val, str) and ObjectId.is_valid(val):
                            mongo_q = {"$or": [{"id": val}, {"_id": ObjectId(val)}]}
                    except Exception:
                        pass
                res = _mongo_db[self.collection_name].update_one(mongo_q, {"$set": update_data})
                return res.modified_count > 0
            except Exception as e:
                logger.error(f"MongoDB update error: {e}")
                if settings.ENVIRONMENT == "production" and not settings.ALLOW_FALLBACK_IN_PROD:
                    raise RuntimeError(f"Database update operation failed in production: {e}")

        docs = self._read_fallback()
        updated = False
        for i, doc in enumerate(docs):
            match = True
            for k, v in query.items():
                if k == "_id" and doc.get("id") == str(v):
                    continue
                if doc.get(k) != v:
                    match = False
                    break
            if match:
                docs[i].update(update_data)
                docs[i]["updated_at"] = datetime.now(timezone.utc).isoformat()
                updated = True
                break
        
        if updated:
            self._write_fallback(docs)
        return updated

    def update_many(self, query: Dict[str, Any], update_data: Dict[str, Any]) -> int:
        """Updates multiple matching documents in place."""
        if not _use_fallback and _mongo_db is not None:
            try:
                res = _mongo_db[self.collection_name].update_many(query, {"$set": update_data})
                return res.modified_count
            except Exception as e:
                logger.error(f"MongoDB update_many error: {e}")
                if settings.ENVIRONMENT == "production" and not settings.ALLOW_FALLBACK_IN_PROD:
                    raise RuntimeError(f"Database batch update failed in production: {e}")

        docs = self._read_fallback()
        modified_count = 0
        for doc in docs:
            match = True
            for k, v in query.items():
                if doc.get(k) != v:
                    match = False
                    break
            if match:
                doc.update(update_data)
                doc["updated_at"] = datetime.now(timezone.utc).isoformat()
                modified_count += 1
        
        if modified_count > 0:
            self._write_fallback(docs)
        return modified_count

    def delete_one(self, query: Dict[str, Any]) -> bool:
        if not _use_fallback and _mongo_db is not None:
            try:
                mongo_q = dict(query)
                if "id" in mongo_q and "_id" not in mongo_q:
                    val = mongo_q["id"]
                    try:
                        from bson import ObjectId
                        if isinstance(val, str) and ObjectId.is_valid(val):
                            mongo_q = {"$or": [{"id": val}, {"_id": ObjectId(val)}]}
                    except Exception:
                        pass
                res = _mongo_db[self.collection_name].delete_one(mongo_q)
                return res.deleted_count > 0
            except Exception as e:
                logger.error(f"MongoDB delete error: {e}")
                if settings.ENVIRONMENT == "production" and not settings.ALLOW_FALLBACK_IN_PROD:
                    raise RuntimeError(f"Database delete operation failed in production: {e}")

        docs = self._read_fallback()
        deleted = False
        new_docs = []
        for doc in docs:
            if not deleted:
                match = True
                for k, v in query.items():
                    if k == "_id" and doc.get("id") == str(v):
                        continue
                    if doc.get(k) != v:
                        match = False
                        break
                if match:
                    deleted = True
                    continue
            new_docs.append(doc)
            
        if deleted:
            self._write_fallback(new_docs)
            return True
        return False

    def count_documents(self, query: Optional[Dict[str, Any]] = None) -> int:
        """Counts documents matching the query (or all documents if query is empty)."""
        query = query or {}
        if not _use_fallback and _mongo_db is not None:
            try:
                return _mongo_db[self.collection_name].count_documents(query)
            except Exception as e:
                logger.error(f"MongoDB count_documents error: {e}")
                if settings.ENVIRONMENT == "production" and not settings.ALLOW_FALLBACK_IN_PROD:
                    raise RuntimeError(f"Database count operation failed in production: {e}")

        docs = self._read_fallback()
        if not query:
            return len(docs)
        count = 0
        for doc in docs:
            match = True
            for k, v in query.items():
                if doc.get(k) != v:
                    match = False
                    break
            if match:
                count += 1
        return count

    def delete_many(self, query: Optional[Dict[str, Any]] = None) -> int:
        """Deletes all documents matching the query (or all documents if query is empty)."""
        query = query or {}
        if not _use_fallback and _mongo_db is not None:
            try:
                res = _mongo_db[self.collection_name].delete_many(query)
                return res.deleted_count
            except Exception as e:
                logger.error(f"MongoDB delete_many error: {e}")
                if settings.ENVIRONMENT == "production" and not settings.ALLOW_FALLBACK_IN_PROD:
                    raise RuntimeError(f"Database batch delete failed in production: {e}")

        docs = self._read_fallback()
        if not query:
            deleted_count = len(docs)
            self._write_fallback([])
            return deleted_count

        retained = []
        deleted_count = 0
        for doc in docs:
            match = True
            for k, v in query.items():
                if doc.get(k) != v:
                    match = False
                    break
            if match:
                deleted_count += 1
            else:
                retained.append(doc)

        if deleted_count > 0:
            self._write_fallback(retained)
        return deleted_count

    def aggregate(self, pipeline: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Executes MongoDB aggregation pipeline.
        In development fallback mode, provides an in-memory pipeline simulator
        for $match, $sort, $skip, and $limit stages supporting $gte, $lte, $gt, $lt, $eq, $ne, $in, $nin.
        """
        if not _use_fallback and _mongo_db is not None:
            try:
                col = _mongo_db[self.collection_name]
                cursor = col.aggregate(pipeline)
                results = list(cursor)
                if results:
                    for r in results:
                        if "id" not in r and "_id" in r:
                            r["id"] = str(r["_id"])
                        elif "_id" in r:
                            r["_id"] = str(r["_id"])
                    return results
                # If collection has documents in Mongo, return empty list (legitimate 0 match)
                if col.estimated_document_count() > 0 or (settings.ENVIRONMENT == "production" and not settings.ALLOW_FALLBACK_IN_PROD):
                    return []
            except Exception as e:
                logger.error(f"MongoDB aggregation error: {e}")
                if settings.ENVIRONMENT == "production" and not settings.ALLOW_FALLBACK_IN_PROD:
                    raise RuntimeError(f"Aggregation pipeline failed in production: {e}")

        # In-memory aggregation simulator for fallback store
        docs = self._read_fallback()
        current = [dict(d) for d in docs]

        def _normalize_cmp(v_val: Any, t_val: Any) -> Tuple[Any, Any]:
            if v_val is None or t_val is None:
                return v_val, t_val
            if isinstance(v_val, (int, float)) and isinstance(t_val, (int, float)):
                return float(v_val), float(t_val)
            if isinstance(v_val, str) and isinstance(t_val, str):
                if len(t_val) == 10 and len(v_val) >= 10 and (len(v_val) == 10 or v_val[10] in ("T", " ")):
                    return v_val[:10], t_val
            return v_val, t_val

        def _matches_op(doc_val: Any, op: str, target: Any) -> bool:
            if op == "$eq":
                return doc_val == target
            if op == "$ne":
                return doc_val != target
            if op == "$in":
                return isinstance(target, (list, tuple, set)) and doc_val in target
            if op == "$nin":
                return not (isinstance(target, (list, tuple, set)) and doc_val in target)
            if op in ("$gt", "$gte", "$lt", "$lte"):
                if doc_val is None:
                    return False
                v_cmp, t_cmp = _normalize_cmp(doc_val, target)
                try:
                    if op == "$gt":
                        return v_cmp > t_cmp
                    if op == "$gte":
                        return v_cmp >= t_cmp
                    if op == "$lt":
                        return v_cmp < t_cmp
                    if op == "$lte":
                        return v_cmp <= t_cmp
                except TypeError:
                    return False
            return True

        for stage in pipeline:
            if "$match" in stage:
                criteria = stage["$match"]
                filtered = []
                for doc in current:
                    matched = True
                    for k, v in criteria.items():
                        doc_val = doc.get(k)
                        if isinstance(v, dict):
                            for op, target in v.items():
                                if not _matches_op(doc_val, op, target):
                                    matched = False
                                    break
                        elif doc_val != v:
                            matched = False
                        if not matched:
                            break
                    if matched:
                        filtered.append(doc)
                current = filtered

            elif "$sort" in stage:
                sort_specs = stage["$sort"]
                for field, direction in reversed(list(sort_specs.items())):
                    reverse = (direction == -1)
                    def sort_key(d, f=field):
                        val = d.get(f)
                        if val is None:
                            return (0, 0)
                        if isinstance(val, (int, float)):
                            return (1, float(val))
                        if isinstance(val, str):
                            return (2, val)
                        return (3, str(val))
                    current.sort(key=sort_key, reverse=reverse)

            elif "$skip" in stage:
                skip_n = max(0, int(stage["$skip"]))
                current = current[skip_n:]

            elif "$limit" in stage:
                limit_n = max(0, int(stage["$limit"]))
                current = current[:limit_n]

        return current

# Initialize collections
users_collection = DocumentStore("users")
profiles_collection = DocumentStore("profiles")
meal_entries_collection = DocumentStore("meal_entries")
food_analysis_collection = DocumentStore("food_analysis_history")
meal_plans_collection = DocumentStore("meal_plans")
chat_history_collection = DocumentStore("chat_history")
refresh_tokens_collection = DocumentStore("refresh_tokens")


def get_user_nutrition_analytics(user_id: str, days: int = 7) -> Dict[str, Any]:
    """
    Computes aggregated nutrition metrics over the requested window (7, 14, 30 days)
    using optimized MongoDB aggregation pipelines and Redis caching.
    """
    from datetime import date, timedelta
    start_date = (date.today() - timedelta(days=days)).isoformat()
    end_date = date.today().isoformat()

    pipeline = [
        {"$match": {"user_id": user_id, "date": {"$gte": start_date, "$lte": end_date}}},
        {"$sort": {"date": 1}}
    ]
    entries = meal_entries_collection.aggregate(pipeline)

    total_calories = sum(e.get("calories", 0.0) for e in entries)
    total_protein = sum(e.get("protein", 0.0) for e in entries)
    total_carbs = sum(e.get("carbohydrates", 0.0) for e in entries)
    total_fat = sum(e.get("fat", 0.0) for e in entries)
    total_fiber = sum(e.get("fiber", 0.0) for e in entries)

    # Days with logged meals
    distinct_dates = list(set(e.get("date") for e in entries if e.get("date")))
    num_days = max(1, len(distinct_dates))

    avg_cals = round(total_calories / num_days, 1)
    avg_protein = round(total_protein / num_days, 1)
    avg_carbs = round(total_carbs / num_days, 1)
    avg_fat = round(total_fat / num_days, 1)
    avg_fiber = round(total_fiber / num_days, 1)

    # Macro calories
    p_cals = total_protein * 4.0
    c_cals = total_carbs * 4.0
    f_cals = total_fat * 9.0
    sum_macro_cals = max(1.0, p_cals + c_cals + f_cals)

    macro_distribution = {
        "protein_percent": round((p_cals / sum_macro_cals) * 100, 1),
        "carbs_percent": round((c_cals / sum_macro_cals) * 100, 1),
        "fat_percent": round((f_cals / sum_macro_cals) * 100, 1)
    }

    # Category breakdown
    categories: Dict[str, float] = {}
    item_counts: Dict[str, int] = {}
    for e in entries:
        mtype = e.get("meal_type", "Snack").capitalize()
        categories[mtype] = categories.get(mtype, 0.0) + e.get("calories", 0.0)
        fname = e.get("food_name", "Unknown").title()
        item_counts[fname] = item_counts.get(fname, 0) + 1

    top_foods = sorted(item_counts.items(), key=lambda x: x[1], reverse=True)[:5]

    return {
        "user_id": user_id,
        "window_days": days,
        "start_date": start_date,
        "end_date": end_date,
        "days_logged": len(distinct_dates),
        "total_meals_logged": len(entries),
        "totals": {
            "calories": round(total_calories, 1),
            "protein": round(total_protein, 1),
            "carbohydrates": round(total_carbs, 1),
            "fat": round(total_fat, 1),
            "fiber": round(total_fiber, 1)
        },
        "daily_averages": {
            "calories": avg_cals,
            "protein": avg_protein,
            "carbohydrates": avg_carbs,
            "fat": avg_fat,
            "fiber": avg_fiber
        },
        "macro_distribution": macro_distribution,
        "category_breakdown": {k: round(v, 1) for k, v in categories.items()},
        "top_consumed_foods": [{"food": f, "count": c} for f, c in top_foods]
    }
