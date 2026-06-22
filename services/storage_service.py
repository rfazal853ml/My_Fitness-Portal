"""
Supabase Storage Service — Handle image uploads and management
"""
from fastapi import HTTPException
from services.supabase_client import get_supabase
import os


class StorageService:
    BUCKET_NAME = "user-photos"  # Supabase storage bucket for profile images

    @staticmethod
    async def ensure_bucket_exists() -> None:
        """
        Create the profiles bucket if it doesn't already exist.
        Called during app startup.
        """
        db = get_supabase()
        
        try:
            # Try to list objects in the bucket to see if it exists
            db.storage.from_(StorageService.BUCKET_NAME).list()
        except Exception as e:
            # Bucket doesn't exist, create it
            if "Bucket not found" in str(e):
                try:
                    db.storage.create_bucket(
                        StorageService.BUCKET_NAME,
                        options={"public": True}  # Make bucket public
                    )
                    print(f"✓ Created '{StorageService.BUCKET_NAME}' storage bucket")
                except Exception as create_error:
                    print(f"⚠ Warning: Failed to create storage bucket: {str(create_error)}")
            else:
                print(f"⚠ Warning: Storage error: {str(e)}")

    @staticmethod
    async def upload_profile_image(file, user_id: str) -> str:
        """
        Upload a profile image to Supabase Storage.
        Returns the public URL of the uploaded image.
        """
        db = get_supabase()
        
        if not file or not file.filename:
            return None

        try:
            # Read file content
            file_content = await file.read()
            
            # Generate unique filename: {user_id}_{original_filename}
            filename = f"{user_id}_{file.filename}"
            
            # Upload to Supabase Storage under profiles bucket
            response = db.storage.from_(StorageService.BUCKET_NAME).upload(
                path=filename,
                file=file_content,
                file_options={"content-type": file.content_type or "image/jpeg"}
            )
            
            # Get the public URL for the uploaded image
            public_url = db.storage.from_(StorageService.BUCKET_NAME).get_public_url(filename)
            
            return public_url
        
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"Failed to upload profile image: {str(e)}"
            )

    @staticmethod
    def delete_profile_image(photo_url: str) -> None:
        """
        Delete a profile image from Supabase Storage.
        Extracts the filename from the public URL.
        """
        if not photo_url:
            return
        
        try:
            db = get_supabase()
            
            # Extract filename from URL (last part after /)
            # URL format: https://{project}.supabase.co/storage/v1/object/public/profiles/{filename}
            filename = photo_url.split("/")[-1]
            
            # Delete from storage
            db.storage.from_(StorageService.BUCKET_NAME).remove([filename])
        
        except Exception as e:
            # Log but don't raise — deletion failure shouldn't block the flow
            print(f"Warning: Failed to delete profile image: {str(e)}")

