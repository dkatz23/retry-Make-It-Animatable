# Version: 1.0.0

# a.1 Imports and Initial Setup
import os
import tempfile
import threading
import requests
from fastapi import FastAPI, Request
import uvicorn
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# FastAPI app
api_app = FastAPI()

# b.1 API Server Setup Functions
def start_api_thread(pipeline_function, DB_class):
    """Start the API server in a background thread

    Args:
        pipeline_function: The _pipeline function from the main app
        DB_class: The DB class from the main app
    """
    api_thread = threading.Thread(
        target=run_api,
        args=(pipeline_function, DB_class),
        daemon=True
    )
    api_thread.start()
    logger.info("Started FastAPI server thread")
    return api_thread


def run_api(pipeline_function, DB_class):
    """Run the FastAPI server

    Args:
        pipeline_function: The _pipeline function from the main app
        DB_class: The DB class from the main app
    """
    api_app.state.pipeline_function = pipeline_function
    api_app.state.DB_class = DB_class
    uvicorn.run(api_app, host="0.0.0.0", port=8000)


# c.1 API Endpoint for Rigging from URL
@api_app.post("/api/rig-from-url")
async def rig_from_url_api(request: Request):
    """API endpoint to rig a model from a URL and retrieve the .glb output

    Args:
        request: The FastAPI request with JSON payload containing 'url'

    Returns:
        JSON response with the persistent URL to the rigged .glb model
    """
    try:
        # Get data from the request
        data = await request.json()
        model_url = data.get("url")
        if not model_url:
            logger.error("No model URL provided")
            return {"status": "error", "message": "Model URL is required"}

        logger.info(f"Processing model from URL: {model_url}")

        # Get the pipeline function and DB class
        pipeline_function = api_app.state.pipeline_function
        DB_class = api_app.state.DB_class

        # Download the model
        local_filename = os.path.join(tempfile.gettempdir(), model_url.split('/')[-1])
        logger.info(f"Downloading model to: {local_filename}")
        with requests.get(model_url, stream=True) as r:
            r.raise_for_status()
            with open(local_filename, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)

        # Rig the model
        logger.info("Starting rigging pipeline")
        db = DB_class()
        for step in pipeline_function(
            input_path=local_filename,
            is_gs=False,
            opacity_threshold=0.01,
            no_fingers=True,
            rest_pose_type="No",
            ignore_pose_parts=[],
            input_normal=False,
            bw_fix=True,
            bw_vis_bone="LeftArm",
            reset_to_rest=True,
            animation_file=None,
            retarget=True,
            inplace=True,
            db=db,
            export_temp=True,
            original_filename=model_url,  # Pass the model_url as the original filename
        ):
            pass

        # Prioritize .glb output
        if db.anim_vis_path and os.path.isfile(db.anim_vis_path):
            rigged_path = db.anim_vis_path
            logger.info(f"Using rigged .glb output: {rigged_path}")
        elif db.anim_path and os.path.isfile(db.anim_path):
            rigged_path = db.anim_path
            logger.warning(f"No .glb output found, using .fbx: {rigged_path}")
        else:
            logger.error("Rigging failed: no output file found")
            return {"status": "error", "message": "Rigging failed: output file not found"}

        # Upload to Render.com
        logger.info(f"Uploading rigged model to Render.com: {rigged_path}")
        with open(rigged_path, "rb") as f:
            files = {"modelFile": (os.path.basename(rigged_path), f, "model/gltf-binary")}
            response = requests.post(
                "https://viverse-backend.onrender.com/api/upload-rigged-model",
                files=files,
                data={"clientType": "playcanvas"}
            )
            if response.status_code != 200:
                logger.error(f"Upload to Render.com failed: {response.text}")
                return {"status": "error", "message": f"Upload to Render.com failed with status code {response.status_code}"}
            result = response.json()
            persistent_url = result.get("persistentUrl")
            if not persistent_url:
                logger.error("No persistent URL returned from Render.com")
                return {"status": "error", "message": "No persistent URL returned from Render.com"}

        logger.info(f"Successfully uploaded rigged model to: {persistent_url}")
        return {"status": "done", "persistentUrl": persistent_url}
    except Exception as e:
        logger.error(f"Error in rig_from_url_api: {str(e)}")
        return {"status": "error", "message": str(e)}

