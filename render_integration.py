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

     @api_app.post("/api/rig-from-url")
     async def rig_from_url_api(request: Request):
         """API endpoint to rig a model from a URL and retrieve the .glb output

         Args:
             request: The FastAPI request containing a JSON payload with 'url'

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
             ):
                 pass

             # Determine which output file to use (prioritize .glb)
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
