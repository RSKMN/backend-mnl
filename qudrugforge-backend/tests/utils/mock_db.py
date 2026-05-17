import copy
from bson import ObjectId
from collections import defaultdict
from app.utils.datetime import utc_now

class InsertOneResult:
    def __init__(self, inserted_id):
        self.inserted_id = inserted_id

class InsertManyResult:
    def __init__(self, inserted_ids):
        self.inserted_ids = inserted_ids

class UpdateResult:
    def __init__(self, modified_count):
        self.modified_count = modified_count
        self.raw_result = {"n": modified_count, "nModified": modified_count, "ok": 1.0}

class DeleteResult:
    def __init__(self, deleted_count):
        self.deleted_count = deleted_count

def get_nested_val(doc, key):
    parts = key.split(".")
    curr = doc
    for p in parts:
        if isinstance(curr, dict) and p in curr:
            curr = curr[p]
        else:
            return None
    return curr

def set_nested_val(doc, key, value):
    parts = key.split(".")
    curr = doc
    for p in parts[:-1]:
        if p not in curr or not isinstance(curr[p], dict):
            curr[p] = {}
        curr = curr[p]
    curr[parts[-1]] = value

def push_nested_val(doc, key, value):
    parts = key.split(".")
    curr = doc
    for p in parts[:-1]:
        if p not in curr or not isinstance(curr[p], dict):
            curr[p] = {}
        curr = curr[p]
    target_list = curr.get(parts[-1])
    if not isinstance(target_list, list):
        target_list = []
        curr[parts[-1]] = target_list
    target_list.append(value)

def doc_matches(doc, query):
    if not query:
        return True
    for key, value in query.items():
        if key == "$or":
            if not any(doc_matches(doc, q) for q in value):
                return False
            continue
        if key == "$and":
            if not all(doc_matches(doc, q) for q in value):
                return False
            continue
            
        doc_val = get_nested_val(doc, key)
        if isinstance(value, dict):
            if "$in" in value:
                choices = value["$in"]
                if doc_val not in choices and not any(isinstance(doc_val, list) and x in choices for x in doc_val):
                    return False
            elif "$nin" in value:
                if doc_val in value["$nin"]:
                    return False
            elif "$gt" in value:
                if doc_val is None or doc_val <= value["$gt"]:
                    return False
            elif "$gte" in value:
                if doc_val is None or doc_val < value["$gte"]:
                    return False
            elif "$lt" in value:
                if doc_val is None or doc_val >= value["$lt"]:
                    return False
            elif "$lte" in value:
                if doc_val is None or doc_val > value["$lte"]:
                    return False
            elif "$ne" in value:
                if doc_val == value["$ne"]:
                    return False
            else:
                if doc_val != value:
                    return False
        else:
            if doc_val != value:
                return False
    return True

class MockCursor:
    def __init__(self, items):
        self._items = items
        self._skip_val = 0
        self._limit_val = None
        self._sort_keys = None

    def skip(self, n):
        self._skip_val = n
        return self

    def limit(self, n):
        self._limit_val = n
        return self

    def sort(self, key_or_list, direction=None):
        if isinstance(key_or_list, list):
            self._sort_keys = key_or_list
        else:
            self._sort_keys = [(key_or_list, direction or 1)]
        return self

    async def to_list(self, length=None):
        items = copy.deepcopy(self._items)
        
        # Apply sorting
        if self._sort_keys:
            for key, direction in reversed(self._sort_keys):
                reverse = direction < 0
                items.sort(key=lambda x: get_nested_val(x, key) or "", reverse=reverse)
                
        # Apply skip
        if self._skip_val:
            items = items[self._skip_val:]
            
        # Apply limit
        limit = length if length is not None else self._limit_val
        if limit is not None:
            items = items[:limit]
            
        return items

    def __aiter__(self):
        self._idx = self._skip_val
        self._current_items = copy.deepcopy(self._items)
        if self._sort_keys:
            for key, direction in reversed(self._sort_keys):
                reverse = direction < 0
                self._current_items.sort(key=lambda x: get_nested_val(x, key) or "", reverse=reverse)
        return self

    async def __anext__(self):
        if self._limit_val is not None and (self._idx - self._skip_val) >= self._limit_val:
            raise StopAsyncIteration
        if self._idx >= len(self._current_items):
            raise StopAsyncIteration
        val = self._current_items[self._idx]
        self._idx += 1
        return val

