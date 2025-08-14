'''
NOTE:
1.This script is used to print the folder structure of the project.This will be used to run everytime i wish to use claude/chatgpt to generate code , since models require context and folder structure helps them to render correct code upfront.
2.This has nothing to do with the project, but is a helpful script to have.
'''

import os

def print_tree(directory, prefix=""):
    entries = sorted(os.listdir(directory))
    entries = [e for e in entries if not e.startswith('__pycache__')]
    
    for index, entry in enumerate(entries):
        path = os.path.join(directory, entry)
        connector = "├── " if index < len(entries) - 1 else "└── "
        print(prefix + connector + entry)
        
        if os.path.isdir(path):
            extension = "│   " if index < len(entries) - 1 else "    "
            print_tree(path, prefix + extension)

if __name__ == "__main__":
    print("📁 Folder Structure:\n")
    root_path = "../app"  # You can change this to any directory path
    print_tree(root_path)
