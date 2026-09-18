# config/db.py
# Provides a single shared PyMongo client so every module uses the same
# connection pool instead of opening a new connection per call.

from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.database import Database
from config.settings import MONGO_URI, OPEN5GS_DB, NWDAF_DB


_client: MongoClient | None = None


def get_client() -> MongoClient:
    """Return (and lazily create) the shared MongoClient."""
    global _client
    if _client is None:
        _client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    return _client


def get_open5gs_db() -> Database:
    return get_client()[OPEN5GS_DB]


def get_nwdaf_db() -> Database:
    return get_client()[NWDAF_DB]


def get_collection(db_name: str, collection_name: str) -> Collection:
    return get_client()[db_name][collection_name]


def ping() -> bool:
    """Return True if MongoDB is reachable."""
    try:
        get_client().admin.command("ping")
        return True
    except Exception:
        return False
