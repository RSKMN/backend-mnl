import os
from pathlib import Path
from app.core.config import settings
from app.core.exceptions import AppException

def resolve_and_validate_run_dir(run_name: str = None, source_output_dir: str = None) -> Path:
    """
    Safely resolves the run directory path under Q_AI_DRUG_OUTPUT_ROOT, preventing
    path traversal and validating that the target directory exists.
    """
    root_path = Path(settings.Q_AI_DRUG_OUTPUT_ROOT).resolve()
    
    if source_output_dir and source_output_dir.startswith("gs://"):
        import uuid
        from google.cloud import storage
        try:
            client = storage.Client()
        except:
            client = storage.Client.create_anonymous_client()
            
        parts = source_output_dir[5:].split("/", 1)
        bucket_name = parts[0]
        prefix = parts[1] if len(parts) > 1 else ""
        
        local_dir = Path(settings.LOCAL_STORAGE_ROOT) / "temp_imports" / str(uuid.uuid4())
        local_dir.mkdir(parents=True, exist_ok=True)
        
        bucket = client.bucket(bucket_name)
        blobs = bucket.list_blobs(prefix=prefix)
        for blob in blobs:
            rel_path = blob.name[len(prefix):].lstrip("/")
            dest_file = local_dir / rel_path
            dest_file.parent.mkdir(parents=True, exist_ok=True)
            try:
                blob.download_to_filename(str(dest_file))
            except:
                pass
                
        return local_dir

    if run_name:
        target_path = root_path / run_name
    elif source_output_dir:
        input_path = Path(source_output_dir)
        if input_path.is_absolute():
            if not settings.Q_AI_DRUG_IMPORT_ALLOW_ABSOLUTE_PATHS:
                raise AppException(
                    status_code=400,
                    code="Q_AI_DRUG_OUTPUT_PATH_UNSAFE",
                    message="Absolute import paths are disallowed by configuration."
                )
            target_path = input_path
        else:
            # Handle backward compatibility: strip leading 'outputs/' if it exists
            cleaned_dir = source_output_dir
            if cleaned_dir.startswith("outputs/"):
                cleaned_dir = cleaned_dir[len("outputs/"):]
            elif cleaned_dir.startswith("outputs\\"):
                cleaned_dir = cleaned_dir[len("outputs\\"):]
            target_path = root_path / cleaned_dir
    else:
        raise AppException(
            status_code=400,
            code="VALIDATION_ERROR",
            message="Either run_name or source_output_dir must be specified."
        )

    try:
        resolved_absolute = target_path.resolve()
    except Exception as e:
        raise AppException(
            status_code=400,
            code="VALIDATION_ERROR",
            message=f"Invalid output directory path: {str(e)}"
        )

    # Check path safety constraint
    is_absolute_input = source_output_dir and Path(source_output_dir).is_absolute()
    if not (is_absolute_input and settings.Q_AI_DRUG_IMPORT_ALLOW_ABSOLUTE_PATHS):
        if not str(resolved_absolute).startswith(str(root_path)):
            raise AppException(
                status_code=400,
                code="Q_AI_DRUG_OUTPUT_PATH_UNSAFE",
                message="Directory traversal attempt detected or path resides outside output root."
            )

    if not resolved_absolute.exists() or not resolved_absolute.is_dir():
        raise AppException(
            status_code=404,
            code="Q_AI_DRUG_OUTPUT_NOT_FOUND",
            message=f"The specified q-ai-drug output directory was not found: {resolved_absolute}"
        )

    return resolved_absolute
