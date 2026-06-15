import asyncio
from motor.motor_asyncio import AsyncIOMotorClient

async def main():
    client = AsyncIOMotorClient("mongodb+srv://qudrugforge:RSKMN%40quinfosys@qudrugforge-cluster.qjzt2ri.mongodb.net/?appName=qudrugforge-cluster")
    db = client["qudrugforge_STAGING"]
    res = await db.pipeline_runs.update_many({"status": {"$in": ["queued", "running"]}}, {"$set": {"status": "cancelled"}})
    print(f"Cancelled {res.modified_count} pipelines")
    
if __name__ == "__main__":
    asyncio.run(main())