# d.1 API Endpoint for Animating from URL
@api_app.post("/api/animate-from-url")
async def animate_from_url_api(request: Request):
    """API endpoint to rig and animate a model from a URL and retrieve the animated .glb output

    Args:
        request: The FastAPI request with JSON payload containing 'url'

    Returns:
        JSON response with the persistent URL to the animated .glb model
    """
    try:
        # Get data from the request
        data = await request.json()
        model_url = data.get("url")
        if not model_url:
            logger.error("No model URL provided for animation")
            return {"status": "error", "message": "Model URL is required for animation"}

        logger.info(f"Processing model for animation from URL: {model_url}")

        # Get the pipeline function and DB class
        pipeline_function = api_app.state.pipeline_function
        DB_class = api_app.state.DB_class

        # Download the model
        local_filename = os.path.join(tempfile.gettempdir(), model_url.split('/')[-1])
        logger.info(f"Downloading model to: {local_filename}")
        with requests.get(model_url, stream=True) as r:
            r.raise_for_status()
            with open(local_filename, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)

        # Use the standard running animation file (ensure path is correct relative to the main script)
        # Adjust path if necessary based on where animateRIG_app_workingMay1.py runs from
        animation_file = os.path.abspath(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data/Standard Run.fbx')) # Assuming data dir is one level up
        if not os.path.isfile(animation_file):
             animation_file = os.path.abspath("./data/Standard Run.fbx") # Fallback if structure differs
             if not os.path.isfile(animation_file):
                 logger.error(f"Default animation file not found at expected paths: {animation_file}")
                 return {"status": "error", "message": f"Default animation file not found"}
        logger.info(f"Using animation file: {animation_file}")

        # Rig and animate the model
        logger.info("Starting animation pipeline")
        db = DB_class()
        for step in pipeline_function(
            input_path=local_filename,
            is_gs=False,
            opacity_threshold=0.01,
            no_fingers=True,
            rest_pose_type="No",
            ignore_pose_parts=[],
            input_normal=False,
            bw_fix=True,
            bw_vis_bone="LeftArm",
            reset_to_rest=True,  # Important: Reset to rest for correct animation
            animation_file=animation_file, # Apply the animation
            retarget=True,
            inplace=True,
            db=db,
            export_temp=True,
            original_filename=model_url,  # Pass the model_url as the original filename
        ):
            pass

        # Always prioritize the animated GLB preview model
        if db.anim_vis_path and os.path.isfile(db.anim_vis_path):
            animated_path = db.anim_vis_path
            logger.info(f"Using animated .glb output: {animated_path}")
        else:
            # Attempt to find the FBX if GLB failed, but ideally GLB should be generated
            if db.anim_path and os.path.isfile(db.anim_path):
                 logger.warning(f"Animated .glb preview not found, attempting to use FBX: {db.anim_path} (Upload might fail if not GLB)")
                 animated_path = db.anim_path # This might not work if server expects GLB
            else:
                logger.error("Animation failed: no output file found")
                return {"status": "error", "message": "Animation failed: output file not found"}


        # Upload to Render.com
        logger.info(f"Uploading animated model to Render.com: {animated_path}")
        with open(animated_path, "rb") as f:
            # Ensure correct MIME type for GLB
            mime_type = "model/gltf-binary" if animated_path.lower().endswith(".glb") else "application/octet-stream" # Fallback
            files = {"modelFile": (os.path.basename(animated_path), f, mime_type)}
            response = requests.post(
                "https://viverse-backend.onrender.com/api/upload-rigged-model",
                files=files,
                data={"clientType": "playcanvas"} # Keep clientType consistent
            )
            if response.status_code != 200:
                logger.error(f"Upload to Render.com failed: {response.text}")
                return {"status": "error", "message": f"Upload to Render.com failed with status code {response.status_code}"}
            result = response.json()
            persistent_url = result.get("persistentUrl")
            if not persistent_url:
                logger.error("No persistent URL returned from Render.com")
                return {"status": "error", "message": "No persistent URL returned from Render.com"}

        logger.info(f"Successfully uploaded animated model to: {persistent_url}")
        return {"status": "done", "persistentUrl": persistent_url}
    except Exception as e:
        logger.error(f"Error in animate_from_url_api: {str(e)}")
        return {"status": "error", "message": str(e)}
