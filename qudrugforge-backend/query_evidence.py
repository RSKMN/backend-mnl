import os
from dotenv import load_dotenv
from pymongo import MongoClient
import json
from bson import ObjectId

class JSONEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, ObjectId):
            return str(o)
        from datetime import datetime
        if isinstance(o, datetime):
            return o.isoformat()
        return super().default(o)

def main():
    load_dotenv('.env')
    uri = os.getenv('MONGODB_URI')
    client = MongoClient(uri)
    db_name = os.getenv('MONGODB_DATABASE', 'qudrugforge_STAGING')
    db = client.get_database(db_name)

    project_id = "6a2fc96160689a672c937aed"

    collections = [
        {
            'name': 'molecules',
            'fields': {'metadata.candidate_id': 1, 'smiles': 1, 'raw.QED': 1, 'raw.novelty': 1, '_id': 0}
        },
        {
            'name': 'docking_results',
            'fields': {'compound_id': 1, 'binding_energy': 1, 'metadata.rmsd': 1, '_id': 0}
        },
        {
            'name': 'gnina_results',
            'fields': {'compound_id': 1, 'cnn_score': 1, 'cnn_affinity': 1, 'cnn_pose_score': 1, '_id': 0}
        },
        {
            'name': 'quantum_descriptors',
            'fields': {'compound_id': 1, 'qml_score': 1, 'homo_energy': 1, 'lumo_energy': 1, '_id': 0}
        },
        {
            'name': 'admet_results',
            'fields': {'compound_id': 1, 'risk_score': 1, 'properties.lipinski_violations': 1, 'properties.TPSA': 1, '_id': 0}
        },
        {
            'name': 'reports',
            'fields': {'title': 1, 'status': 1, 'report_type': 1, '_id': 0}
        }
    ]

    for col in collections:
        collection = db[col['name']]
        # check both formats
        count_str = collection.count_documents({'project_id': project_id})
        count_oid = collection.count_documents({'project_id': ObjectId(project_id)})
        
        query_filter = {'project_id': project_id} if count_str > 0 else {'project_id': ObjectId(project_id)}
        count = count_str + count_oid
        
        print(f"=== Collection: {col['name']} ===")
        print(f"Document Count: {count}")
        
        docs = list(collection.find(query_filter, col['fields']).limit(5))
        print(f"First 5 Documents (Sanitized):")
        print(json.dumps(docs, indent=2, cls=JSONEncoder))
        print('\n----------------------------------------\n')

if __name__ == '__main__':
    main()
