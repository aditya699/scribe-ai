1. uv venv #creates a virtual environment
2. venv\Scripts\activate #activates the virtual environment
3. uv pip install .[dev] #installs the dependencies for the project
4. uvicorn main:app --reload #runs the server