class MockCollection:
    def __init__(self, name, db):
        self.name = name
        self.db = db
        self._documents = {}

    async def find_one(self, filter=None, *args, **kwargs):
        for doc in self._documents.values():
            if doc_matches(doc, filter):
                return copy.deepcopy(doc)
        return None

    def find(self, filter=None, *args, **kwargs):
        matched = []
        for doc in self._documents.values():
            if doc_matches(doc, filter):
                matched.append(doc)
        return MockCursor(matched)

    async def insert_one(self, document):
        if "_id" not in document:
            document["_id"] = ObjectId()
        doc = copy.deepcopy(document)
        doc_id = doc["_id"]
        self._documents[doc_id] = doc
        return InsertOneResult(doc_id)

    async def insert_many(self, documents):
        inserted_ids = []
        for doc in documents:
            res = await self.insert_one(doc)
            inserted_ids.append(res.inserted_id)
        return InsertManyResult(inserted_ids)

    async def update_one(self, filter, update, upsert=False):
        target = None
        for doc in self._documents.values():
            if doc_matches(doc, filter):
                target = doc
                break
        
        if not target:
            if upsert:
                # Basic upsert payload creation
                new_doc = {}
                if "_id" not in new_doc:
                    new_doc["_id"] = ObjectId()
                
                # Apply filter fields to base
                for k, v in filter.items():
                    if not k.startswith("$") and "." not in k:
                        new_doc[k] = v
                
                # Apply set/push updates
                if "$set" in update:
                    for k, v in update["$set"].items():
                        set_nested_val(new_doc, k, v)
                
                self._documents[new_doc["_id"]] = new_doc
                return UpdateResult(1)
            return UpdateResult(0)

        # Apply update operators
        modified = False
        if "$set" in update:
            for k, v in update["$set"].items():
                set_nested_val(target, k, v)
            modified = True
            
        if "$push" in update:
            for k, v in update["$push"].items():
                push_nested_val(target, k, v)
            modified = True

        if "$addToSet" in update:
            for k, v in update["$addToSet"].items():
                curr = get_nested_val(target, k)
                if not isinstance(curr, list):
                    curr = []
                    set_nested_val(target, k, curr)
                if v not in curr:
                    push_nested_val(target, k, v)
            modified = True

        if modified:
            target["updated_at"] = utc_now()

        return UpdateResult(1 if modified else 0)

    async def update_many(self, filter, update, upsert=False):
        matched_count = 0
        for doc in self._documents.values():
            if doc_matches(doc, filter):
                # Apply set updates
                if "$set" in update:
                    for k, v in update["$set"].items():
                        set_nested_val(doc, k, v)
                if "$push" in update:
                    for k, v in update["$push"].items():
                        push_nested_val(doc, k, v)
                doc["updated_at"] = utc_now()
                matched_count += 1
        return UpdateResult(matched_count)

    async def delete_many(self, filter):
        to_delete = []
        for doc_id, doc in self._documents.items():
            if doc_matches(doc, filter):
                to_delete.append(doc_id)
        
        for doc_id in to_delete:
            del self._documents[doc_id]
            
        return DeleteResult(len(to_delete))

    async def delete_one(self, filter):
        target_id = None
        for doc_id, doc in self._documents.items():
            if doc_matches(doc, filter):
                target_id = doc_id
                break
        if target_id:
            del self._documents[target_id]
            return DeleteResult(1)
        return DeleteResult(0)

    async def count_documents(self, filter):
        count = 0
        for doc in self._documents.values():
            if doc_matches(doc, filter):
                count += 1
        return count

    async def create_index(self, keys, **kwargs):
        return "mock_index"

    async def bulk_write(self, operations, ordered=True, *args, **kwargs):
        modified_count = 0
        for op in operations:
            # Check for UpdateOne
            filt = getattr(op, "_filter", None)
            doc = getattr(op, "_doc", None)
            if filt is not None and doc is not None:
                res = await self.update_one(filt, doc)
                modified_count += res.modified_count
        return UpdateResult(modified_count)

    def aggregate(self, pipeline, *args, **kwargs):
        matched_docs = []
        match_stage = pipeline[0].get("$match", {})
        for doc in self._documents.values():
            if doc_matches(doc, match_stage):
                matched_docs.append(doc)
                
        group_stage = pipeline[1].get("$group", {})
        group_by = group_stage.get("_id")
        
        counts = defaultdict(int)
        if group_by == "$status":
            for doc in matched_docs:
                status = doc.get("status")
                counts[status] += 1
                
        results = []
        for status, count in counts.items():
            results.append({"_id": status, "count": count})
            
        return MockCursor(results)

    async def drop(self):
        self._documents.clear()

class MockDatabase:
    def __init__(self):
        self._collections = defaultdict(lambda: None)

    def __getitem__(self, name):
        if self._collections[name] is None:
            self._collections[name] = MockCollection(name, self)
        return self._collections[name]

    async def list_collection_names(self):
        return list(self._collections.keys())
