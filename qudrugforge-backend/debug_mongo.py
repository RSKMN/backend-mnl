import pymongo
from bson import ObjectId
client = pymongo.MongoClient('mongodb://localhost:27017')
db = client['qudrugforge_STAGING']
run_a = '6a215b6b71a3addcd13d6292'
run_b = '6a215ba871a3addcd13d62ce'
for pid in [run_a, run_b]:
    print(f'Project {pid}:')
    mols = list(db.molecules.find({'project_id': ObjectId(pid)}))
    print('  Molecules in DB:', len(mols))
    for m in mols[:3]: print('    ', m['smiles'], m.get('source'))
    docks = list(db.docking_results.find({'project_id': ObjectId(pid)}))
    print('  Docking results:', len(docks))
    for d in docks[:3]: print('    ', d.get('ligand_smiles', d.get('canonical_smiles')))
