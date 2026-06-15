import os
import pytest
from unittest import mock
from bson import ObjectId
from app.core.config import Settings
from app.services.viewer_service import viewer_service

def test_production_config_disables_simulation():
    # Test setting APP_ENV to "production" forces ENABLE_DEV_JOB_SIMULATION to False
    settings = Settings(APP_ENV="production", ENABLE_DEV_JOB_SIMULATION=True)
    assert settings.ENABLE_DEV_JOB_SIMULATION is False

    # Test in development it stays True if specified
    settings_dev = Settings(APP_ENV="development", ENABLE_DEV_JOB_SIMULATION=True)
    assert settings_dev.ENABLE_DEV_JOB_SIMULATION is True

@pytest.mark.asyncio
async def test_get_pose_metadata_with_molecule_properties():
    # Setup mock returns
    mock_workspace_membership = {"role": "owner"}
    mock_project = {"_id": ObjectId(), "workspace_id": ObjectId()}
    
    mock_result_id = str(ObjectId())
    mock_molecule_id = str(ObjectId())
    mock_pose_file_id = str(ObjectId())
    
    mock_docking_result = {
        "_id": ObjectId(mock_result_id),
        "project_id": mock_project["_id"],
        "molecule_id": ObjectId(mock_molecule_id),
        "target_id": ObjectId(),
        "pose_file_id": mock_pose_file_id,
        "binding_energy": -9.2
    }
    
    mock_file_metadata = {
        "original_filename": "pose_EGFR.sdf",
        "metadata": {}
    }
    
    mock_molecule = {
        "_id": ObjectId(mock_molecule_id),
        "mw": 421.4,
        "logp": 3.82,
        "qed": 0.88,
        "tpsa": 75.3
    }
    
    with mock.patch("app.repositories.workspace_repository.workspace_repository.get_membership", new_callable=mock.AsyncMock) as mock_membership_get, \
         mock.patch("app.repositories.project_repository.project_repository.get_project_by_id", new_callable=mock.AsyncMock) as mock_project_get, \
         mock.patch("app.repositories.docking_result_repository.docking_result_repository.get_result_by_id", new_callable=mock.AsyncMock) as mock_result_get, \
         mock.patch("app.repositories.file_metadata_repository.file_metadata_repository.get_metadata_by_file_id", new_callable=mock.AsyncMock) as mock_file_get, \
         mock.patch("app.repositories.molecule_repository.molecule_repository.get_molecule_by_id", new_callable=mock.AsyncMock) as mock_mol_get:
         
        mock_membership_get.return_value = mock_workspace_membership
        mock_project_get.return_value = mock_project
        mock_result_get.return_value = mock_docking_result
        mock_file_get.return_value = mock_file_metadata
        mock_mol_get.return_value = mock_molecule
        
        # Invoke get_pose_metadata
        res = await viewer_service.get_pose_metadata(
            project_id=str(mock_project["_id"]),
            result_id=mock_result_id,
            user_id="user_123"
        )
        
        assert res["result_id"] == mock_result_id
        assert res["molecule_properties"]["mw"] == 421.4
        assert res["molecule_properties"]["logp"] == 3.82
        assert res["molecule_properties"]["qed"] == 0.88
        assert res["molecule_properties"]["tpsa"] == 75.3
        assert res["scores"]["binding_affinity_kcal_mol"] == -9.2
