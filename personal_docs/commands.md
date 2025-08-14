1. uv venv #creates a virtual environment
# This is for first time setup
2. venv\Scripts\activate #activates the virtual environment
3. uv pip install .[dev] #installs the dependencies for the project
4. uvicorn main:app --reload #runs the server

# After that what all dependencies you will add in the pyproject.toml file to update ur venv use 

5. uv sync --extra dev
